//! The Arslan desktop shell.
//!
//! Arslan's UI is not bundled into this webview. The Python sidecar serves it
//! (`server/main.py` mounts the built SPA), so this shell's entire job is:
//!
//!   1. start the sidecar,
//!   2. read the port it announces on stdout,
//!   3. point the window at it,
//!   4. make sure the sidecar dies when the app does.
//!
//! Step 4 is not optional bookkeeping: the sidecar owns the SQLite database.
//! An orphan left running after the window closes keeps a lock on it, and the
//! next launch fails in a way that looks like data corruption.

use std::io::{BufRead, BufReader, Read, Write};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::UpdaterExt;

/// Must match `PORT_LINE_PREFIX` in packaging/server_entry.py. Changing either
/// side alone leaves the window stuck on the splash screen forever.
const PORT_LINE_PREFIX: &str = "ARSLAN_PORT=";

/// How long to wait for that line before giving up. Generous because a first
/// launch runs database migrations before the port is announced; the splash
/// screen explains the wait.
const STARTUP_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(90);

/// Holds the sidecar so it can be killed on exit. `Mutex<Option<Child>>`
/// rather than a bare Child: `take()` on shutdown means a second exit event
/// cannot try to kill an already-reaped process.
#[derive(Default)]
struct Sidecar(Mutex<Option<Child>>);

/// Start the sidecar and block until it announces its port.
///
/// Blocking is deliberate. Doing this asynchronously would let the window
/// appear before there is anything to show and require a second code path for
/// "port arrived late"; the splash screen already covers the wait.
fn start_sidecar(app: &tauri::AppHandle) -> Result<(u16, Child), String> {
    let exe = app
        .path()
        .resolve("sidecar/arslan-server", tauri::path::BaseDirectory::Resource)
        .map_err(|e| format!("cannot locate the bundled sidecar: {e}"))?;

    if !exe.exists() {
        return Err(format!(
            "sidecar missing at {}. The app bundle was built without it — see \
             packaging/build_dmg.sh, which stages packaging/dist into \
             src-tauri/binaries/sidecar.",
            exe.display()
        ));
    }

    let mut child = Command::new(&exe)
        // stdin is PIPED and the handle is then held for the life of this
        // process. That pipe is the sidecar's death signal: when we die — for
        // ANY reason, including SIGKILL, where our exit handlers never run —
        // the write end closes and the sidecar reads EOF and exits. Without
        // it, a force-quit leaves an orphan holding the SQLite lock, and the
        // next launch looks like database corruption. Measured: killing this
        // process with the handlers in place still left the sidecar running.
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        // stderr is INHERITED, not piped: uvicorn logs there, and a piped
        // stderr nobody drains fills its buffer and deadlocks the sidecar
        // once it has logged ~64KB. Inheriting also means crash output lands
        // in Console.app where it can actually be read.
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| format!("cannot start the sidecar: {e}"))?;

    // Deliberately NOT taken: dropping the ChildStdin would close the pipe
    // immediately and kill the sidecar on startup. It must live exactly as
    // long as this process, which is what storing the Child in state does.
    debug_assert!(child.stdin.is_some(), "stdin pipe is the sidecar's lifeline");

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "sidecar produced no stdout".to_string())?;

    // Read the handshake on a worker thread so a sidecar that never prints
    // anything cannot hang the main thread past the timeout.
    //
    // The thread KEEPS DRAINING after the port arrives, and that is not
    // tidiness. Returning early drops the BufReader, closing our read end;
    // the sidecar's next write to stdout then fails with EPIPE. uvicorn logs
    // there, so every request produced a "--- Logging error --- BrokenPipeError"
    // traceback in the packaged app. Draining to EOF also gives us the
    // sidecar's own output in Console.app, where it can be read after a crash.
    let (tx, rx) = std::sync::mpsc::channel::<Result<u16, String>>();
    std::thread::spawn(move || {
        let mut announced = false;
        for line in BufReader::new(stdout).lines() {
            let Ok(line) = line else { break };
            if !announced {
                if let Some(rest) = line.strip_prefix(PORT_LINE_PREFIX) {
                    let parsed = rest
                        .trim()
                        .parse::<u16>()
                        .map_err(|_| format!("unparseable port line: {line:?}"));
                    let _ = tx.send(parsed);
                    announced = true;
                    continue;
                }
            }
            eprintln!("[sidecar] {line}");
        }
        if !announced {
            let _ = tx.send(Err(format!(
                "sidecar exited without printing {PORT_LINE_PREFIX}<port>"
            )));
        }
    });

    match rx.recv_timeout(STARTUP_TIMEOUT) {
        Ok(Ok(port)) => Ok((port, child)),
        Ok(Err(e)) => {
            let _ = child.kill();
            Err(e)
        }
        Err(_) => {
            let _ = child.kill();
            Err(format!(
                "sidecar did not announce a port within {}s",
                STARTUP_TIMEOUT.as_secs()
            ))
        }
    }
}

/// Block until the sidecar answers `/api/v1/health` with a 200.
///
/// Two things depend on this, not one: the webview navigates exactly once, so
/// pointing it at a port that is announced but not yet serving shows a
/// connection error the user has to fix by relaunching; and the api_token
/// file is written during server startup, so reading it before health-OK
/// races a file that may not exist yet. Raw std TCP on purpose — pulling in
/// an HTTP client crate to send one GET would be the heavier wrong.
fn wait_for_health(port: u16) -> Result<(), String> {
    let deadline = std::time::Instant::now() + STARTUP_TIMEOUT;
    let addr = format!("127.0.0.1:{port}");
    while std::time::Instant::now() < deadline {
        if let Ok(mut s) = std::net::TcpStream::connect(&addr) {
            let _ = s.set_read_timeout(Some(std::time::Duration::from_secs(3)));
            let req = format!(
                "GET /api/v1/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
            );
            if s.write_all(req.as_bytes()).is_ok() {
                let mut buf = String::new();
                let _ = s.read_to_string(&mut buf);
                if buf.starts_with("HTTP/1.1 200") || buf.starts_with("HTTP/1.0 200") {
                    return Ok(());
                }
            }
        }
        std::thread::sleep(std::time::Duration::from_millis(300));
    }
    Err(format!("sidecar port {port} never answered /api/v1/health"))
}

/// Read the bearer token the sidecar persisted, for injection into the webview.
///
/// The sidecar runs with ARSLAN_PACKAGED=1, so auth is enforced and the token
/// lives at <data dir>/api_token (0o600). The path is fixed because
/// server_entry strips ARSLAN_DATA_DIR in frozen builds — if that ever
/// changes, this must change with it.
///
/// The token is embedded in a JS string, so it is validated against the exact
/// alphabet `secrets.token_urlsafe` produces rather than escaped: a value that
/// is not [A-Za-z0-9_-] is not our token, and refusing it beats quoting it.
fn read_api_token() -> Option<String> {
    let home = std::env::var_os("HOME")?;
    let path = std::path::Path::new(&home)
        .join("Library/Application Support/Arslan/api_token");
    let token = std::fs::read_to_string(path).ok()?.trim().to_string();
    if !token.is_empty()
        && token
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        Some(token)
    } else {
        None
    }
}

/// Check the release feed once, in the background, and walk the user through
/// installing if there is something newer.
///
/// This call is the entire difference between "auto-update works" and "every
/// installed copy is stranded forever": Tauri v2's updater is fully
/// programmatic — registering the plugin wires the keys and the endpoint but
/// checks NOTHING on its own. v0.1.0/v0.1.1 shipped exactly that way, which
/// is why they never showed a prompt and had to be replaced by hand.
///
/// Every failure path is silent BY DESIGN except a failed install: an offline
/// machine or an unreachable feed is a normal morning, not an error the user
/// can act on. README's Status section discloses that silence.
fn check_for_updates(app: tauri::AppHandle) {
    tauri::async_runtime::spawn(async move {
        let updater = match app.updater() {
            Ok(u) => u,
            Err(e) => {
                eprintln!("updater unavailable: {e}");
                return;
            }
        };
        let update = match updater.check().await {
            Ok(Some(u)) => u,
            Ok(None) => return, // already newest
            Err(e) => {
                eprintln!("update check failed (offline is normal): {e}");
                return;
            }
        };

        let version = update.version.clone();
        let notes = update.body.clone().unwrap_or_default();
        let yes = app
            .dialog()
            .message(format!(
                "Arslan {version} is available.

{}

Download and install now?",
                notes.trim()
            ))
            .title("Update available")
            .kind(MessageDialogKind::Info)
            .buttons(MessageDialogButtons::OkCancelCustom(
                "Install".into(),
                "Later".into(),
            ))
            .blocking_show();
        if !yes {
            return;
        }

        // Signature verification against the compiled-in pubkey happens inside
        // download_and_install; a tampered artefact fails here, not after.
        match update.download_and_install(|_, _| {}, || {}).await {
            Ok(()) => {
                let restart = app
                    .dialog()
                    .message(format!(
                        "Arslan {version} is installed. Restart now to use it?"
                    ))
                    .title("Update ready")
                    .kind(MessageDialogKind::Info)
                    .buttons(MessageDialogButtons::OkCancelCustom(
                        "Restart".into(),
                        "Later".into(),
                    ))
                    .blocking_show();
                if restart {
                    app.restart();
                }
            }
            Err(e) => {
                // The ONE failure worth surfacing: the user said "install" and
                // it did not happen.
                app.dialog()
                    .message(format!("The update could not be installed: {e}"))
                    .title("Update failed")
                    .kind(MessageDialogKind::Error)
                    .blocking_show();
            }
        }
    });
}

/// True when the app is running from a place that can vanish from under it:
/// a mounted disk image (/Volumes/…) or a Gatekeeper app-translocation
/// mount. Seen in the field (v0.1.2): the sidecar lazy-loads bundle files
/// per request (e.g. certifi's CA bundle for TLS), so once the DMG volume
/// is force-ejected the UI keeps running but every LLM call fails with
/// "[Errno 2] No such file or directory". The auto-updater is also unable
/// to replace files on a read-only volume.
fn is_ephemeral_install_path(exe: &str) -> bool {
    exe.starts_with("/Volumes/") || exe.contains("/AppTranslocation/")
}

/// Walk up from the executable to the enclosing .app bundle root.
fn app_bundle_root(exe: &std::path::Path) -> Option<std::path::PathBuf> {
    exe.ancestors()
        .find(|p| p.extension().is_some_and(|e| e == "app"))
        .map(|p| p.to_path_buf())
}

/// Offer to copy the bundle into /Applications and relaunch from there.
/// Runs BEFORE the sidecar starts so the freshly launched copy never races
/// this process for the database. Declining is fine — the app works from a
/// DMG until the volume is ejected — so this stays a proposal, not a gate.
#[cfg(target_os = "macos")]
fn offer_install_to_applications(app: &tauri::App, exe: &std::path::Path) {
    let Some(bundle) = app_bundle_root(exe) else {
        return;
    };
    let yes = app
        .dialog()
        .message(
            "Arslan is running straight from its disk image. Ejecting the \
             image would break the running app, and automatic updates cannot \
             work here.\n\nArslan 正在从安装镜像(DMG)中直接运行:镜像被推出后 \
             app 会失灵,自动更新也无法工作。\n\nInstall to the Applications \
             folder and relaunch? / 安装到「应用程序」并重新打开?",
        )
        .title("Install Arslan / 安装 Arslan")
        .kind(MessageDialogKind::Info)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Install / 安装".into(),
            "Not now / 暂不".into(),
        ))
        .blocking_show();
    if !yes {
        return;
    }

    let dest = std::path::Path::new("/Applications/Arslan.app");
    // Replacing an existing copy is installer semantics; the path is our own
    // fixed bundle name, never derived from input.
    if dest.exists() {
        let _ = std::fs::remove_dir_all(dest);
    }
    // ditto preserves code signatures and extended attributes; plain fs::copy
    // would produce a bundle Gatekeeper rejects.
    let copied = std::process::Command::new("/usr/bin/ditto")
        .arg(&bundle)
        .arg(dest)
        .status()
        .map(|s| s.success())
        .unwrap_or(false);
    if !copied {
        app.dialog()
            .message(
                "Could not copy Arslan into /Applications. Please drag it \
                 there in Finder instead.\n\n自动安装失败,请在访达中手动把 \
                 Arslan 拖进「应用程序」。",
            )
            .title("Install failed / 安装失败")
            .kind(MessageDialogKind::Error)
            .blocking_show();
        return;
    }
    let _ = std::process::Command::new("/usr/bin/open").arg(dest).spawn();
    // The sidecar has not started yet, so exiting here cannot orphan it or
    // hold the database lock against the relaunched copy.
    std::process::exit(0);
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .manage(Sidecar::default())
        .setup(|app| {
            #[cfg(target_os = "macos")]
            if let Ok(exe) = std::env::current_exe() {
                if is_ephemeral_install_path(&exe.to_string_lossy()) {
                    offer_install_to_applications(app, &exe);
                }
            }

            let handle = app.handle().clone();
            let (port, child) = start_sidecar(&handle)?;
            app.state::<Sidecar>().0.lock().unwrap().replace(child);

            // 127.0.0.1, never "localhost": on a machine where localhost
            // resolves to ::1 first, the webview would try IPv6 against a
            // server bound only to IPv4 and show a connection error.
            let url = format!("http://127.0.0.1:{port}")
                .parse()
                .map_err(|e| format!("built an invalid sidecar URL: {e}"))?;

            // Health first: the webview navigates once, and the token file is
            // written during server startup — both need the server actually up.
            wait_for_health(port)?;

            let mut win = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
                .title("Arslan")
                .inner_size(1280.0, 840.0)
                .min_inner_size(900.0, 600.0);

            // No opaque white title bar: the webview fills the window and the
            // native traffic lights float over the sidebar's top-left corner
            // (which the SPA keeps free of content). Overlay leaves no native
            // strip to drag by, so the SPA marks its sidebar header as
            // data-tauri-drag-region and capabilities/remote-ui-drag.json
            // grants that local origin exactly the two drag commands.
            #[cfg(target_os = "macos")]
            {
                win = win
                    .title_bar_style(tauri::TitleBarStyle::Overlay)
                    .hidden_title(true)
                    .traffic_light_position(tauri::LogicalPosition::new(13.0, 16.0));
            }

            // The other half of the auth contract. The sidecar enforces auth
            // (ARSLAN_PACKAGED=1); the SPA reads window.__ARSLAN_TOKEN__ at
            // startup (web/src/lib/injectedToken.ts). Skipping injection when
            // the file is unreadable is deliberate fail-visible: the UI's API
            // calls 401 immediately, instead of the server silently running
            // open to every local process.
            match read_api_token() {
                Some(token) => {
                    win = win.initialization_script(&format!(
                        "window.__ARSLAN_TOKEN__ = \"{token}\";"
                    ));
                }
                None => eprintln!(
                    "WARNING: no readable api_token — the UI will be unauthenticated \
                     against an auth-enforcing server"
                ),
            }

            win.build()?;

            // AFTER the window exists: a blocking dialog with no window behind
            // it can appear beneath other apps, and an update prompt before
            // the app has even shown itself reads as malware.
            check_for_updates(handle);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the Arslan shell")
        .run(|app, event| {
            // Both events matter: Exit covers quit-from-menu, ExitRequested
            // covers the last window closing. Missing either leaves an orphan
            // holding the database lock.
            if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
                if let Some(mut child) = app.state::<Sidecar>().0.lock().unwrap().take() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dmg_and_translocation_paths_are_ephemeral() {
        assert!(is_ephemeral_install_path(
            "/Volumes/Arslan/Arslan.app/Contents/MacOS/arslan"
        ));
        assert!(is_ephemeral_install_path(
            "/private/var/folders/ab/T/AppTranslocation/9C1D/d/Arslan.app/Contents/MacOS/arslan"
        ));
    }

    #[test]
    fn real_installs_are_not_ephemeral() {
        assert!(!is_ephemeral_install_path(
            "/Applications/Arslan.app/Contents/MacOS/arslan"
        ));
        // A path merely mentioning Volumes deeper down must not trip it.
        assert!(!is_ephemeral_install_path(
            "/Users/alice/Applications/Volumes-notes/Arslan.app/Contents/MacOS/arslan"
        ));
    }

    #[test]
    fn bundle_root_is_the_dot_app_ancestor() {
        let exe = std::path::Path::new("/Volumes/Arslan/Arslan.app/Contents/MacOS/arslan");
        assert_eq!(
            app_bundle_root(exe).unwrap(),
            std::path::Path::new("/Volumes/Arslan/Arslan.app")
        );
        assert_eq!(app_bundle_root(std::path::Path::new("/usr/bin/true")), None);
    }
}

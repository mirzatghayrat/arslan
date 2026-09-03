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

pub mod endpoint;
mod listen;
mod proxy;
mod voice;
use std::sync::Mutex;

use tauri::{Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::UpdaterExt;

/// Must match `PORT_LINE_PREFIX` in packaging/server_entry.py. Changing either
/// side alone leaves the window stuck on the splash screen forever.
const PORT_LINE_PREFIX: &str = "ARSLAN_PORT=";

/// How long to wait for that line before giving up. Generous because a first
/// launch runs database migrations before the port is announced; the splash
/// screen explains the wait.
const STARTUP_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(90);

/// Shared window geometry. The splash and the real window are built at the same
/// size and both `.center()`, so the swap between them moves nothing.
const WINDOW_W: f64 = 1280.0;
const WINDOW_H: f64 = 840.0;

/// Minimum time the launch screen stays up, measured from when its window is
/// created — not from process start, because the DMG "install to Applications"
/// prompt runs before it and can hold for minutes.
///
/// A cold start measured 1.43s from launch to health-OK, so this is mostly a
/// floor rather than a wait: it buys roughly 0.6s so the clip reads as a launch
/// screen instead of a flicker. It is one constant on purpose.
const SPLASH_FLOOR: std::time::Duration = std::time::Duration::from_millis(2000);

/// Lockstep with the `#clip` transition duration in desktop/splash/index.html.
/// Rust asks the page to fade, waits this long, then swaps windows; if the two
/// numbers drift apart the swap happens mid-fade and the flash comes back.
const SPLASH_FADE_OUT: std::time::Duration = std::time::Duration::from_millis(400);

/// Backstop for a main window whose page never finishes loading. Showing a
/// half-loaded window beats leaving the user on a launch screen that will never
/// end, and the boot veil means a page still rendering looks like the splash.
const REVEAL_DEADLINE: std::time::Duration = std::time::Duration::from_secs(15);

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
        .resolve(
            "sidecar/arslan-server",
            tauri::path::BaseDirectory::Resource,
        )
        .map_err(|e| format!("cannot locate the bundled sidecar: {e}"))?;

    if !exe.exists() {
        return Err(format!(
            "sidecar missing at {}. The app bundle was built without it — see \
             packaging/build_dmg.sh, which stages packaging/dist into \
             src-tauri/binaries/sidecar.",
            exe.display()
        ));
    }

    let mut cmd = Command::new(&exe);
    // Hand the sidecar the proxy this process had to go looking for. httpx
    // reads these variables and nothing else, and a Finder-launched app has
    // none of them, so without this every outbound call from the sidecar —
    // every LLM request included — goes direct on a machine that can only
    // reach the internet through a proxy.
    match proxy::resolve() {
        Some(ref url) => eprintln!("network: proxying through {url} (loopback exempt)"),
        // Said out loud because "no proxy" and "proxy we failed to find" look
        // identical from the outside, and the difference is the whole bug.
        None => eprintln!("network: direct (no proxy in the environment or System Settings)"),
    }
    if let Some(url) = proxy::resolve() {
        cmd.env("HTTPS_PROXY", &url)
            .env("HTTP_PROXY", &url)
            .env("ALL_PROXY", &url)
            // Loopback stays direct: the sidecar is on 127.0.0.1 and so is a
            // local model server. Proxying those would break a working setup.
            .env("NO_PROXY", proxy::NO_PROXY);
    }

    let mut child = cmd
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
    debug_assert!(
        child.stdin.is_some(),
        "stdin pipe is the sidecar's lifeline"
    );

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
    let path = std::path::Path::new(&home).join("Library/Application Support/Arslan/api_token");
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

/// Update lifecycle, shared with the SPA over the two IPC commands below.
///
/// UX decided by the user (v0.1.5 round): no blocking dialogs and no silent
/// auto-download. A found update only surfaces as a small corner pill in the
/// web UI; nothing downloads until the user clicks Install there, and the app
/// restarts right after a successful install. The check itself runs once at
/// startup plus on the "Check for Updates…" menu item — deliberately NO
/// periodic timer.
#[derive(Default)]
struct UpdateShared {
    status: Mutex<UpdateStatus>,
    /// The checked Update handle, kept so install_update() can consume it.
    pending: Mutex<Option<tauri_plugin_updater::Update>>,
}

#[derive(Clone, serde::Serialize)]
struct UpdateStatus {
    /// "none" | "checking" | "available" | "downloading" | "error"
    state: String,
    version: String,
    error: String,
}

// Not derived: a derived Default would say state:"" and the SPA would render a
// pill for a state that means "nothing happened yet". Caught by the packaged
// IPC probe before v0.1.5 shipped.
impl Default for UpdateStatus {
    fn default() -> Self {
        Self {
            state: "none".into(),
            version: String::new(),
            error: String::new(),
        }
    }
}

impl UpdateShared {
    fn set(&self, app: &tauri::AppHandle, state: &str, version: &str, error: &str) {
        let status = UpdateStatus {
            state: state.into(),
            version: version.into(),
            error: error.into(),
        };
        *self.status.lock().unwrap() = status.clone();
        // Announce every transition. The SPA polls every 60s while a check lasts
        // 1-3s, so the "checking" state exists on screen only because of this
        // push; emitting inside set() keeps the stored state and the announced
        // one from ever disagreeing. Failure is ignored: during the startup
        // check no window exists to hear it, and the poll still covers every
        // durable state.
        let _ = app.emit("update-status", status);
    }
}

/// Ruling ③A (spec ③, 2026-08-08): the shell opens EXACTLY ONE kind of URL for
/// the web side — https. Everything else is refused here, in the shell, because
/// the page content is the least trusted thing in the room: a prompt-injected
/// model or a hostile MCP description must not be able to launch file://,
/// custom schemes, or plain http through us. "Only backend-returned
/// authorization URLs" — the other half of the ruling — is enforced where the
/// URL originates (step 3's flow hands it straight from the SDK to this
/// command); the shell cannot know provenance, so it enforces what it can see.
fn https_only(url: &str) -> Result<(), String> {
    let lower = url.trim().to_ascii_lowercase();
    if lower.starts_with("https://") && !lower.starts_with("https:///") {
        Ok(())
    } else {
        Err(format!("refusing to open non-https url: {url}"))
    }
}

/// Open a URL in the user's default browser. macOS-only by the same argument as
/// the rest of this file: darwin-aarch64 is the one platform this shell ships on.
#[tauri::command]
fn open_external(url: String) -> Result<(), String> {
    https_only(&url)?;
    std::process::Command::new("open")
        .arg(&url)
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("could not open the browser: {e}"))
}

/// Poll target for the SPA's corner pill (web/src/components/UpdatePill.tsx).
#[tauri::command]
fn update_status(shared: tauri::State<'_, UpdateShared>) -> UpdateStatus {
    shared.status.lock().unwrap().clone()
}

/// The user clicked Install on the pill: download, verify, install, restart.
/// Signature verification against the compiled-in pubkey happens inside
/// download_and_install; a tampered artefact fails here, not after.
#[tauri::command]
async fn install_update(app: tauri::AppHandle) {
    let shared = app.state::<UpdateShared>();
    let Some(update) = shared.pending.lock().unwrap().take() else {
        return; // double-click race or stale pill — nothing staged
    };
    shared.set(&app, "downloading", &update.version, "");
    match update.download_and_install(|_, _| {}, || {}).await {
        Ok(()) => {
            // The user's click WAS the restart consent ("点安装就直接安装重启").
            app.restart();
        }
        Err(e) => {
            // The ONE failure worth surfacing: the user said "install" and it
            // did not happen. The pill shows it; no modal needed.
            eprintln!("update install failed: {e}");
            shared.set(&app, "error", &update.version, &e.to_string());
        }
    }
}

/// Check the release feed once, in the background.
///
/// This call is the entire difference between "auto-update works" and "every
/// installed copy is stranded forever": Tauri v2's updater is fully
/// programmatic — registering the plugin wires the keys and the endpoint but
/// checks NOTHING on its own. v0.1.0/v0.1.1 shipped exactly that way, which
/// is why they never showed a prompt and had to be replaced by hand.
///
/// `interactive` is true for the menu item, where silence would read as a
/// dead button: up-to-date and check-failure each get a small dialog. The
/// startup check keeps every failure path silent BY DESIGN — an offline
/// machine or an unreachable feed is a normal morning, not an error the user
/// can act on. README's Status section discloses that silence.
fn check_for_updates(app: tauri::AppHandle, interactive: bool) {
    tauri::async_runtime::spawn(async move {
        // Menu-triggered only: the pill shows a "checking" sweep so the click is
        // visibly alive. The startup check stays byte-for-byte silent — its
        // whole failure model (offline is a normal morning) depends on that.
        if interactive {
            app.state::<UpdateShared>().set(&app, "checking", "", "");
        }
        // Built rather than taken off the handle so the system proxy can be
        // attached: reqwest reads only the environment, which a Finder-launched
        // app does not have, and "could not reach the update feed" was the
        // first symptom of that on a proxied machine.
        let mut builder = app.updater_builder();
        if let Some(url) = proxy::resolve() {
            match url.parse() {
                Ok(parsed) => builder = builder.proxy(parsed),
                // An unparseable value is the user's own env var; say so once
                // and carry on direct rather than failing the whole check.
                Err(e) => eprintln!("ignoring unusable proxy {url:?}: {e}"),
            }
        }
        let updater = match builder.build() {
            Ok(u) => u,
            Err(e) => {
                eprintln!("updater unavailable: {e}");
                return;
            }
        };
        match updater.check().await {
            Ok(Some(update)) => {
                let shared = app.state::<UpdateShared>();
                shared.set(&app, "available", &update.version, "");
                shared.pending.lock().unwrap().replace(update);
                // No dialog even when interactive: the pill in the corner is
                // the one consistent surface for "there is an update".
            }
            Ok(None) => {
                if interactive {
                    // Leave "checking" BEFORE the blocking dialog, or the sweep
                    // keeps spinning behind the modal for as long as it is open.
                    // A stuck progress indicator is worse than none.
                    app.state::<UpdateShared>().set(&app, "none", "", "");
                    app.dialog()
                        .message("You're on the latest version. / 已是最新版。")
                        .title("Arslan")
                        .kind(MessageDialogKind::Info)
                        .blocking_show();
                }
            }
            Err(e) => {
                eprintln!("update check failed (offline is normal): {e}");
                if interactive {
                    // Back to "none", NOT "error": the pill's error state means
                    // an install failed and offers no way out, while a failed
                    // CHECK already gets its own dialog right here — a red
                    // corner pill on top would say the same thing twice.
                    app.state::<UpdateShared>().set(&app, "none", "", "");
                    app.dialog()
                        .message(format!(
                            "Could not reach the update feed — are you online?\n\
                             无法连接更新源,请检查网络。\n\n{e}"
                        ))
                        .title("Check for Updates")
                        .kind(MessageDialogKind::Warning)
                        .blocking_show();
                }
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
    let _ = std::process::Command::new("/usr/bin/open")
        .arg(dest)
        .spawn();
    // The sidecar has not started yet, so exiting here cannot orphan it or
    // hold the database lock against the relaunched copy.
    std::process::exit(0);
}

/// Window labels. The boot thread looks windows up by label instead of
/// carrying handles, so a window that is gone is a `None` to skip rather than a
/// handle to something destroyed.
const SPLASH_LABEL: &str = "splash";
const MAIN_LABEL: &str = "main";

/// Everything between "the launch screen is up" and "the real window is up".
///
/// Runs on its own thread. Both of the steps it owns can take a long time on a
/// first launch — the sidecar announces its port only after migrations finish,
/// and health comes after that — and on the setup thread either one would
/// freeze the launch screen rather than play under it.
fn boot(app: tauri::AppHandle, splash_since: std::time::Instant) {
    let port = match start_sidecar(&app) {
        Ok((port, child)) => {
            app.state::<Sidecar>().0.lock().unwrap().replace(child);
            port
        }
        Err(e) => return report_boot_failure(&app, &e),
    };
    if let Err(e) = wait_for_health(port) {
        return report_boot_failure(&app, &e);
    }

    // The floor, then the fade.
    //
    // Fading rather than cutting is what lets the hand-off happen at any point
    // in the clip. The clip dims to the background colour only during its own
    // last half second, so cutting at the floor — which a 1.4s cold start
    // always reaches first — would swap away from a fully bright frame and put
    // back exactly the flash this whole arrangement exists to remove.
    let shown = splash_since.elapsed();
    if shown < SPLASH_FLOOR {
        std::thread::sleep(SPLASH_FLOOR - shown);
    }
    if let Some(splash) = app.get_webview_window(SPLASH_LABEL) {
        let _ = splash.eval("window.__arslanFadeOut && window.__arslanFadeOut()");
        std::thread::sleep(SPLASH_FADE_OUT);
    }

    // Windows have to be built on the main thread on macOS.
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || open_main_window(&handle, port));
}

/// Report a failed start on the window that is already in front of the user.
///
/// This path used to be `?` out of `setup`, which panicked before any window
/// had been built: the app died having shown nothing at all, and the user had
/// no way to tell a crash from a slow launch. The launch screen is on screen
/// by the time anything here can fail, so it carries the message.
fn report_boot_failure(app: &tauri::AppHandle, message: &str) {
    eprintln!("Arslan failed to start: {message}");
    if let Some(splash) = app.get_webview_window(SPLASH_LABEL) {
        // These strings are ours, not user input, but they are being pasted
        // into a JS string literal — quote them rather than trusting that no
        // future error message will ever contain a quote or a backslash.
        let escaped = message
            .replace('\\', "\\\\")
            .replace('"', "\\\"")
            .replace('\n', "\\n");
        let _ = splash.eval(format!(
            "window.__arslanBootError && window.__arslanBootError(\
             \"Arslan could not start.\\n\\n{escaped}\")"
        ));
    }
}

/// Build the real window hidden, and reveal it once its page has loaded.
///
/// Hidden-then-show is the whole point: the swap has to land on a painted page.
/// The SPA paints a #17150F boot veil before React exists (web/index.html), so
/// by the time the page reports Finished it is already the colour the launch
/// screen ended on and the exchange has nothing to show.
fn open_main_window(app: &tauri::AppHandle, port: u16) {
    // 127.0.0.1, never "localhost": on a machine where localhost resolves to
    // ::1 first, the webview would try IPv6 against a server bound only to
    // IPv4 and show a connection error.
    let url: tauri::Url = match format!("http://127.0.0.1:{port}").parse() {
        Ok(url) => url,
        Err(e) => {
            return report_boot_failure(app, &format!("built an invalid sidecar URL: {e}"));
        }
    };

    let mut win = WebviewWindowBuilder::new(app, MAIN_LABEL, WebviewUrl::External(url))
        .title("Arslan")
        .inner_size(WINDOW_W, WINDOW_H)
        .min_inner_size(900.0, 600.0)
        // Same size and same centring as the splash, so the swap moves nothing.
        .center()
        // Revealed by on_page_load below. A window shown at build time would be
        // white for as long as the SPA takes to load, which is the flash the
        // launch screen was added to remove.
        .visible(false)
        // Give file drags back to the page. wry installs an NSDragging
        // interceptor on macOS too (wkwebview/drag_drop.rs) and, once it
        // reports the drop handled, the OS default is never invoked — and the
        // OS default is what delivers HTML5 dragover/drop to the webview. So in
        // the packaged app a file dragged onto the second brain produced
        // NOTHING: no dashed-border feedback, no error, not even the "this build
        // can't read images" message, because the SPA never saw the event. Dev
        // browsers were unaffected, which is why this shipped. Arslan has no
        // native drop handler of its own — every drop target is HTML — so
        // disabling it costs nothing.
        .disable_drag_drop_handler()
        .on_page_load(|win, payload| {
            if matches!(payload.event(), tauri::webview::PageLoadEvent::Finished) {
                reveal(win.app_handle());
            }
        });

    // No opaque white title bar: the webview fills the window and the native
    // traffic lights float over the sidebar's top-left corner (which the SPA
    // keeps free of content). Overlay leaves no native strip to drag by, so the
    // SPA marks its sidebar header as data-tauri-drag-region and
    // capabilities/remote-ui-drag.json grants that local origin exactly the two
    // drag commands.
    #[cfg(target_os = "macos")]
    {
        win = win
            .title_bar_style(tauri::TitleBarStyle::Overlay)
            .hidden_title(true)
            .traffic_light_position(tauri::LogicalPosition::new(13.0, 16.0));
    }

    // One initialization script carrying two unrelated facts, because it has to
    // run before any page script does.
    //
    // The fade flag is unconditional: web/index.html removes its boot veil
    // during parse unless this says a launch screen is handing off to it, so a
    // browser tab and `npm run dev` never see a dark frame, and a missing token
    // must not also cost the fade.
    let mut init = String::from("window.__ARSLAN_SHELL_FADE_IN__ = true;");

    // The other half of the auth contract. The sidecar enforces auth
    // (ARSLAN_PACKAGED=1); the SPA reads window.__ARSLAN_TOKEN__ at startup
    // (web/src/lib/injectedToken.ts). Skipping injection when the file is
    // unreadable is deliberate fail-visible: the UI's API calls 401
    // immediately, instead of the server silently running open to every local
    // process.
    match read_api_token() {
        Some(token) => init.push_str(&format!("window.__ARSLAN_TOKEN__ = \"{token}\";")),
        None => eprintln!(
            "WARNING: no readable api_token — the UI will be unauthenticated \
             against an auth-enforcing server"
        ),
    }
    win = win.initialization_script(&init);

    if let Err(e) = win.build() {
        return report_boot_failure(app, &format!("could not open the main window: {e}"));
    }

    // Backstop for a page that never reports Finished. Without it a stalled
    // load leaves a hidden main window behind a launch screen that will never
    // end — a hang with no symptom to report. `reveal` is idempotent, so this
    // firing after a normal reveal does nothing.
    let deadline_handle = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(REVEAL_DEADLINE);
        let inner = deadline_handle.clone();
        let _ = deadline_handle.run_on_main_thread(move || reveal(&inner));
    });

    // AFTER the window exists so the pill has somewhere to appear. Startup-only
    // + the menu item — deliberately no periodic timer (user decision, v0.1.5).
    check_for_updates(app.clone(), false);
}

/// Show the main window and retire the launch screen, in that order and once.
///
/// The order is load-bearing twice over: closing the splash first would leave a
/// moment with no window at all, which shows the desktop through and — worse —
/// is the condition Tauri reports as ExitRequested, i.e. it would quit the app
/// during its own launch.
///
/// Idempotent because two things call it: the page-load callback and the
/// deadline backstop.
fn reveal(app: &tauri::AppHandle) {
    let Some(main) = app.get_webview_window(MAIN_LABEL) else {
        return;
    };
    if main.is_visible().unwrap_or(false) {
        return;
    }
    let _ = main.show();
    let _ = main.set_focus();
    if let Some(splash) = app.get_webview_window(SPLASH_LABEL) {
        let _ = splash.close();
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .manage(Sidecar::default())
        .manage(UpdateShared::default())
        .manage(listen::Listener::default())
        .manage(voice::Conversation::default())
        .invoke_handler(tauri::generate_handler![
            update_status,
            install_update,
            open_external,
            listen::voice_start,
            listen::voice_stop,
            voice::voice_conversation_start,
            voice::voice_conversation_stop,
            voice::voice_mute,
            voice::voice_unmute
        ])
        .on_menu_event(|app, event| {
            if event.id() == "check-for-updates" {
                check_for_updates(app.clone(), true);
            }
        })
        .setup(|app| {
            #[cfg(target_os = "macos")]
            if let Ok(exe) = std::env::current_exe() {
                if is_ephemeral_install_path(&exe.to_string_lossy()) {
                    offer_install_to_applications(app, &exe);
                }
            }

            // The launch screen goes up FIRST, before anything that can block,
            // and two separate facts each make that mandatory.
            //
            // (1) `app.windows` in tauri.conf.json is an empty array, so no
            //     window exists until one is built here. That is why
            //     desktop/splash/index.html shipped from the first packaged
            //     build onward and was never once on screen: nothing rendered
            //     it. Nobody noticed because a launch screen that never appears
            //     and a launch screen that flashes past in 1.4s look the same.
            // (2) Tauri's event loop does not start until this closure returns,
            //     so a window built here that then waited for the sidecar
            //     inline would exist without ever painting a frame.
            //
            // Hence the boot work moves to its own thread below.
            let splash_since = std::time::Instant::now();
            WebviewWindowBuilder::new(app, SPLASH_LABEL, WebviewUrl::App("index.html".into()))
                .title("Arslan")
                .inner_size(WINDOW_W, WINDOW_H)
                .resizable(false)
                .decorations(false)
                // The page paints its own rounded frame; the window behind it
                // must not paint a square one. Needs macOSPrivateApi in
                // tauri.conf.json or this flag silently does nothing.
                .transparent(true)
                .center()
                .build()?;

            // Built before the main window now, because at this point there is
            // no main window. The menu belongs to the app rather than to a
            // window, so nothing here depended on the old ordering.
            //
            // "Check for Updates…" lives in the app submenu, right under About
            // — the place macOS users actually look. Built from the default
            // menu so Edit/copy-paste etc. all survive.
            #[cfg(target_os = "macos")]
            {
                use tauri::menu::{Menu, MenuItem};
                let menu = Menu::default(app.handle())?;
                if let Some(tauri::menu::MenuItemKind::Submenu(app_menu)) = menu.items()?.first() {
                    let check = MenuItem::with_id(
                        app,
                        "check-for-updates",
                        "Check for Updates…",
                        true,
                        None::<&str>,
                    )?;
                    app_menu.insert(&check, 1)?;
                }
                app.set_menu(menu)?;
            }

            let handle = app.handle().clone();
            std::thread::spawn(move || boot(handle, splash_since));
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

    /// 🔴 These were the first tests CI ever ran for this crate: the module
    /// below predates the `cargo test` step and sat here unexecuted — a test
    /// that never runs and a test that passes look identical from the outside.
    #[test]
    fn https_is_allowed() {
        assert!(https_only("https://accounts.example.com/authorize?x=1").is_ok());
    }

    #[test]
    fn everything_else_is_refused() {
        for url in [
            "http://accounts.example.com/authorize", // downgrade, not a typo
            "file:///etc/passwd",
            "javascript:alert(1)",
            "https:///missing-host",
            "",
        ] {
            assert!(https_only(url).is_err(), "should refuse {url:?}");
        }
    }

    #[test]
    fn scheme_check_is_case_insensitive() {
        assert!(https_only("HTTPS://ok.example.com/a").is_ok());
    }

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

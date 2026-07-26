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

use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

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
    let (tx, rx) = std::sync::mpsc::channel::<Result<u16, String>>();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines() {
            let Ok(line) = line else { break };
            if let Some(rest) = line.strip_prefix(PORT_LINE_PREFIX) {
                let parsed = rest
                    .trim()
                    .parse::<u16>()
                    .map_err(|_| format!("unparseable port line: {line:?}"));
                let _ = tx.send(parsed);
                return;
            }
        }
        let _ = tx.send(Err(format!(
            "sidecar exited without printing {PORT_LINE_PREFIX}<port>"
        )));
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

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Sidecar::default())
        .setup(|app| {
            let handle = app.handle().clone();
            let (port, child) = start_sidecar(&handle)?;
            app.state::<Sidecar>().0.lock().unwrap().replace(child);

            // 127.0.0.1, never "localhost": on a machine where localhost
            // resolves to ::1 first, the webview would try IPv6 against a
            // server bound only to IPv4 and show a connection error.
            let url = format!("http://127.0.0.1:{port}")
                .parse()
                .map_err(|e| format!("built an invalid sidecar URL: {e}"))?;

            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
                .title("Arslan")
                .inner_size(1280.0, 840.0)
                .min_inner_size(900.0, 600.0)
                .build()?;
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

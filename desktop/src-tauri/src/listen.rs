//! Push-to-talk: hold, speak, let go, get text.
//!
//! The recognizer lives in a helper binary inside the app bundle rather than
//! here, because Speech and AVAudioEngine are Swift APIs and because the shell
//! already knows how to own a child that dies with it. The helper's stdin is
//! that contract: closing it means "the user let go", and it closes on its own
//! if this process dies, so a force-quit cannot leave the microphone open.
//!
//! Everything the helper says arrives as one JSON line and is forwarded to the
//! webview as an event. Errors included — a refused microphone must reach the
//! UI as a sentence, not as silence that reads like broken hardware.

use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;

use tauri::{AppHandle, Emitter, Manager};

/// The running helper, if the user is holding the button. `stdin` is kept
/// separately because releasing the button means dropping exactly that.
#[derive(Default)]
pub struct Listener {
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
}

/// Event name the webview listens on. One channel for every line the helper
/// emits, so a partial, a final and an error cannot get out of order.
const EVENT: &str = "voice://line";

fn helper_path(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    app.path()
        .resolve("listen/arslan-listen", tauri::path::BaseDirectory::Resource)
        .map_err(|e| format!("cannot locate the listener: {e}"))
}

#[tauri::command]
pub fn voice_start(app: AppHandle, locale: String) -> Result<(), String> {
    let state = app.state::<Listener>();
    // Holding the button twice over is not an error worth failing on, but two
    // helpers would fight for the microphone. Stop the first.
    let _ = stop_inner(&app);

    let exe = helper_path(&app)?;
    if !exe.exists() {
        return Err(format!(
            "the listener is missing from the bundle at {}",
            exe.display()
        ));
    }

    let mut child = Command::new(&exe)
        .arg(&locale)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| format!("cannot start the listener: {e}"))?;

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "the listener has no stdout".to_string())?;
    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| "the listener has no stdin".to_string())?;

    // One reader thread per press. It ends when the helper exits, which the
    // release of the button guarantees.
    let handle = app.clone();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if line.trim().is_empty() {
                continue;
            }
            let _ = handle.emit(EVENT, line);
        }
    });

    *state.child.lock().unwrap() = Some(child);
    *state.stdin.lock().unwrap() = Some(stdin);
    Ok(())
}

/// Release: close stdin and let the recognizer settle. We deliberately do NOT
/// kill the helper here — the last word is still being transcribed, and the
/// final line is the whole point of the press.
#[tauri::command]
pub fn voice_stop(app: AppHandle) -> Result<(), String> {
    stop_inner(&app);
    Ok(())
}

fn stop_inner(app: &AppHandle) -> bool {
    let state = app.state::<Listener>();
    let had = state.stdin.lock().unwrap().take().is_some_and(|mut s| {
        let _ = s.flush();
        true
    }); // dropped here: EOF reaches the helper
        // The child handle is kept so it can be reaped; the helper exits on its own
        // once it has emitted the final line.
    if let Some(mut c) = state.child.lock().unwrap().take() {
        std::thread::spawn(move || {
            let _ = c.wait();
        });
    }
    had
}

#[cfg(test)]
mod tests {
    use super::EVENT;

    #[test]
    fn the_event_name_is_the_one_the_webview_listens_on() {
        // A rename here without a matching rename in the frontend is silent:
        // the button would work, the helper would run, and no text would ever
        // appear. Pin the string on both sides.
        assert_eq!(EVENT, "voice://line");
    }
}

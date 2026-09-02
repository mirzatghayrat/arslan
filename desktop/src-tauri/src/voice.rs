//! Conversation mode: a long-lived ear, and the one decision the shell makes.
//!
//! The helper (`arslan-voice`) reports partials, finals and a level meter.
//! This module feeds those into `endpoint::Endpointer` and, when it says the
//! sentence is over, writes `end_utterance` back to the helper — which then
//! emits the final and re-arms. Every helper line is also forwarded verbatim
//! to the webview on `voice://conv`, errors included.

use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use tauri::{AppHandle, Emitter, Manager};

use crate::endpoint::Endpointer;

pub const EVENT: &str = "voice://conv";

#[derive(Default)]
pub struct Conversation {
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<Arc<Mutex<ChildStdin>>>>,
}

pub enum HelperLine {
    Ready,
    Partial(String),
    // The text is asserted by parse tests; `drive` never reads it because the
    // raw line (not this parsed form) is what reaches the webview.
    #[allow(dead_code)]
    Final(String),
    Level(f32),
    Other,
}

pub fn parse_helper_line(s: &str) -> HelperLine {
    let v: serde_json::Value = match serde_json::from_str(s) {
        Ok(v) => v,
        Err(_) => return HelperLine::Other,
    };
    match v.get("t").and_then(|t| t.as_str()) {
        Some("ready") => HelperLine::Ready,
        Some("partial") => match v.get("text").and_then(|t| t.as_str()) {
            Some(t) => HelperLine::Partial(t.to_string()),
            None => HelperLine::Other,
        },
        Some("final") => match v.get("text").and_then(|t| t.as_str()) {
            Some(t) => HelperLine::Final(t.to_string()),
            None => HelperLine::Other,
        },
        Some("level") => match v.get("peak").and_then(|p| p.as_f64()) {
            Some(p) => HelperLine::Level(p as f32),
            None => HelperLine::Other,
        },
        _ => HelperLine::Other,
    }
}

/// Feed one line into the endpointer. Returns true when `end_utterance`
/// should be written — at most once per armed request: after it fires, the
/// endpointer is put into a state that cannot fire again until `Ready`.
pub fn drive(ep: &mut Endpointer, line: &HelperLine, now_ms: u64) -> bool {
    match line {
        HelperLine::Ready => {
            ep.reset();
            false
        }
        HelperLine::Partial(t) => {
            ep.on_partial(t, now_ms);
            fire_if_due(ep, now_ms)
        }
        HelperLine::Level(p) => {
            ep.on_level(*p, now_ms);
            fire_if_due(ep, now_ms)
        }
        HelperLine::Final(_) | HelperLine::Other => false,
    }
}

fn fire_if_due(ep: &mut Endpointer, now_ms: u64) -> bool {
    if ep.should_end(now_ms) {
        // Consume: no second fire until the helper re-arms.
        ep.reset();
        true
    } else {
        false
    }
}

fn helper_path(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    app.path()
        .resolve("listen/arslan-voice", tauri::path::BaseDirectory::Resource)
        .map_err(|e| format!("cannot locate the voice helper: {e}"))
}

fn write_cmd(stdin: &Arc<Mutex<ChildStdin>>, cmd: &str) -> Result<(), String> {
    let mut s = stdin.lock().unwrap();
    writeln!(s, "{{\"c\":\"{cmd}\"}}")
        .and_then(|_| s.flush())
        .map_err(|e| format!("voice helper stdin: {e}"))
}

#[tauri::command]
pub fn voice_conversation_start(
    app: AppHandle,
    locale: String,
    silence_ms: u64,
) -> Result<(), String> {
    let state = app.state::<Conversation>();
    stop_inner(&app);

    let exe = helper_path(&app)?;
    if !exe.exists() {
        return Err(format!(
            "the voice helper is missing from the bundle at {}",
            exe.display()
        ));
    }
    let mut child = Command::new(&exe)
        .arg(&locale)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| format!("cannot start the voice helper: {e}"))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "the voice helper has no stdout".to_string())?;
    let stdin = Arc::new(Mutex::new(
        child
            .stdin
            .take()
            .ok_or_else(|| "the voice helper has no stdin".to_string())?,
    ));

    let handle = app.clone();
    let writer = stdin.clone();
    std::thread::spawn(move || {
        let t0 = Instant::now();
        let mut ep = Endpointer::new(silence_ms);
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if line.trim().is_empty() {
                continue;
            }
            let now = t0.elapsed().as_millis() as u64;
            if drive(&mut ep, &parse_helper_line(&line), now) {
                let _ = write_cmd(&writer, "end_utterance");
            }
            let _ = handle.emit(EVENT, line);
        }
        let _ = handle.emit(EVENT, r#"{"t":"ended"}"#.to_string());
    });

    *state.child.lock().unwrap() = Some(child);
    *state.stdin.lock().unwrap() = Some(stdin);
    Ok(())
}

#[tauri::command]
pub fn voice_conversation_stop(app: AppHandle) -> Result<(), String> {
    stop_inner(&app);
    Ok(())
}

#[tauri::command]
pub fn voice_mute(app: AppHandle) -> Result<(), String> {
    with_stdin(&app, "mute")
}

#[tauri::command]
pub fn voice_unmute(app: AppHandle) -> Result<(), String> {
    with_stdin(&app, "unmute")
}

fn with_stdin(app: &AppHandle, cmd: &str) -> Result<(), String> {
    let state = app.state::<Conversation>();
    let guard = state.stdin.lock().unwrap();
    match guard.as_ref() {
        Some(s) => write_cmd(s, cmd),
        None => Err("conversation mode is not running".to_string()),
    }
}

/// Dropping stdin is the stop signal (EOF); the helper releases the mic and
/// exits, and the reader thread ends with it.
fn stop_inner(app: &AppHandle) {
    let state = app.state::<Conversation>();
    state.stdin.lock().unwrap().take();
    let child = state.child.lock().unwrap().take();
    if let Some(mut c) = child {
        std::thread::spawn(move || {
            let _ = c.wait();
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::endpoint::Endpointer;

    #[test]
    fn parses_the_lines_that_drive_the_endpointer() {
        assert!(matches!(
            parse_helper_line(r#"{"t":"ready"}"#),
            HelperLine::Ready
        ));
        assert!(
            matches!(parse_helper_line(r#"{"t":"partial","text":"hi"}"#), HelperLine::Partial(t) if t == "hi")
        );
        assert!(
            matches!(parse_helper_line(r#"{"t":"final","text":"hi there"}"#), HelperLine::Final(t) if t == "hi there")
        );
        assert!(
            matches!(parse_helper_line(r#"{"t":"level","peak":0.25}"#), HelperLine::Level(p) if (p - 0.25).abs() < 1e-6)
        );
        assert!(matches!(
            parse_helper_line(r#"{"t":"state","muted":true}"#),
            HelperLine::Other
        ));
        assert!(matches!(parse_helper_line("not json"), HelperLine::Other));
        assert!(
            matches!(parse_helper_line(r#"{"t":"partial"}"#), HelperLine::Other),
            "a partial without text is not a partial"
        );
    }

    #[test]
    fn drive_asks_to_end_exactly_once_per_utterance() {
        let mut ep = Endpointer::new(900);
        assert!(!drive(&mut ep, &HelperLine::Ready, 0));
        assert!(!drive(&mut ep, &HelperLine::Level(0.5), 100));
        assert!(!drive(&mut ep, &HelperLine::Partial("open".into()), 300));
        assert!(!drive(&mut ep, &HelperLine::Level(0.5), 400));
        assert!(!drive(&mut ep, &HelperLine::Level(0.01), 1_200));
        assert!(
            drive(&mut ep, &HelperLine::Level(0.01), 1_300),
            "900 ms after the last voice"
        );
        // Until the helper re-arms (Ready), the same silence must not ask again.
        assert!(!drive(&mut ep, &HelperLine::Level(0.01), 1_400));
        assert!(!drive(&mut ep, &HelperLine::Final("open".into()), 1_500));
        // Ready resets: a new utterance starts from nothing.
        assert!(!drive(&mut ep, &HelperLine::Ready, 1_600));
        assert!(!drive(&mut ep, &HelperLine::Level(0.01), 3_000));
    }

    #[test]
    fn the_event_name_is_the_one_the_webview_listens_on() {
        assert_eq!(EVENT, "voice://conv");
    }
}

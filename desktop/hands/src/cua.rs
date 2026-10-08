//! Cua Driver as Hands' private worker (Hands v2, spec docs/specs/2026-10-08-0157-hands-v2.md §3).
//!
//! One `cua-driver __private-worker --generation <id>` child per Hands run, spoken to
//! over its stdin/stdout only — never the driver's socket daemon, whose socket admits
//! any process of the user (it checks only the uid) and so would lend Hands'
//! Accessibility and Screen Recording grants to anything. As Hands' child the worker
//! is in Hands' responsibility chain, so those grants are Hands'; it sits NEXT TO the
//! bundle and is checked against the sha256 recorded inside it before every spawn,
//! for the same reason as agent-desktop (integrity.rs).
//!
//! The worker's environment is rebuilt from nothing (`env_clear`): its HOME is a
//! folder inside Hands' own, so a user's own Cua install cannot change Arslan's driver
//! and Cua writes nothing elsewhere; telemetry is off three ways (this environment,
//! our fork's build, and the harness's network check).
//!
//! Wire protocol (cua-driver-sdk `worker.rs`, version 1): one JSON line per request
//! `{protocol_version, request_id, generation, operation, name?, arguments?}`, one JSON
//! line back `{protocol_version, request_id, generation, ok, completion, result?,
//! error?, error_code?}`. `completion` is `not_started | completed | unknown`: only
//! `not_started` may ever be sent again; `unknown` means "it may have happened".

use crate::argv::{refuse, Refusal};
use crate::integrity::Pinned;
use serde_json::{json, Value};
use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::atomic::{AtomicI32, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

pub const PROTOCOL_VERSION: u64 = 1;
/// A window state carries a screenshot as base64; nothing legitimate comes near this.
pub const MAX_LINE: usize = 48 * 1024 * 1024;
const STARTUP: Duration = Duration::from_secs(15);
/// Starting value (spec §3.3): cua's own figure for a background AX click is 1153 ms
/// at its 1000 ms default and 325 ms at 200 ms. Hands' own give-back guard stays.
const WINDOW_CHANGE_TIMEOUT_MS: &str = "300";
const LOG_LIMIT: u64 = 4 * 1024 * 1024;

#[derive(Debug, Clone)]
pub struct Config {
    /// `…/hands/cua-driver`, beside the bundle.
    pub binary: PathBuf,
    /// The sha256 it must have (recorded inside Hands' signed bundle); None only for
    /// development and tests.
    pub pinned: Option<Arc<Pinned>>,
    /// The worker's HOME: a private folder inside Hands' own.
    pub home: PathBuf,
    /// Where the worker's stderr goes (0600, inside Hands' folder).
    pub log: PathBuf,
    /// Hands' bundle id: the worker echoes it in its readiness proof and reports it as
    /// the owner of its permissions.
    pub host_bundle_id: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Completion {
    NotStarted,
    Completed,
    Unknown,
}

impl Completion {
    pub fn name(self) -> &'static str {
        match self {
            Completion::NotStarted => "not_started",
            Completion::Completed => "completed",
            Completion::Unknown => "unknown",
        }
    }

    fn parse(text: &str) -> Option<Completion> {
        match text {
            "not_started" => Some(Completion::NotStarted),
            "completed" => Some(Completion::Completed),
            "unknown" => Some(Completion::Unknown),
            _ => None,
        }
    }
}

/// The worker's answer to one tool call that it completed (successfully or not).
#[derive(Debug, Clone)]
pub struct Answer {
    pub ok: bool,
    pub result: Value,
    pub error_code: Option<String>,
    pub error: Option<String>,
}

/// A request that did not end in an answer: why, and whether it may have run.
#[derive(Debug, Clone)]
pub struct Failure {
    pub refusal: Refusal,
    pub completion: Completion,
}

fn failure(code: &'static str, message: impl Into<String>, completion: Completion) -> Failure {
    Failure {
        refusal: refuse(code, message),
        completion,
    }
}

struct Worker {
    child: Child,
    stdin: ChildStdin,
    stdout: Option<BufReader<ChildStdout>>,
    generation: String,
    next_id: u64,
}

impl Worker {
    fn reap(mut self) {
        drop(self.stdin);
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

pub struct Cua {
    config: Config,
    worker: Mutex<Option<Worker>>,
    /// The running worker's pid, readable without the worker lock so Stop can kill a
    /// worker that a request is blocked on.
    pid: AtomicI32,
}

impl Cua {
    pub fn new(config: Config) -> Cua {
        Cua {
            config,
            worker: Mutex::new(None),
            pid: AtomicI32::new(0),
        }
    }

    pub fn present(&self) -> bool {
        self.config.binary.is_file()
    }

    pub fn pinned(&self) -> Option<bool> {
        self.config.pinned.as_ref().map(|p| p.check().is_ok())
    }

    /// Kill the worker if one runs (Stop). A request blocked on it ends at once with
    /// `unknown`; the next request starts a new worker. True if there was one.
    pub fn stop(&self) -> bool {
        let pid = self.pid.swap(0, Ordering::SeqCst);
        if pid > 0 {
            unsafe {
                libc::kill(pid, libc::SIGKILL);
            }
        }
        pid > 0
    }

    /// One tool call. Holds the worker for its whole duration: Hands runs one request
    /// at a time anyway, and a pipe has no request multiplexing.
    pub fn call(
        &self,
        tool: &str,
        arguments: Value,
        deadline: Duration,
    ) -> Result<Answer, Failure> {
        let mut slot = self.worker.lock().unwrap_or_else(|p| p.into_inner());
        if slot.is_none() {
            *slot = Some(self.spawn()?);
        }
        let worker = slot.as_mut().expect("a worker");
        let request_id = worker.next_id;
        worker.next_id += 1;
        let request = json!({
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "generation": worker.generation,
            "operation": "call",
            "name": tool,
            "arguments": arguments,
        });
        match exchange(worker, &request, deadline) {
            Ok(response) => {
                let answer = check_identity(&response, request_id, &worker.generation);
                match answer {
                    Ok(answer) => Ok(answer),
                    Err(failed) => {
                        self.retire(&mut slot);
                        Err(failed)
                    }
                }
            }
            Err(failed) => {
                self.retire(&mut slot);
                Err(failed)
            }
        }
    }

    /// Ask the worker to end (Hands is quitting). Best effort.
    pub fn shutdown(&self) {
        let mut slot = self.worker.lock().unwrap_or_else(|p| p.into_inner());
        if let Some(worker) = slot.as_mut() {
            let request = json!({
                "protocol_version": PROTOCOL_VERSION,
                "request_id": worker.next_id,
                "generation": worker.generation,
                "operation": "shutdown",
            });
            let _ = exchange(worker, &request, Duration::from_secs(2));
        }
        self.retire(&mut slot);
    }

    fn retire(&self, slot: &mut Option<Worker>) {
        self.pid.store(0, Ordering::SeqCst);
        if let Some(worker) = slot.take() {
            worker.reap();
        }
    }

    fn spawn(&self) -> Result<Worker, Failure> {
        if !self.present() {
            return Err(failure(
                "engine_missing",
                "Cua Driver is not installed with this Arslan Hands",
                Completion::NotStarted,
            ));
        }
        if let Some(pinned) = &self.config.pinned {
            pinned
                .check()
                .map_err(|e| failure("helper_failed", e, Completion::NotStarted))?;
        }
        crate::paths::ensure_private_dir(&self.config.home)
            .map_err(|e| failure("helper_failed", e, Completion::NotStarted))?;
        let generation =
            new_generation().map_err(|e| failure("helper_failed", e, Completion::NotStarted))?;
        let log = self.open_log();
        let mut command = Command::new(&self.config.binary);
        command
            .arg("__private-worker")
            .arg("--generation")
            .arg(&generation)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(match log {
                Some(file) => Stdio::from(file),
                None => Stdio::null(),
            })
            .env_clear();
        for (name, value) in environment(&self.config.home) {
            command.env(name, value);
        }
        let mut child = command.spawn().map_err(|e| {
            failure(
                "helper_failed",
                format!("cannot start Cua Driver: {e}"),
                Completion::NotStarted,
            )
        })?;
        let stdin = child.stdin.take();
        let stdout = child.stdout.take();
        let (Some(stdin), Some(stdout)) = (stdin, stdout) else {
            let _ = child.kill();
            let _ = child.wait();
            return Err(failure(
                "helper_failed",
                "Cua Driver has no pipes",
                Completion::NotStarted,
            ));
        };
        self.pid.store(child.id() as i32, Ordering::SeqCst);
        let mut worker = Worker {
            child,
            stdin,
            stdout: Some(BufReader::new(stdout)),
            generation,
            next_id: 1,
        };
        let request = json!({
            "protocol_version": PROTOCOL_VERSION,
            "request_id": 0,
            "generation": worker.generation,
            "operation": "initialize",
            "arguments": initialization(&self.config.host_bundle_id),
        });
        let ready = exchange(&mut worker, &request, STARTUP)
            .and_then(|response| check_identity(&response, 0, &worker.generation));
        let proven = ready
            .as_ref()
            .is_ok_and(|answer| ready_proof(answer, &self.config.host_bundle_id));
        match ready {
            Ok(_) if proven => Ok(worker),
            Ok(answer) => {
                self.pid.store(0, Ordering::SeqCst);
                worker.reap();
                Err(failure(
                    "bad_output",
                    format!(
                        "Cua Driver did not prove it is this host's worker: {}",
                        answer.error.unwrap_or_default()
                    ),
                    Completion::NotStarted,
                ))
            }
            Err(failed) => {
                self.pid.store(0, Ordering::SeqCst);
                worker.reap();
                Err(Failure {
                    // Nothing was asked of it yet: whatever went wrong, no action ran.
                    completion: Completion::NotStarted,
                    ..failed
                })
            }
        }
    }

    fn open_log(&self) -> Option<std::fs::File> {
        if std::fs::metadata(&self.config.log).is_ok_and(|m| m.len() > LOG_LIMIT) {
            let _ = std::fs::remove_file(&self.config.log);
        }
        OpenOptions::new()
            .create(true)
            .append(true)
            .mode(0o600)
            .open(&self.config.log)
            .ok()
    }
}

/// The worker's whole environment. Nothing from Hands' own environment reaches it.
pub fn environment(home: &std::path::Path) -> Vec<(&'static str, String)> {
    vec![
        ("HOME", home.display().to_string()),
        ("PATH", "/usr/bin:/bin:/usr/sbin:/sbin".into()),
        ("LANG", "en_US.UTF-8".into()),
        // Off whatever else says on: DO_NOT_TRACK wins over every other switch in
        // Cua's telemetry, and our fork compiles the sender out besides.
        ("DO_NOT_TRACK", "1".into()),
        ("CUA_DRIVER_RS_TELEMETRY_ENABLED", "false".into()),
        (
            "CUA_DRIVER_WINDOW_CHANGE_TIMEOUT_MS",
            WINDOW_CHANGE_TIMEOUT_MS.into(),
        ),
    ]
}

/// The runtime Hands asks for: the standard permission mode only (Arslan asks the
/// user itself; with browser tools refused, nothing is left for Cua to authorize),
/// never unrestricted.
pub fn initialization(host_bundle_id: &str) -> Value {
    json!({
        "configured_driver": {
            "claude_code_compatibility": false,
            "authorization": {
                "allowed_modes": ["standard"],
                "compatibility_mode": "standard",
                "compatibility_capability_manifest_path": null,
                "compatibility_bounded_manifest_path": null,
                "unrestricted_acknowledged": false,
                "max_session_ttl_seconds": 3600,
                "max_idle_ttl_seconds": 900,
            }
        },
        "host_bundle_id": host_bundle_id,
    })
}

/// The worker answers `initialize` with `{ready: true, pid, host_bundle_id}`: a
/// different process than Hands, echoing Hands' bundle id.
fn ready_proof(answer: &Answer, host_bundle_id: &str) -> bool {
    let result = &answer.result;
    answer.ok
        && result.get("ready").and_then(Value::as_bool) == Some(true)
        && result
            .get("pid")
            .and_then(Value::as_u64)
            .is_some_and(|pid| pid != u64::from(std::process::id()))
        && result.get("host_bundle_id").and_then(Value::as_str) == Some(host_bundle_id)
}

fn new_generation() -> Result<String, String> {
    let mut bytes = [0u8; 16];
    if unsafe { libc::getentropy(bytes.as_mut_ptr().cast(), bytes.len()) } != 0 {
        return Err("no entropy".into());
    }
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

/// Write one request line and read one response line within `deadline`.
fn exchange(worker: &mut Worker, request: &Value, deadline: Duration) -> Result<Value, Failure> {
    let line = format!("{request}\n");
    if let Err(e) = worker
        .stdin
        .write_all(line.as_bytes())
        .and_then(|()| worker.stdin.flush())
    {
        // A worker that died before reading the line never ran it; one that broke the
        // pipe halfway may have read a whole request. Only the first is provable.
        let completion = if worker.child.try_wait().ok().flatten().is_some() {
            Completion::NotStarted
        } else {
            Completion::Unknown
        };
        return Err(failure(
            "engine_died",
            format!("Cua Driver did not take the request: {e}"),
            completion,
        ));
    }
    // A pipe has no read timeout: one helper thread owns this read and hands the
    // reader back.
    let mut stdout = worker.stdout.take().ok_or_else(|| {
        failure(
            "engine_died",
            "Cua Driver's reply channel is gone",
            Completion::Unknown,
        )
    })?;
    let (tx, rx) = mpsc::sync_channel(1);
    thread::spawn(move || {
        let line = read_line_limited(&mut stdout, MAX_LINE);
        let _ = tx.send((stdout, line));
    });
    let (stdout, line) = match rx.recv_timeout(deadline) {
        Ok(read) => read,
        Err(_) => {
            return Err(failure(
                "TIMEOUT",
                "Cua Driver did not answer in time",
                Completion::Unknown,
            ))
        }
    };
    worker.stdout = Some(stdout);
    match line {
        Ok(Some(text)) => serde_json::from_str(&text).map_err(|_| {
            failure(
                "bad_output",
                "Cua Driver printed something that is not a reply",
                Completion::Unknown,
            )
        }),
        Ok(None) => Err(failure(
            "engine_died",
            "Cua Driver ended before it answered",
            Completion::Unknown,
        )),
        Err(e) => Err(failure("bad_output", e, Completion::Unknown)),
    }
}

fn check_identity(response: &Value, request_id: u64, generation: &str) -> Result<Answer, Failure> {
    let same = response.get("protocol_version").and_then(Value::as_u64) == Some(PROTOCOL_VERSION)
        && response.get("request_id").and_then(Value::as_u64) == Some(request_id)
        && response.get("generation").and_then(Value::as_str) == Some(generation);
    if !same {
        return Err(failure(
            "bad_output",
            "Cua Driver answered another request",
            Completion::Unknown,
        ));
    }
    let completion = response
        .get("completion")
        .and_then(Value::as_str)
        .and_then(Completion::parse)
        .unwrap_or(Completion::Unknown);
    let ok = response.get("ok").and_then(Value::as_bool) == Some(true);
    let text = |key: &str| response.get(key).and_then(Value::as_str).map(str::to_owned);
    match completion {
        Completion::Completed => Ok(Answer {
            ok,
            result: response.get("result").cloned().unwrap_or(Value::Null),
            error_code: text("error_code"),
            error: text("error"),
        }),
        Completion::NotStarted if !ok => Err(Failure {
            refusal: refuse(
                "engine_refused",
                text("error").unwrap_or_else(|| "Cua Driver did not start it".into()),
            ),
            completion,
        }),
        _ => Err(Failure {
            refusal: refuse(
                "engine_unknown",
                text("error").unwrap_or_else(|| "Cua Driver cannot say whether it ran".into()),
            ),
            // `ok` with anything but completed is a contract breach: treat as unknown.
            completion: Completion::Unknown,
        }),
    }
}

/// One `\n`-terminated line, refusing anything longer than `max` bytes. `Ok(None)` at
/// end of stream.
fn read_line_limited(reader: &mut impl BufRead, max: usize) -> Result<Option<String>, String> {
    let mut line: Vec<u8> = Vec::new();
    loop {
        let available = reader
            .fill_buf()
            .map_err(|e| format!("cannot read Cua Driver's reply: {e}"))?;
        if available.is_empty() {
            return Ok(if line.is_empty() {
                None
            } else {
                Some(String::from_utf8_lossy(&line).into_owned())
            });
        }
        let (take, done) = match available.iter().position(|b| *b == b'\n') {
            Some(i) => (i + 1, true),
            None => (available.len(), false),
        };
        if line.len() + take > max {
            return Err("Cua Driver's reply is too long".into());
        }
        line.extend_from_slice(&available[..take]);
        reader.consume(take);
        if done {
            line.pop();
            return Ok(Some(String::from_utf8_lossy(&line).into_owned()));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn long_lines_are_refused_and_lines_are_split_on_newlines() {
        let mut short = std::io::Cursor::new(b"{\"a\":1}\n{\"b\":2}\n".to_vec());
        assert_eq!(
            read_line_limited(&mut short, 100).unwrap().as_deref(),
            Some("{\"a\":1}")
        );
        assert_eq!(
            read_line_limited(&mut short, 100).unwrap().as_deref(),
            Some("{\"b\":2}")
        );
        assert_eq!(read_line_limited(&mut short, 100).unwrap(), None);
        let mut long = std::io::Cursor::new(vec![b'x'; 300]);
        assert!(read_line_limited(&mut long, 100).is_err());
    }

    #[test]
    fn only_completed_answers_are_answers() {
        let base = |completion: &str, ok: bool| {
            json!({"protocol_version": 1, "request_id": 3, "generation": "g", "ok": ok,
                   "completion": completion, "result": {"x": 1}})
        };
        assert!(check_identity(&base("completed", true), 3, "g").unwrap().ok);
        assert!(
            !check_identity(&base("completed", false), 3, "g")
                .unwrap()
                .ok
        );
        let not_started = check_identity(&base("not_started", false), 3, "g").unwrap_err();
        assert_eq!(not_started.completion, Completion::NotStarted);
        // Success that is not "completed" breaks the contract: never trusted as done.
        let odd = check_identity(&base("not_started", true), 3, "g").unwrap_err();
        assert_eq!(odd.completion, Completion::Unknown);
        let unknown = check_identity(&base("unknown", false), 3, "g").unwrap_err();
        assert_eq!(unknown.completion, Completion::Unknown);
        // Another request's answer, or another generation's, is not this one's.
        assert!(check_identity(&base("completed", true), 4, "g").is_err());
        assert!(check_identity(&base("completed", true), 3, "h").is_err());
    }

    #[test]
    fn the_environment_is_only_what_hands_sets() {
        let env = environment(std::path::Path::new("/tmp/h"));
        let names: Vec<&str> = env.iter().map(|(n, _)| *n).collect();
        assert_eq!(
            names,
            [
                "HOME",
                "PATH",
                "LANG",
                "DO_NOT_TRACK",
                "CUA_DRIVER_RS_TELEMETRY_ENABLED",
                "CUA_DRIVER_WINDOW_CHANGE_TIMEOUT_MS"
            ]
        );
        assert!(env.contains(&("HOME", "/tmp/h".into())));
        assert!(env.contains(&("DO_NOT_TRACK", "1".into())));
    }

    #[test]
    fn the_runtime_is_standard_mode_only() {
        let init = initialization("com.arslan.desktop.hands");
        assert_eq!(
            init["configured_driver"]["authorization"]["allowed_modes"],
            json!(["standard"])
        );
        assert_eq!(
            init["configured_driver"]["authorization"]["unrestricted_acknowledged"],
            false
        );
        assert_eq!(init["host_bundle_id"], "com.arslan.desktop.hands");
    }
}

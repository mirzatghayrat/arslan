//! Trusted native maintenance transport. No web IPC, implicit approval or retry.
//! A refusal/transport error can follow a partial directory move: retain the
//! journal and reconcile state, never infer that an action had no effect.
use crate::recovery_secret::{DurableSecret, ExistingSecret};
use serde::Deserialize;
use std::io::{Read, Write};
use std::os::fd::AsRawFd;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

pub(crate) enum Request<'a> {
    Rewrap {
        candidate: &'a str,
        source: &'a ExistingSecret,
        target: &'a DurableSecret,
    },
    Prepare {
        archive: &'a Path,
        candidate: &'a str,
    },
    Switch {
        candidate: &'a str,
        secret: &'a ExistingSecret,
    },
    Rollback,
    Inspect,
    RollbackBound {
        operation_id: &'a str,
    },
    Finalize {
        operation_id: &'a str,
        secret: &'a ExistingSecret,
    },
}

#[derive(Debug, PartialEq)]
pub(crate) enum Outcome {
    Rewrapped { credentials: u64 },
    Prepared { files: u64 },
    TrialPending(String),
    RolledBack(bool),
    PendingOperation(Option<String>),
    Finalized { already_finalized: bool },
}

#[derive(Debug, PartialEq)]
pub(crate) enum ControlError {
    InvalidRequest,
    Unavailable,
    Refused,
    OutcomeUnknown,
}

pub(super) fn valid_id(value: &str) -> bool {
    value.len() == 36
        && value.bytes().enumerate().all(|(i, byte)| {
            if [8, 13, 18, 23].contains(&i) {
                byte == b'-'
            } else {
                byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)
            }
        })
}

fn encode(request: &Request<'_>) -> Result<Vec<u8>, ControlError> {
    fn valid_candidate(candidate: &str) -> bool {
        !candidate.is_empty()
            && ![".", ".."].contains(&candidate)
            && candidate.len() <= 255
            && !candidate.contains(['/', '\\', '\0'])
    }
    let value = match request {
        Request::Rewrap { candidate, source, target } => {
            if !valid_candidate(candidate) || target.recheck().is_err() {
                return Err(ControlError::InvalidRequest);
            }
            serde_json::json!({"action":"rewrap", "candidate":candidate,
                "source_secret":source.expose(), "target_secret":target.secret().expose()})
        }
        Request::Prepare { archive, candidate } => {
            let path = archive.to_str().ok_or(ControlError::InvalidRequest)?;
            if !archive.is_absolute()
                || path.len() > 4096
                || path.contains('\0')
                || archive
                    .components()
                    .any(|part| part == std::path::Component::ParentDir)
                || !valid_candidate(candidate)
            {
                return Err(ControlError::InvalidRequest);
            }
            serde_json::json!({"action":"prepare", "archive":path, "candidate":candidate})
        }
        Request::Switch { candidate, secret } => {
            if !valid_candidate(candidate) {
                return Err(ControlError::InvalidRequest);
            }
            serde_json::json!({"action":"switch", "candidate":candidate, "secret":secret.expose()})
        }
        Request::Rollback => serde_json::json!({"action":"rollback"}),
        Request::Inspect => serde_json::json!({"action":"inspect"}),
        Request::RollbackBound { operation_id } => {
            if !valid_id(operation_id) {
                return Err(ControlError::InvalidRequest);
            }
            serde_json::json!({"action":"rollback", "operation_id":operation_id})
        }
        Request::Finalize {
            operation_id,
            secret,
        } => {
            if !valid_id(operation_id) {
                return Err(ControlError::InvalidRequest);
            }
            serde_json::json!({"action":"finalize", "operation_id":operation_id, "secret":secret.expose()})
        }
    };
    let mut bytes = serde_json::to_vec(&value).map_err(|_| ControlError::InvalidRequest)?;
    if bytes.len() > 16 * 1024 {
        return Err(ControlError::InvalidRequest);
    }
    bytes.push(b'\n');
    Ok(bytes)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Success<T> {
    ok: bool,
    result: T,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Refusal {
    ok: bool,
    code: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Switched {
    status: String,
    operation_id: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Prepared {
    prepared: bool,
    candidate: String,
    files: u64,
    secret_included: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Rewrapped {
    rewrapped: bool,
    candidate: String,
    credentials: u64,
    secret_persisted: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RolledBack {
    rolled_back: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PendingOperation {
    operation_id: serde_json::Value,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Finalized {
    finalized: bool,
    already_finalized: bool,
    original_retained: bool,
}

fn success<T: serde::de::DeserializeOwned>(bytes: &[u8]) -> Result<T, ControlError> {
    let reply: Success<T> =
        serde_json::from_slice(bytes).map_err(|_| ControlError::OutcomeUnknown)?;
    if !reply.ok {
        return Err(ControlError::OutcomeUnknown);
    }
    Ok(reply.result)
}

fn decode(bytes: &[u8], exit: Option<i32>, request: &Request<'_>) -> Result<Outcome, ControlError> {
    if exit == Some(1) {
        let reply: Refusal =
            serde_json::from_slice(bytes).map_err(|_| ControlError::OutcomeUnknown)?;
        return if !reply.ok && reply.code == "activation_control_refused" {
            Err(ControlError::Refused)
        } else {
            Err(ControlError::OutcomeUnknown)
        };
    }
    if exit != Some(0) {
        return Err(ControlError::OutcomeUnknown);
    }
    match request {
        Request::Rewrap { candidate, target, .. } => {
            let r: Rewrapped = success(bytes)?;
            if !r.rewrapped || r.candidate != *candidate || r.credentials > 10_000
                || r.secret_persisted || target.recheck().is_err()
            {
                return Err(ControlError::OutcomeUnknown);
            }
            Ok(Outcome::Rewrapped { credentials: r.credentials })
        }
        Request::Prepare { candidate, .. } => {
            let r: Prepared = success(bytes)?;
            if !r.prepared
                || r.candidate != *candidate
                || r.secret_included
                || r.files == 0
                || r.files > 10_000
            {
                return Err(ControlError::OutcomeUnknown);
            }
            Ok(Outcome::Prepared { files: r.files })
        }
        Request::Switch { .. } => {
            let r: Switched = success(bytes)?;
            if r.status != "trial_pending" || !valid_id(&r.operation_id) {
                return Err(ControlError::OutcomeUnknown);
            }
            Ok(Outcome::TrialPending(r.operation_id))
        }
        Request::Rollback | Request::RollbackBound { .. } => {
            let r: RolledBack = success(bytes)?;
            Ok(Outcome::RolledBack(r.rolled_back))
        }
        Request::Inspect => {
            let r: PendingOperation = success(bytes)?;
            match r.operation_id {
                serde_json::Value::Null => Ok(Outcome::PendingOperation(None)),
                serde_json::Value::String(id) if valid_id(&id) => {
                    Ok(Outcome::PendingOperation(Some(id)))
                }
                _ => Err(ControlError::OutcomeUnknown),
            }
        }
        Request::Finalize { .. } => {
            let r: Finalized = success(bytes)?;
            if !r.finalized || !r.original_retained {
                return Err(ControlError::OutcomeUnknown);
            }
            Ok(Outcome::Finalized {
                already_finalized: r.already_finalized,
            })
        }
    }
}

pub(super) struct OwnedChild(pub(super) Child);
impl Drop for OwnedChild {
    fn drop(&mut self) {
        if !matches!(self.0.try_wait(), Ok(Some(_))) {
            let _ = self.0.kill();
        }
        let _ = self.0.wait();
    }
}

pub(super) fn nonblocking(pipe: &impl AsRawFd) -> Result<(), ControlError> {
    // SAFETY: these borrowed handles remain open during both fcntl calls.
    let flags = unsafe { libc::fcntl(pipe.as_raw_fd(), libc::F_GETFL) };
    if flags < 0
        || unsafe { libc::fcntl(pipe.as_raw_fd(), libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0
    {
        return Err(ControlError::OutcomeUnknown);
    }
    Ok(())
}

pub(crate) fn run(executable: &Path, request: &Request<'_>) -> Result<Outcome, ControlError> {
    if !executable.is_absolute() {
        return Err(ControlError::InvalidRequest);
    }
    let mut command = Command::new(executable);
    command.arg("--activation-control");
    execute(command, request, Duration::from_secs(30))
}

fn execute(
    mut command: Command,
    request: &Request<'_>,
    timeout: Duration,
) -> Result<Outcome, ControlError> {
    let payload = encode(request)?;
    let mut child = OwnedChild(
        command
            .env_remove("ARSLAN_SECRET_KEY")
            .env_remove("ARSLAN_SECRET_KEY_FILE")
            .env_remove("ARSLAN_API_TOKEN")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| ControlError::Unavailable)?,
    );
    let mut input = child.0.stdin.take();
    let mut output = child.0.stdout.take().ok_or(ControlError::OutcomeUnknown)?;
    nonblocking(input.as_ref().ok_or(ControlError::OutcomeUnknown)?)?;
    nonblocking(&output)?;
    let deadline = Instant::now() + timeout;
    let mut written = 0;
    let mut bytes = Vec::new();
    let mut eof = false;
    loop {
        if Instant::now() >= deadline {
            return Err(ControlError::OutcomeUnknown);
        }
        if let Some(pipe) = input.as_mut() {
            match pipe.write(&payload[written..]) {
                Ok(0) => return Err(ControlError::OutcomeUnknown),
                Ok(n) => written += n,
                Err(e)
                    if [
                        std::io::ErrorKind::WouldBlock,
                        std::io::ErrorKind::Interrupted,
                    ]
                    .contains(&e.kind()) => {}
                Err(_) => return Err(ControlError::OutcomeUnknown),
            }
            if written == payload.len() {
                input.take();
            }
        }
        if !eof {
            let mut buffer = [0; 512];
            match output.read(&mut buffer) {
                Ok(0) => eof = true,
                Ok(n) => {
                    bytes.extend_from_slice(&buffer[..n]);
                    if bytes.len() > 4096 {
                        return Err(ControlError::OutcomeUnknown);
                    }
                }
                Err(e)
                    if [
                        std::io::ErrorKind::WouldBlock,
                        std::io::ErrorKind::Interrupted,
                    ]
                    .contains(&e.kind()) => {}
                Err(_) => return Err(ControlError::OutcomeUnknown),
            }
        }
        if let Some(status) = child
            .0
            .try_wait()
            .map_err(|_| ControlError::OutcomeUnknown)?
        {
            if eof && input.is_none() {
                return decode(&bytes, status.code(), request);
            }
        }
        std::thread::sleep(Duration::from_millis(5));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const ID: &str = "01234567-89ab-cdef-0123-456789abcdef";
    fn secret() -> ExistingSecret {
        crate::recovery_secret::prepare(Some("synthetic-only"), Path::new("unused"))
            .unwrap_or_else(|_| panic!("invalid fixture"))
    }

    #[test]
    fn requests_are_exact_bounded_and_do_not_accept_paths() {
        let key = secret();
        for candidate in ["", ".", "..", "../elsewhere", "/absolute", "a\\b"] {
            assert_eq!(
                encode(&Request::Switch {
                    candidate,
                    secret: &key
                })
                .err(),
                Some(ControlError::InvalidRequest)
            );
        }
        let message = encode(&Request::Finalize {
            operation_id: ID,
            secret: &key,
        })
        .unwrap();
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&message).unwrap(),
            serde_json::json!({"action":"finalize", "operation_id":ID, "secret":"synthetic-only"})
        );
        assert!(!valid_id("01234567-89AB-cdef-0123-456789abcdef"));
    }

    #[test]
    fn prepare_requires_selected_absolute_archive_and_matching_new_candidate() {
        let request = Request::Prepare {
            archive: Path::new("/tmp/selected.zip"),
            candidate: "restored",
        };
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&encode(&request).unwrap()).unwrap(),
            serde_json::json!({"action":"prepare", "archive":"/tmp/selected.zip", "candidate":"restored"})
        );
        for path in ["relative.zip", "/tmp/../archive", "/tmp/a\0b"] {
            assert_eq!(
                encode(&Request::Prepare {
                    archive: Path::new(path),
                    candidate: "restored"
                })
                .err(),
                Some(ControlError::InvalidRequest)
            );
        }
        assert_eq!(
            encode(&Request::Prepare {
                archive: Path::new("/tmp/a"),
                candidate: "../elsewhere"
            })
            .err(),
            Some(ControlError::InvalidRequest)
        );
        let value = serde_json::json!({"ok":true,"result":{"prepared":true,"candidate":"restored","files":1,"secret_included":false}});
        assert_eq!(
            decode(&serde_json::to_vec(&value).unwrap(), Some(0), &request),
            Ok(Outcome::Prepared { files: 1 })
        );
        for (key, bad) in [
            ("candidate", serde_json::json!("other")),
            ("prepared", serde_json::json!(false)),
            ("files", serde_json::json!(0)),
            ("files", serde_json::json!(10001)),
            ("secret_included", serde_json::json!(true)),
            ("extra", serde_json::json!(null)),
        ] {
            let mut invalid = value.clone();
            invalid["result"][key] = bad;
            assert_eq!(
                decode(&serde_json::to_vec(&invalid).unwrap(), Some(0), &request),
                Err(ControlError::OutcomeUnknown)
            );
        }
    }

    #[test]
    fn replies_require_matching_shapes_status_and_retention() {
        let request = Request::Rollback;
        assert_eq!(
            decode(
                br#"{"ok":true,"result":{"rolled_back":true}}"#,
                Some(0),
                &request
            ),
            Ok(Outcome::RolledBack(true))
        );
        for bytes in [
            br#"{"ok":true,"result":{"rolled_back":true,"extra":1}}"#.as_slice(),
            br#"{"ok":true,"result":{"rolled_back":true,"status":null}}"#,
            br#"{"ok":true,"result":{"rolled_back":true},"code":null}"#,
            br#"{"ok":true,"ok":false,"result":{"rolled_back":true}}"#,
            br#"{"ok":true,"result":{"finalized":true}}"#,
            br#"{"ok":true,"result":{"rolled_back":true}} trailing"#,
        ] {
            assert_eq!(
                decode(bytes, Some(0), &request),
                Err(ControlError::OutcomeUnknown)
            );
        }
        assert_eq!(
            decode(
                br#"{"ok":false,"code":"activation_control_refused"}"#,
                Some(1),
                &request
            ),
            Err(ControlError::Refused)
        );
        assert_eq!(
            decode(
                br#"{"ok":true,"result":{"rolled_back":true}}"#,
                Some(1),
                &request
            ),
            Err(ControlError::OutcomeUnknown)
        );
        let key = secret();
        let finalize = Request::Finalize {
            operation_id: ID,
            secret: &key,
        };
        assert_eq!(decode(br#"{"ok":true,"result":{"finalized":true,"already_finalized":false,"original_retained":false}}"#,
                          Some(0), &finalize), Err(ControlError::OutcomeUnknown));
    }

    #[test]
    fn inspection_and_bound_rollback_require_canonical_operation_ids() {
        assert_eq!(
            decode(
                br#"{"ok":true,"result":{"operation_id":null}}"#,
                Some(0),
                &Request::Inspect
            ),
            Ok(Outcome::PendingOperation(None))
        );
        let reply = serde_json::json!({"ok":true,"result":{"operation_id":ID}});
        assert_eq!(
            decode(
                &serde_json::to_vec(&reply).unwrap(),
                Some(0),
                &Request::Inspect
            ),
            Ok(Outcome::PendingOperation(Some(ID.into())))
        );
        for bytes in [
            br#"{"ok":true,"result":{}}"#.as_slice(),
            br#"{"ok":true,"result":{"operation_id":"invalid"}}"#,
            br#"{"ok":true,"result":{"operation_id":null,"extra":1}}"#,
        ] {
            assert_eq!(
                decode(bytes, Some(0), &Request::Inspect),
                Err(ControlError::OutcomeUnknown)
            );
        }
        assert_eq!(
            encode(&Request::RollbackBound {
                operation_id: "invalid"
            })
            .err(),
            Some(ControlError::InvalidRequest)
        );
        let encoded = encode(&Request::RollbackBound { operation_id: ID }).unwrap();
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&encoded).unwrap(),
            serde_json::json!({"action":"rollback","operation_id":ID})
        );
    }

    fn shell(script: &str) -> Command {
        let mut command = Command::new("/bin/sh");
        command.args(["-c", script]);
        command
    }

    #[test]
    fn rewrap_requires_durable_source_bounded_pipe_and_exact_candidate_reply() {
        use std::os::unix::fs::PermissionsExt;
        let home = std::env::temp_dir().join(format!("arslan-rewrap-control-{}-{}",
            std::process::id(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
        let profile = home.join("profile");
        let file = home.join(".arslan/secret_key");
        std::fs::create_dir_all(&profile).unwrap();
        std::fs::create_dir_all(file.parent().unwrap()).unwrap();
        std::fs::write(&file, b"synthetic-target").unwrap();
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600)).unwrap();
        let target = DurableSecret::load(&home, &profile, "dev", None, None).unwrap_or_else(|_| panic!());
        let source = secret();
        let request = Request::Rewrap { candidate: "restored", source: &source, target: &target };
        let encoded = encode(&request).unwrap();
        assert_eq!(serde_json::from_slice::<serde_json::Value>(&encoded).unwrap(),
            serde_json::json!({"action":"rewrap","candidate":"restored",
                "source_secret":"synthetic-only","target_secret":"synthetic-target"}));
        let value = serde_json::json!({"ok":true,"result":{"rewrapped":true,"candidate":"restored",
            "credentials":2,"secret_persisted":false}});
        let reply = serde_json::to_vec(&value).unwrap();
        assert_eq!(decode(&reply, Some(0), &request), Ok(Outcome::Rewrapped { credentials: 2 }));
        assert_eq!(execute(shell("IFS= read -r payload; printf '%s' '{\"ok\":true,\"result\":{\"rewrapped\":true,\"candidate\":\"restored\",\"credentials\":2,\"secret_persisted\":false}}'"),
            &request, Duration::from_secs(2)), Ok(Outcome::Rewrapped { credentials: 2 }));
        for (field, bad) in [
            ("candidate", serde_json::json!("other")), ("credentials", serde_json::json!(10001)),
            ("credentials", serde_json::json!(-1)), ("secret_persisted", serde_json::json!(true)),
            ("rewrapped", serde_json::json!(false)), ("extra", serde_json::json!(null)),
        ] {
            let mut wrong = value.clone();
            wrong["result"][field] = bad;
            assert_eq!(decode(&serde_json::to_vec(&wrong).unwrap(), Some(0), &request), Err(ControlError::OutcomeUnknown));
        }
        assert_eq!(encode(&Request::Rewrap { candidate: "../active", source: &source, target: &target }).err(),
            Some(ControlError::InvalidRequest));
        std::fs::write(&file, b"changed-target").unwrap();
        assert_eq!(encode(&request).err(), Some(ControlError::InvalidRequest));
        assert_eq!(decode(&reply, Some(0), &request), Err(ControlError::OutcomeUnknown));
        let huge = "x".repeat(8192);
        std::fs::write(&file, huge.as_bytes()).unwrap();
        let target = DurableSecret::load(&home, &profile, "dev", None, None).unwrap_or_else(|_| panic!());
        let source = crate::recovery_secret::prepare(Some(&huge), Path::new("unused")).unwrap_or_else(|_| panic!());
        assert_eq!(encode(&Request::Rewrap { candidate: "restored", source: &source, target: &target }).err(),
            Some(ControlError::InvalidRequest));
        std::fs::remove_dir_all(home).unwrap();
    }

    #[test]
    fn real_process_requires_reply_and_successful_exit() {
        let result = execute(shell("IFS= read -r payload; printf '%s' '{\"ok\":true,\"result\":{\"rolled_back\":true}}'"),
                             &Request::Rollback, Duration::from_secs(2));
        assert_eq!(result, Ok(Outcome::RolledBack(true)));
        assert_eq!(
            execute(
                shell("IFS= read -r payload; exit 7"),
                &Request::Rollback,
                Duration::from_secs(2)
            ),
            Err(ControlError::OutcomeUnknown)
        );
    }

    #[test]
    fn stalled_or_oversized_output_is_bounded() {
        for script in [
            "while :; do :; done",
            "IFS= read -r payload; while :; do printf 'xxxxxxxxxxxxxxxx'; done",
        ] {
            let start = Instant::now();
            assert_eq!(
                execute(
                    shell(script),
                    &Request::Rollback,
                    Duration::from_millis(100)
                ),
                Err(ControlError::OutcomeUnknown)
            );
            assert!(start.elapsed() < Duration::from_secs(2));
        }
    }

    #[test]
    fn secret_environment_is_not_inherited_and_timeout_reaps_owned_child() {
        let mut command = shell("IFS= read -r payload; test -z \"${ARSLAN_SECRET_KEY+x}${ARSLAN_SECRET_KEY_FILE+x}${ARSLAN_API_TOKEN+x}\" || exit 9; printf '%s' '{\"ok\":true,\"result\":{\"rolled_back\":false}}'");
        for key in [
            "ARSLAN_SECRET_KEY",
            "ARSLAN_SECRET_KEY_FILE",
            "ARSLAN_API_TOKEN",
        ] {
            command.env(key, "synthetic-must-not-inherit");
        }
        assert_eq!(
            execute(command, &Request::Rollback, Duration::from_secs(2)),
            Ok(Outcome::RolledBack(false))
        );
        let path = std::env::temp_dir().join(format!(
            "arslan-control-pid-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let mut command = shell("printf '%s' \"$$\" > \"$PIDFILE\"; while :; do :; done");
        command.env("PIDFILE", &path);
        assert_eq!(
            execute(command, &Request::Rollback, Duration::from_millis(250)),
            Err(ControlError::OutcomeUnknown)
        );
        let pid: libc::pid_t = std::fs::read_to_string(&path).unwrap().parse().unwrap();
        std::fs::remove_file(path).unwrap();
        // SAFETY: WNOHANG queries only the exact synthetic child we just owned.
        assert_eq!(
            unsafe { libc::waitpid(pid, std::ptr::null_mut(), libc::WNOHANG) },
            -1
        );
        assert_eq!(
            std::io::Error::last_os_error().raw_os_error(),
            Some(libc::ECHILD)
        );
    }

    #[test]
    #[ignore = "requires frozen_activation_trial_smoke disposable fixture and temporary frozen binary"]
    fn packaged_control_fixture() {
        let temp = Path::new("/tmp").canonicalize().unwrap();
        let home = std::path::PathBuf::from(std::env::var_os("HOME").unwrap())
            .canonicalize()
            .unwrap();
        assert_eq!(home.parent(), Some(temp.as_path()));
        assert!(home
            .file_name()
            .unwrap()
            .to_string_lossy()
            .starts_with("arslan-frozen-trial-"));
        let binary =
            std::path::PathBuf::from(std::env::var_os("ARSLAN_CONTROL_TEST_BINARY").unwrap())
                .canonicalize()
                .unwrap();
        assert!(binary.starts_with(&temp));
        assert_eq!(binary.file_name().unwrap(), "arslan-server");
        assert!(binary.components().any(|part| {
            let name = part.as_os_str().to_string_lossy();
            name.starts_with("arslan-candidate-build.")
                || name.starts_with("arslan-native-candidate.")
        }));
        let synthetic = if std::env::var_os("ARSLAN_CONTROL_TEST_WRONG_KEY").is_some() {
            "wrong-key"
        } else if std::env::var_os("ARSLAN_CONTROL_TEST_TARGET_KEY").is_some() {
            let proof = DurableSecret::load(&home, &home.join("Library/Application Support/Arslan"),
                "dev", None, None).unwrap_or_else(|_| panic!("invalid durable fixture"));
            assert_eq!(proof.secret().expose(), "frozen-smoke-target-only");
            "frozen-smoke-target-only"
        } else {
            "frozen-smoke-synthetic-only"
        };
        let key = crate::recovery_secret::prepare(Some(synthetic), Path::new("unused"))
            .unwrap_or_else(|_| panic!("invalid fixture"));
        let operation = std::env::var("ARSLAN_CONTROL_TEST_OPERATION").unwrap_or_default();
        let action = std::env::var("ARSLAN_CONTROL_TEST_ACTION").unwrap();
        if action == "shutdown" {
            crate::recovery_shutdown::packaged_fixture(&binary);
            println!("NATIVE_CONTROL_RESULT={{\"ok\":true,\"result\":{{\"stopped\":true}}}}");
            return;
        }
        if action == "trial" {
            crate::recovery_trial::run(&binary, &operation, &key)
                .unwrap_or_else(|error| panic!("native trial failed: {error:?}"));
            println!(
                "NATIVE_CONTROL_RESULT={{\"ok\":true,\"result\":{{\"trial_completed\":true}}}}"
            );
            return;
        }
        let archive = home.join("backup.zip");
        let durable = if action == "rewrap" {
            let proof = DurableSecret::load(&home, &home.join("Library/Application Support/Arslan"),
                "dev", None, None).unwrap_or_else(|_| panic!("invalid durable fixture"));
            assert_eq!(proof.secret().expose(), "frozen-smoke-target-only");
            Some(proof)
        } else { None };
        let request = match action.as_str() {
            "rewrap" => Request::Rewrap { candidate: "restored", source: &key, target: durable.as_ref().unwrap() },
            "prepare" => Request::Prepare {
                archive: &archive,
                candidate: "restored",
            },
            "switch" => Request::Switch {
                candidate: "restored",
                secret: &key,
            },
            "rollback" => Request::RollbackBound {
                operation_id: &operation,
            },
            "inspect" => Request::Inspect,
            "finalize" => Request::Finalize {
                operation_id: &operation,
                secret: &key,
            },
            _ => panic!("invalid fixture action"),
        };
        let message = match run(&binary, &request) {
            Ok(Outcome::Rewrapped { credentials }) => serde_json::json!({"ok":true,
                "result":{"rewrapped":true,"candidate":"restored","credentials":credentials,"secret_persisted":false}}),
            Ok(Outcome::Prepared { files }) => serde_json::json!({"ok":true,
                "result":{"prepared":true,"candidate":"restored","files":files,"secret_included":false}}),
            Ok(Outcome::PendingOperation(operation_id)) => serde_json::json!({"ok":true,
                "result":{"operation_id":operation_id}}),
            Ok(Outcome::TrialPending(operation_id)) => serde_json::json!({"ok":true,
                "result":{"status":"trial_pending", "operation_id":operation_id}}),
            Ok(Outcome::RolledBack(rolled_back)) => {
                serde_json::json!({"ok":true,"result":{"rolled_back":rolled_back}})
            }
            Ok(Outcome::Finalized { already_finalized }) => serde_json::json!({"ok":true,
                "result":{"finalized":true,"already_finalized":already_finalized,"original_retained":true}}),
            Err(ControlError::Refused) => {
                serde_json::json!({"ok":false,"code":"activation_control_refused"})
            }
            Err(error) => panic!("native transport failed: {error:?}"),
        };
        println!("NATIVE_CONTROL_RESULT={message}");
    }
}

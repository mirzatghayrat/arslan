//! Trusted native maintenance transport. No web IPC, implicit approval or retry.
//! A refusal/transport error can follow a partial directory move: retain the
//! journal and reconcile state, never infer that an action had no effect.
use crate::recovery_secret::ExistingSecret;
use serde::Deserialize;
use std::io::{Read, Write};
use std::os::fd::AsRawFd;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

pub(crate) enum Request<'a> {
    Switch {
        candidate: &'a str,
        secret: &'a ExistingSecret,
    },
    Rollback,
    Finalize {
        operation_id: &'a str,
        secret: &'a ExistingSecret,
    },
}

#[derive(Debug, PartialEq)]
pub(crate) enum Outcome {
    TrialPending(String),
    RolledBack(bool),
    Finalized { already_finalized: bool },
}

#[derive(Debug, PartialEq)]
pub(crate) enum ControlError {
    InvalidRequest,
    Unavailable,
    Refused,
    OutcomeUnknown,
}

fn valid_id(value: &str) -> bool {
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
    let value = match request {
        Request::Switch { candidate, secret } => {
            if candidate.is_empty()
                || [".", ".."].contains(candidate)
                || candidate.len() > 255
                || candidate.contains(['/', '\\', '\0'])
            {
                return Err(ControlError::InvalidRequest);
            }
            serde_json::json!({"action":"switch", "candidate":candidate, "secret":secret.expose()})
        }
        Request::Rollback => serde_json::json!({"action":"rollback"}),
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
struct RolledBack {
    rolled_back: bool,
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
        Request::Switch { .. } => {
            let r: Switched = success(bytes)?;
            if r.status != "trial_pending" || !valid_id(&r.operation_id) {
                return Err(ControlError::OutcomeUnknown);
            }
            Ok(Outcome::TrialPending(r.operation_id))
        }
        Request::Rollback => {
            let r: RolledBack = success(bytes)?;
            Ok(Outcome::RolledBack(r.rolled_back))
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

struct OwnedChild(Child);
impl Drop for OwnedChild {
    fn drop(&mut self) {
        if !matches!(self.0.try_wait(), Ok(Some(_))) {
            let _ = self.0.kill();
        }
        let _ = self.0.wait();
    }
}

fn nonblocking(pipe: &impl AsRawFd) -> Result<(), ControlError> {
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

    fn shell(script: &str) -> Command {
        let mut command = Command::new("/bin/sh");
        command.args(["-c", script]);
        command
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
        } else {
            "frozen-smoke-synthetic-only"
        };
        let key = crate::recovery_secret::prepare(Some(synthetic), Path::new("unused"))
            .unwrap_or_else(|_| panic!("invalid fixture"));
        let operation = std::env::var("ARSLAN_CONTROL_TEST_OPERATION").unwrap_or_default();
        let action = std::env::var("ARSLAN_CONTROL_TEST_ACTION").unwrap();
        let request = match action.as_str() {
            "switch" => Request::Switch {
                candidate: "restored",
                secret: &key,
            },
            "rollback" => Request::Rollback,
            "finalize" => Request::Finalize {
                operation_id: &operation,
                secret: &key,
            },
            _ => panic!("invalid fixture action"),
        };
        let message = match run(&binary, &request) {
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

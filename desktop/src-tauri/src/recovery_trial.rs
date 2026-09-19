//! Native restricted trial ownership. Success is health AND graceful child exit,
//! never user approval or finalization. Errors leave the journal for recovery.
use crate::recovery_control::{nonblocking, valid_id, ControlError, OwnedChild};
use crate::recovery_secret::ExistingSecret;
use serde::Deserialize;
use std::io::{Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpStream};
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

#[derive(Debug, PartialEq)]
pub(crate) enum TrialError {
    InvalidRequest,
    Unavailable,
    Unconfirmed,
}

fn pending(error: &std::io::Error) -> bool {
    matches!(
        error.kind(),
        std::io::ErrorKind::WouldBlock | std::io::ErrorKind::Interrupted
    )
}

pub(super) fn token() -> Result<String, TrialError> {
    let mut bytes = [0u8; 32];
    // SAFETY: getentropy writes exactly this live, writable 32-byte buffer.
    if unsafe { libc::getentropy(bytes.as_mut_ptr().cast(), bytes.len()) } != 0 {
        return Err(TrialError::Unavailable);
    }
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

fn port(line: &[u8]) -> Result<u16, TrialError> {
    let line = std::str::from_utf8(line).map_err(|_| TrialError::Unconfirmed)?;
    let number = line
        .strip_prefix("ARSLAN_TRIAL_PORT=")
        .ok_or(TrialError::Unconfirmed)?;
    let value: u16 = number.parse().map_err(|_| TrialError::Unconfirmed)?;
    if value == 0 || value.to_string() != number {
        return Err(TrialError::Unconfirmed);
    }
    Ok(value)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Health {
    status: String,
    mode: String,
    operation_id: String,
}

fn health(bytes: &[u8], operation: &str) -> Result<(), TrialError> {
    let split = bytes
        .windows(4)
        .position(|w| w == b"\r\n\r\n")
        .ok_or(TrialError::Unconfirmed)?;
    let header = std::str::from_utf8(&bytes[..split]).map_err(|_| TrialError::Unconfirmed)?;
    let mut lines = header.split("\r\n");
    if lines.next() != Some("HTTP/1.1 200 OK") {
        return Err(TrialError::Unconfirmed);
    }
    let mut length = None;
    let mut content_type = false;
    let mut no_store = false;
    let mut names = std::collections::HashSet::new();
    for line in lines {
        let (name, value) = line.split_once(':').ok_or(TrialError::Unconfirmed)?;
        if name.is_empty() || !name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-') {
            return Err(TrialError::Unconfirmed);
        }
        let name = name.to_ascii_lowercase();
        if !names.insert(name.clone()) {
            return Err(TrialError::Unconfirmed);
        }
        let value = value.trim();
        match name.as_str() {
            "content-length" => {
                let size: usize = value.parse().map_err(|_| TrialError::Unconfirmed)?;
                if size.to_string() != value {
                    return Err(TrialError::Unconfirmed);
                }
                length = Some(size);
            }
            "content-type" => content_type = value == "application/json",
            "cache-control" => no_store = value == "no-store",
            "transfer-encoding" => return Err(TrialError::Unconfirmed),
            _ => {}
        }
    }
    let body = &bytes[split + 4..];
    if length != Some(body.len()) || !content_type || !no_store {
        return Err(TrialError::Unconfirmed);
    }
    let result: Health = serde_json::from_slice(body).map_err(|_| TrialError::Unconfirmed)?;
    if result.status != "ready"
        || result.mode != "activation_trial"
        || result.operation_id != operation
    {
        return Err(TrialError::Unconfirmed);
    }
    Ok(())
}

fn probe(
    port: u16,
    token: &str,
    operation: &str,
    child: &mut OwnedChild,
    deadline: Instant,
) -> Result<(), TrialError> {
    // An exact numeric loopback address bypasses proxies, DNS and redirects.
    let address = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    let remaining = deadline
        .checked_duration_since(Instant::now())
        .ok_or(TrialError::Unconfirmed)?;
    let mut stream = TcpStream::connect_timeout(&address, remaining.min(Duration::from_secs(1)))
        .map_err(|_| TrialError::Unconfirmed)?;
    stream
        .set_nonblocking(true)
        .map_err(|_| TrialError::Unconfirmed)?;
    let request = format!("GET /api/v1/activation-trial/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {token}\r\nConnection: close\r\n\r\n");
    let mut written = 0;
    let mut response = Vec::new();
    loop {
        if Instant::now() >= deadline
            || child
                .0
                .try_wait()
                .map_err(|_| TrialError::Unconfirmed)?
                .is_some()
        {
            return Err(TrialError::Unconfirmed);
        }
        if written < request.len() {
            match stream.write(&request.as_bytes()[written..]) {
                Ok(0) => return Err(TrialError::Unconfirmed),
                Ok(n) => written += n,
                Err(e) if pending(&e) => {}
                Err(_) => return Err(TrialError::Unconfirmed),
            }
        }
        let mut buffer = [0; 512];
        match stream.read(&mut buffer) {
            Ok(0) if written == request.len() => return health(&response, operation),
            Ok(0) => return Err(TrialError::Unconfirmed),
            Ok(n) => {
                response.extend_from_slice(&buffer[..n]);
                if response.len() > 4096 {
                    return Err(TrialError::Unconfirmed);
                }
            }
            Err(e) if pending(&e) => {}
            Err(_) => return Err(TrialError::Unconfirmed),
        }
        std::thread::sleep(Duration::from_millis(5));
    }
}

pub(crate) fn run(
    executable: &Path,
    operation: &str,
    secret: &ExistingSecret,
) -> Result<(), TrialError> {
    if !executable.is_absolute() {
        return Err(TrialError::InvalidRequest);
    }
    let mut command = Command::new(executable);
    command.arg("--activation-trial");
    execute(command, operation, secret, Duration::from_secs(90))
}

fn execute(
    mut command: Command,
    operation: &str,
    secret: &ExistingSecret,
    timeout: Duration,
) -> Result<(), TrialError> {
    if !valid_id(operation) {
        return Err(TrialError::InvalidRequest);
    }
    let access_token = token()?;
    let mut payload = serde_json::to_vec(&serde_json::json!({"operation_id":operation,
        "access_token":access_token, "secret":secret.expose()}))
    .map_err(|_| TrialError::InvalidRequest)?;
    if payload.len() > 16 * 1024 {
        return Err(TrialError::InvalidRequest);
    }
    payload.push(b'\n');
    let mut child = OwnedChild(
        command
            .env_remove("ARSLAN_SECRET_KEY")
            .env_remove("ARSLAN_SECRET_KEY_FILE")
            .env_remove("ARSLAN_API_TOKEN")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| TrialError::Unavailable)?,
    );
    let mut input = child.0.stdin.take().ok_or(TrialError::Unconfirmed)?;
    let mut output = child.0.stdout.take().ok_or(TrialError::Unconfirmed)?;
    let map = |_: ControlError| TrialError::Unconfirmed;
    nonblocking(&input).map_err(map)?;
    nonblocking(&output).map_err(map)?;
    let deadline = Instant::now() + timeout;
    let mut written = 0;
    let mut bytes = Vec::new();
    let port = loop {
        if Instant::now() >= deadline
            || child
                .0
                .try_wait()
                .map_err(|_| TrialError::Unconfirmed)?
                .is_some()
        {
            return Err(TrialError::Unconfirmed);
        }
        if written < payload.len() {
            match input.write(&payload[written..]) {
                Ok(0) => return Err(TrialError::Unconfirmed),
                Ok(n) => written += n,
                Err(e) if pending(&e) => {}
                Err(_) => return Err(TrialError::Unconfirmed),
            }
        }
        let mut buffer = [0; 512];
        match output.read(&mut buffer) {
            Ok(0) => return Err(TrialError::Unconfirmed),
            Ok(n) => {
                bytes.extend_from_slice(&buffer[..n]);
                if bytes.len() > 4096 {
                    return Err(TrialError::Unconfirmed);
                }
            }
            Err(e) if pending(&e) => {}
            Err(_) => return Err(TrialError::Unconfirmed),
        }
        if let Some(end) = bytes.iter().position(|b| *b == b'\n') {
            if written != payload.len() || end + 1 != bytes.len() {
                return Err(TrialError::Unconfirmed);
            }
            break port(&bytes[..end])?;
        }
        std::thread::sleep(Duration::from_millis(5));
    };
    probe(port, &access_token, operation, &mut child, deadline)?;
    drop(input); // EOF requests graceful shutdown and durable receipt creation.
    let shutdown = Instant::now() + Duration::from_secs(10).min(timeout);
    let mut eof = false;
    loop {
        if Instant::now() >= shutdown {
            return Err(TrialError::Unconfirmed);
        }
        let mut buffer = [0; 512];
        match output.read(&mut buffer) {
            Ok(0) => eof = true,
            Ok(n) => {
                bytes.extend_from_slice(&buffer[..n]);
                if bytes.len() > 4096 {
                    return Err(TrialError::Unconfirmed);
                }
            }
            Err(e) if pending(&e) => {}
            Err(_) => return Err(TrialError::Unconfirmed),
        }
        if let Some(status) = child.0.try_wait().map_err(|_| TrialError::Unconfirmed)? {
            if eof {
                return if status.success() {
                    Ok(())
                } else {
                    Err(TrialError::Unconfirmed)
                };
            }
        }
        std::thread::sleep(Duration::from_millis(5));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const ID: &str = "12345678-1234-1234-1234-123456789abc";
    fn reply(body: &str) -> Vec<u8> {
        format!("HTTP/1.1 200 OK\r\ncontent-length: {}\r\ncontent-type: application/json\r\ncache-control: no-store\r\n\r\n{body}", body.len()).into_bytes()
    }
    fn body() -> String {
        format!(r#"{{"status":"ready","mode":"activation_trial","operation_id":"{ID}"}}"#)
    }
    #[test]
    fn handshake_is_exact_and_port_bounded() {
        assert_eq!(port(b"ARSLAN_TRIAL_PORT=12345"), Ok(12345));
        for line in [
            "ARSLAN_PORT=12345",
            "ARSLAN_TRIAL_PORT=0",
            "ARSLAN_TRIAL_PORT=65536",
            "ARSLAN_TRIAL_PORT=+12",
            "ARSLAN_TRIAL_PORT=012",
            "ARSLAN_TRIAL_PORT=12 extra",
        ] {
            assert_eq!(port(line.as_bytes()), Err(TrialError::Unconfirmed));
        }
    }
    #[test]
    fn health_requires_exact_operation_status_shape_and_http_framing() {
        let valid = reply(&body());
        assert_eq!(health(&valid, ID), Ok(()));
        assert_eq!(health(&valid, "other"), Err(TrialError::Unconfirmed));
        let text = String::from_utf8(valid).unwrap();
        for bad in [
            text.replace("200 OK", "302 Found"),
            text.replace("no-store", "public"),
            text.replace("content-type:", "transfer-encoding:"),
            text.replace("content-length:", "content-length: 1\r\ncontent-length:"),
            format!("{text}extra"),
            text.replace("ready", "other"),
            text.replace("application/json", "text/html"),
        ] {
            assert_eq!(health(bad.as_bytes(), ID), Err(TrialError::Unconfirmed));
        }
        for invalid in [
            body().replace("\"status\":", "\"extra\":1,\"status\":"),
            body().replace("\"status\":", "\"status\":\"ready\",\"status\":"),
        ] {
            assert_eq!(health(&reply(&invalid), ID), Err(TrialError::Unconfirmed));
        }
    }
    #[test]
    fn generated_tokens_are_fresh_and_match_pipe_contract() {
        let first = token().unwrap();
        assert_eq!(first.len(), 64);
        assert!(first
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)));
        assert_ne!(first, token().unwrap());
    }
    #[test]
    fn health_alone_cannot_hide_failed_child_exit() {
        for exit in [0, 7] {
            let listener = std::net::TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
            let port = listener.local_addr().unwrap().port();
            let responder = std::thread::spawn(move || {
                let (mut socket, _) = listener.accept().unwrap();
                socket
                    .set_read_timeout(Some(Duration::from_secs(3)))
                    .unwrap();
                let mut request = Vec::new();
                while !request.ends_with(b"\r\n\r\n") {
                    let mut byte = [0];
                    assert_eq!(socket.read(&mut byte).unwrap(), 1);
                    request.push(byte[0]);
                    assert!(request.len() < 4096);
                }
                let request = String::from_utf8(request).unwrap();
                assert!(request.starts_with("GET /api/v1/activation-trial/health HTTP/1.1\r\n"));
                let auth = request
                    .lines()
                    .find_map(|l| l.strip_prefix("Authorization: Bearer "))
                    .unwrap();
                assert_eq!(auth.len(), 64);
                socket.write_all(&reply(&body())).unwrap();
            });
            let mut command = Command::new("/bin/sh");
            command.args(["-c", &format!("test -z \"${{ARSLAN_SECRET_KEY+x}}${{ARSLAN_SECRET_KEY_FILE+x}}${{ARSLAN_API_TOKEN+x}}\" || exit 9; read -r request; printf 'ARSLAN_TRIAL_PORT={port}\\n'; while IFS= read -r rest; do :; done; exit {exit}")]);
            command
                .env("ARSLAN_SECRET_KEY", "must-not-inherit")
                .env("ARSLAN_SECRET_KEY_FILE", "/must-not-read")
                .env("ARSLAN_API_TOKEN", "must-not-inherit");
            let key = crate::recovery_secret::prepare(Some("synthetic-only"), Path::new("unused"))
                .unwrap();
            let result = execute(command, ID, &key, Duration::from_secs(3));
            responder.join().unwrap();
            assert_eq!(
                result,
                if exit == 0 {
                    Ok(())
                } else {
                    Err(TrialError::Unconfirmed)
                }
            );
        }
    }

    #[test]
    fn stalled_child_is_reaped_and_invalid_or_excess_output_refused() {
        let path = std::env::temp_dir().join(format!(
            "arslan-trial-pid-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let key =
            crate::recovery_secret::prepare(Some("synthetic-only"), Path::new("unused")).unwrap();
        let mut command = Command::new("/bin/sh");
        command
            .args([
                "-c",
                "printf '%s' \"$$\" > \"$PIDFILE\"; while :; do :; done",
            ])
            .env("PIDFILE", &path);
        assert_eq!(
            execute(command, ID, &key, Duration::from_millis(250)),
            Err(TrialError::Unconfirmed)
        );
        let pid: libc::pid_t = std::fs::read_to_string(&path).unwrap().parse().unwrap();
        std::fs::remove_file(path).unwrap();
        // SAFETY: queries only the exact synthetic process owned by this test.
        assert_eq!(
            unsafe { libc::waitpid(pid, std::ptr::null_mut(), libc::WNOHANG) },
            -1
        );
        assert_eq!(
            std::io::Error::last_os_error().raw_os_error(),
            Some(libc::ECHILD)
        );
        for script in [
            "read -r request; printf 'ARSLAN_PORT=12345\\n'; while :; do :; done",
            "read -r request; while :; do printf 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'; done",
        ] {
            let mut command = Command::new("/bin/sh");
            command.args(["-c", script]);
            assert_eq!(
                execute(command, ID, &key, Duration::from_secs(1)),
                Err(TrialError::Unconfirmed)
            );
        }
        assert_eq!(
            run(Path::new("relative"), ID, &key),
            Err(TrialError::InvalidRequest)
        );
        assert_eq!(
            execute(
                Command::new("/not-executed"),
                "invalid",
                &key,
                Duration::from_secs(1)
            ),
            Err(TrialError::InvalidRequest)
        );
    }

    #[test]
    fn stalled_or_oversized_health_response_never_completes() {
        for oversized in [false, true] {
            let listener = std::net::TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
            let port = listener.local_addr().unwrap().port();
            let responder = std::thread::spawn(move || {
                let (mut socket, _) = listener.accept().unwrap();
                socket
                    .set_read_timeout(Some(Duration::from_secs(2)))
                    .unwrap();
                if oversized {
                    let _ = socket.write_all(&[b'x'; 5000]);
                }
                let mut ignored = Vec::new();
                // The client's bounded deadline or size rejection closes this
                // stream; no sleep or indefinitely retained test connection.
                let _ = socket.read_to_end(&mut ignored);
            });
            let mut command = Command::new("/bin/sh");
            command.args(["-c", &format!("read -r request; printf 'ARSLAN_TRIAL_PORT={port}\\n'; while IFS= read -r rest; do :; done")]);
            let key = crate::recovery_secret::prepare(Some("synthetic-only"), Path::new("unused"))
                .unwrap();
            assert_eq!(
                execute(command, ID, &key, Duration::from_millis(250)),
                Err(TrialError::Unconfirmed)
            );
            responder.join().unwrap();
        }
    }
}

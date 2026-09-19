//! Stop only the normal backend child owned by this desktop, before recovery.
//! The pipe stays open: EOF is abrupt parent-death cleanup, not this protocol.
use crate::recovery_control::{nonblocking, OwnedChild};
use std::io::Write;
use std::process::Child;
use std::sync::{
    atomic::{AtomicBool, AtomicUsize, Ordering},
    Arc,
};
use std::time::{Duration, Instant};

#[derive(Debug, PartialEq)]
pub(crate) struct Unconfirmed;

#[derive(Default)]
pub(crate) struct Receipt {
    requested: AtomicBool,
    acknowledgements: AtomicUsize,
    invalid: AtomicBool,
    closed: AtomicBool,
}

impl Receipt {
    pub(crate) fn failed(&self) {
        self.invalid.store(true, Ordering::SeqCst);
    }
    pub(crate) fn observe(&self, line: &str) {
        if line == "ARSLAN_STOPPED=1" {
            if !self.requested.load(Ordering::SeqCst) {
                self.invalid.store(true, Ordering::SeqCst);
            }
            self.acknowledgements.fetch_add(1, Ordering::SeqCst);
        }
    }
    pub(crate) fn closed(&self) {
        self.closed.store(true, Ordering::SeqCst);
    }
    fn confirmed(&self) -> bool {
        self.closed.load(Ordering::SeqCst)
            && !self.invalid.load(Ordering::SeqCst)
            && self.acknowledgements.load(Ordering::SeqCst) == 1
    }
}

pub(crate) fn stop(child: Child, receipt: Arc<Receipt>) -> Result<(), Unconfirmed> {
    stop_with_timeout(child, receipt, Duration::from_secs(15))
}

fn stop_with_timeout(
    child: Child,
    receipt: Arc<Receipt>,
    timeout: Duration,
) -> Result<(), Unconfirmed> {
    let mut child = OwnedChild(child);
    if child.0.try_wait().map_err(|_| Unconfirmed)?.is_some() {
        return Err(Unconfirmed);
    }
    let mut input = child.0.stdin.take().ok_or(Unconfirmed)?;
    nonblocking(&input).map_err(|_| Unconfirmed)?;
    if receipt.requested.swap(true, Ordering::SeqCst) {
        return Err(Unconfirmed);
    }
    let request = b"ARSLAN_SHUTDOWN\n";
    let mut written = 0;
    let deadline = Instant::now() + timeout;
    loop {
        if Instant::now() >= deadline {
            return Err(Unconfirmed);
        }
        if written < request.len() {
            match input.write(&request[written..]) {
                Ok(0) => return Err(Unconfirmed),
                Ok(n) => written += n,
                Err(e)
                    if matches!(
                        e.kind(),
                        std::io::ErrorKind::WouldBlock | std::io::ErrorKind::Interrupted
                    ) => {}
                Err(_) => return Err(Unconfirmed),
            }
        }
        if let Some(status) = child.0.try_wait().map_err(|_| Unconfirmed)? {
            if !status.success() || written != request.len() {
                return Err(Unconfirmed);
            }
            if !receipt.closed.load(Ordering::SeqCst) {
                std::thread::sleep(Duration::from_millis(5));
                continue;
            }
            return if receipt.confirmed() {
                Ok(())
            } else {
                Err(Unconfirmed)
            };
        }
        std::thread::sleep(Duration::from_millis(5));
    }
}

#[cfg(test)]
pub(crate) fn packaged_fixture(binary: &std::path::Path) {
    use std::io::{BufRead, BufReader};
    use std::process::{Command, Stdio};
    // Caller validates the disposable HOME and trusted temporary binary prefix.
    let listener = std::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0)).unwrap();
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    let mut child = Command::new(binary)
        .env("ARSLAN_PORT", port.to_string())
        .env("ARSLAN_SECRET_KEY", "frozen-smoke-synthetic-only")
        .env("ARSLAN_SECRET_KEY_FILE", "")
        .env_remove("ARSLAN_API_TOKEN")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let stdout = child.stdout.take().unwrap();
    let receipt = Arc::new(Receipt::default());
    let reader = receipt.clone();
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines() {
            let Ok(line) = line else {
                reader.failed();
                break;
            };
            reader.observe(&line);
            if line == format!("ARSLAN_PORT={port}") {
                let _ = tx.send(());
            }
        }
        reader.closed();
    });
    if rx.recv_timeout(Duration::from_secs(45)).is_err() || crate::wait_for_health(port).is_err() {
        let _ = child.kill();
        let _ = child.wait();
        panic!("synthetic normal backend failed startup");
    }
    assert_eq!(stop(child, receipt), Ok(()));
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::process::{Command, Stdio};
    fn spawn(script: &str) -> (Child, Arc<Receipt>) {
        use std::io::{BufRead, BufReader};
        let mut child = Command::new("/bin/sh")
            .args(["-c", script])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let receipt = Arc::new(Receipt::default());
        let reader = receipt.clone();
        let stdout = child.stdout.take().unwrap();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                let Ok(line) = line else {
                    reader.failed();
                    break;
                };
                reader.observe(&line);
            }
            reader.closed();
        });
        (child, receipt)
    }
    #[test]
    fn exact_stop_request_and_successful_exit_are_required() {
        let (child, receipt) = spawn("IFS= read -r request; test \"$request\" = ARSLAN_SHUTDOWN || exit 7; printf 'ARSLAN_STOPPED=1\\n'");
        assert_eq!(stop(child, receipt), Ok(()));
        for script in [
            "IFS= read -r request; exit 7",
            "IFS= read -r request; exit 0",
            "IFS= read -r request; printf 'ARSLAN_STOPPED=1\\nARSLAN_STOPPED=1\\n'",
        ] {
            let (child, receipt) = spawn(script);
            assert_eq!(stop(child, receipt), Err(Unconfirmed));
        }
        let (mut exited, receipt) = spawn("exit 0");
        exited.wait().unwrap();
        assert_eq!(stop(exited, receipt), Err(Unconfirmed));
    }
    #[test]
    fn premature_or_malformed_acknowledgement_is_not_confirmation() {
        let receipt = Receipt::default();
        receipt.observe("ARSLAN_STOPPED=1");
        receipt.requested.store(true, Ordering::SeqCst);
        receipt.closed();
        assert!(!receipt.confirmed());
        let receipt = Receipt::default();
        receipt.requested.store(true, Ordering::SeqCst);
        receipt.observe("ARSLAN_STOPPED=1 extra");
        receipt.closed();
        assert!(!receipt.confirmed());
        let receipt = Receipt::default();
        receipt.requested.store(true, Ordering::SeqCst);
        receipt.observe("ARSLAN_STOPPED=1");
        receipt.failed();
        receipt.closed();
        assert!(!receipt.confirmed());
    }
    #[test]
    fn noncooperating_child_is_reaped_but_never_confirmed() {
        let (child, receipt) = spawn("while :; do :; done");
        let pid = child.id() as libc::pid_t;
        assert_eq!(
            stop_with_timeout(child, receipt, Duration::from_millis(100)),
            Err(Unconfirmed)
        );
        // SAFETY: checks only the exact synthetic child owned above.
        assert_eq!(
            unsafe { libc::waitpid(pid, std::ptr::null_mut(), libc::WNOHANG) },
            -1
        );
        assert_eq!(
            std::io::Error::last_os_error().raw_os_error(),
            Some(libc::ECHILD)
        );
    }
}

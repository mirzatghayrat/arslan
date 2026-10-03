//! Arslan Bridge supervisor (docs/specs/mobile-bridge-protocol.md §6, §6.1).
//!
//! The Bridge is the iPhone companion helper shipped at
//! `Arslan.app/Contents/Helpers/ArslanBridge.app`. While Settings › iPhone › "Use Arslan from
//! your iPhone" is on (`phone_bridge` in /desktop/status), this keeps one Bridge running:
//!
//! - its environment has the backend's secrets removed (the token never travels that way);
//! - it gets one JSON config line on stdin (`port`, `token`), and stdin stays open: when the
//!   switch goes off we close it, and when Arslan quits the OS closes it, and the Bridge exits;
//! - a Bridge that dies is started again after 1, 2, 4 … 300 seconds.
//!
//! Dev builds (no Helpers folder) simply never start one.

use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::time::{Duration, Instant};

const MAX_BACKOFF_SECS: u64 = 300;

/// `…/Arslan.app/Contents/MacOS/<exe>` → `…/Arslan.app/Contents/Helpers/ArslanBridge.app/Contents/MacOS/ArslanBridge`.
pub fn executable_for(app_exe: &Path) -> Option<PathBuf> {
    let contents = app_exe.parent()?.parent()?;
    if contents.file_name()? != "Contents" {
        return None;
    }
    Some(contents.join("Helpers/ArslanBridge.app/Contents/MacOS/ArslanBridge"))
}

/// The one line the Bridge reads first. JSON, so any token survives intact.
pub fn config_line(port: u16, token: Option<&str>) -> String {
    let mut line = serde_json::json!({ "port": port, "token": token.unwrap_or("") }).to_string();
    line.push('\n');
    line
}

pub fn backoff(failures: u32) -> Duration {
    Duration::from_secs(
        1u64.checked_shl(failures.min(16))
            .unwrap_or(u64::MAX)
            .min(MAX_BACKOFF_SECS),
    )
}

#[derive(Default)]
pub struct Supervisor {
    executable: Option<PathBuf>,
    running: Option<(Child, ChildStdin)>,
    failures: u32,
    next_try: Option<Instant>,
}

impl Supervisor {
    pub fn for_this_app() -> Self {
        let executable = std::env::current_exe()
            .ok()
            .and_then(|exe| executable_for(&exe));
        Self {
            executable,
            running: None,
            failures: 0,
            next_try: None,
        }
    }

    #[cfg(test)]
    fn with_executable(path: PathBuf) -> Self {
        Self {
            executable: Some(path),
            running: None,
            failures: 0,
            next_try: None,
        }
    }

    #[cfg(test)]
    fn is_running(&self) -> bool {
        self.running.is_some()
    }

    /// Called on every status poll: start, keep, restart or stop the Bridge.
    pub fn tick(&mut self, want: bool, port: u16, token: Option<&str>) {
        // A Bridge that exited on its own counts as a failure and waits out the backoff.
        if let Some((child, _)) = self.running.as_mut() {
            if let Ok(Some(_)) = child.try_wait() {
                self.running = None;
                self.failures += 1;
                self.next_try = Some(Instant::now() + backoff(self.failures));
            }
        }
        if !want {
            self.stop();
            self.failures = 0;
            self.next_try = None;
            return;
        }
        if self.running.is_some() || self.next_try.is_some_and(|t| Instant::now() < t) {
            return;
        }
        let Some(path) = self.executable.as_ref().filter(|p| p.is_file()) else {
            return;
        };
        match Self::spawn(path, port, token) {
            Some(pair) => {
                self.running = Some(pair);
                self.next_try = None;
            }
            None => {
                self.failures += 1;
                self.next_try = Some(Instant::now() + backoff(self.failures));
            }
        }
    }

    fn spawn(path: &Path, port: u16, token: Option<&str>) -> Option<(Child, ChildStdin)> {
        let mut child = Command::new(path)
            .env_remove("ARSLAN_SECRET_KEY")
            .env_remove("ARSLAN_SECRET_KEY_FILE")
            .env_remove("ARSLAN_API_TOKEN")
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .ok()?;
        let mut stdin = child.stdin.take()?;
        if stdin
            .write_all(config_line(port, token).as_bytes())
            .and_then(|_| stdin.flush())
            .is_err()
        {
            let _ = child.kill();
            let _ = child.wait();
            return None;
        }
        Some((child, stdin))
    }

    /// Close stdin (the Bridge exits on EOF); kill it if it has not gone within 2 s.
    pub fn stop(&mut self) {
        if let Some((mut child, stdin)) = self.running.take() {
            drop(stdin);
            let deadline = Instant::now() + Duration::from_secs(2);
            while Instant::now() < deadline {
                if let Ok(Some(_)) = child.try_wait() {
                    return;
                }
                std::thread::sleep(Duration::from_millis(50));
            }
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

impl Drop for Supervisor {
    fn drop(&mut self) {
        self.stop();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_bridge_lives_in_contents_helpers() {
        let exe = Path::new("/Applications/Arslan.app/Contents/MacOS/arslan-desktop");
        assert_eq!(
            executable_for(exe).unwrap(),
            Path::new("/Applications/Arslan.app/Contents/Helpers/ArslanBridge.app/Contents/MacOS/ArslanBridge")
        );
        assert!(
            executable_for(Path::new("/target/debug/arslan-desktop")).is_none(),
            "dev builds start none"
        );
    }

    #[test]
    fn the_config_line_is_one_json_line_with_any_token_intact() {
        let line = config_line(8765, Some("a\"b\\c\nd"));
        assert!(line.ends_with('\n') && line.matches('\n').count() == 1);
        let v: serde_json::Value = serde_json::from_str(line.trim_end()).unwrap();
        assert_eq!(v["port"], 8765);
        assert_eq!(v["token"], "a\"b\\c\nd");
        assert_eq!(
            serde_json::from_str::<serde_json::Value>(config_line(1, None).trim_end()).unwrap()
                ["token"],
            ""
        );
    }

    #[test]
    fn backoff_doubles_to_five_minutes() {
        assert_eq!(backoff(1), Duration::from_secs(2));
        assert_eq!(backoff(4), Duration::from_secs(16));
        assert_eq!(backoff(9), Duration::from_secs(300));
        assert_eq!(backoff(40), Duration::from_secs(300));
    }

    /// A stand-in Bridge: records its stdin, exits on EOF (like the real one).
    fn fake_bridge(dir: &Path) -> (PathBuf, PathBuf) {
        let out = dir.join("stdin.txt");
        let script = dir.join("bridge.sh");
        std::fs::write(
            &script,
            format!(
                "#!/bin/sh\nenv > \"{0}.env\"\ncat > \"{0}\"\n",
                out.display()
            ),
        )
        .unwrap();
        std::fs::set_permissions(&script, std::os::unix::fs::PermissionsExt::from_mode(0o755))
            .unwrap();
        (script, out)
    }

    fn wait_until(mut done: impl FnMut() -> bool) -> bool {
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline {
            if done() {
                return true;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        false
    }

    #[test]
    fn on_starts_it_with_the_config_and_no_secrets_off_stops_it() {
        let dir = std::env::temp_dir().join(format!("arslan-bridge-sup-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let (script, out) = fake_bridge(&dir);
        std::env::set_var("ARSLAN_API_TOKEN", "must-not-leak");
        let mut sup = Supervisor::with_executable(script);
        sup.tick(false, 8765, Some("tok"));
        assert!(!sup.is_running(), "off: nothing runs");
        sup.tick(true, 8765, Some("tok"));
        assert!(sup.is_running());
        sup.tick(true, 8765, Some("tok"));
        assert!(sup.is_running(), "stays one Bridge");
        let stopping = Instant::now();
        sup.tick(false, 8765, Some("tok"));
        assert!(!sup.is_running());
        assert!(
            stopping.elapsed() < Duration::from_secs(1),
            "closing stdin ends it; no kill needed"
        );
        assert!(wait_until(|| std::fs::read_to_string(&out)
            .map(|s| s.contains("\"token\":\"tok\""))
            .unwrap_or(false)));
        let env = std::fs::read_to_string(dir.join("stdin.txt.env")).unwrap();
        assert!(
            !env.contains("must-not-leak"),
            "the token never goes through the environment"
        );
        std::env::remove_var("ARSLAN_API_TOKEN");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_bridge_that_dies_waits_out_the_backoff() {
        let dir = std::env::temp_dir().join(format!("arslan-bridge-die-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let script = dir.join("dies.sh");
        std::fs::write(&script, "#!/bin/sh\nexit 1\n").unwrap();
        std::fs::set_permissions(&script, std::os::unix::fs::PermissionsExt::from_mode(0o755))
            .unwrap();
        let mut sup = Supervisor::with_executable(script);
        sup.tick(true, 1, None);
        assert!(wait_until(|| {
            sup.tick(true, 1, None);
            sup.failures >= 1
        }));
        assert!(
            !sup.is_running() && sup.next_try.is_some(),
            "not restarted at once"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }
}

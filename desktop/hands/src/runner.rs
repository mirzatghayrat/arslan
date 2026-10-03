//! Running agent-desktop: one process per command, a clean environment, a
//! deadline, and a kill switch.
//!
//! agent-desktop is Hands' child, so Hands is its responsible process and Hands'
//! Accessibility grant is the one that applies (spec §0, M5). The environment is
//! rebuilt from scratch: nothing the backend or a launcher set reaches it.

use std::io::Read;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

/// Largest envelope Hands passes on (a skeleton snapshot is far below this).
pub const MAX_OUTPUT: usize = 4 * 1024 * 1024;

/// Every agent-desktop process running right now, by run number, so Stop can
/// kill them. A run only ever waits on its own number.
static RUNNING: Mutex<Vec<(u64, Child)>> = Mutex::new(Vec::new());
static NEXT: AtomicU64 = AtomicU64::new(1);
/// Bumped by Stop under the RUNNING lock. A request remembers the generation it
/// started in; a command it would start after a Stop is killed at once, so no
/// Stop can fall between two commands of one request.
static GENERATION: AtomicU64 = AtomicU64::new(0);

pub fn generation() -> u64 {
    GENERATION.load(Ordering::SeqCst)
}

#[derive(Debug, Clone)]
pub struct Runner {
    pub binary: PathBuf,
    /// agent-desktop's state root (`AGENT_DESKTOP_HOME`), inside Hands' folder.
    pub state_root: PathBuf,
    pub home: PathBuf,
}

#[derive(Debug)]
pub struct Output {
    pub exit: Option<i32>,
    pub stdout: String,
    /// Ended by Stop or by its deadline before it finished.
    pub killed: bool,
    pub timed_out: bool,
}

enum Step {
    Running,
    Exited(Option<i32>),
    Gone,
}

impl Runner {
    /// Run one command for a request that started in `generation`.
    pub fn run(
        &self,
        argv: &[String],
        deadline: Duration,
        generation: u64,
    ) -> Result<Output, String> {
        let mut child = Command::new(&self.binary)
            .args(argv)
            .env_clear()
            .env("HOME", &self.home)
            .env("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
            .env("AGENT_DESKTOP_HOME", &self.state_root)
            .env("LANG", "en_US.UTF-8")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| format!("cannot start agent-desktop: {e}"))?;
        let mut stdout = child.stdout.take().ok_or("no stdout")?;
        let reader = thread::spawn(move || {
            let mut buf = Vec::new();
            let _ = (&mut stdout)
                .take(MAX_OUTPUT as u64 + 1)
                .read_to_end(&mut buf);
            buf
        });
        let id = NEXT.fetch_add(1, Ordering::SeqCst);
        {
            let mut running = RUNNING.lock().unwrap_or_else(|p| p.into_inner());
            if GENERATION.load(Ordering::SeqCst) != generation {
                let _ = child.kill();
                let _ = child.wait();
                drop(running);
                let _ = reader.join();
                return Ok(Output {
                    exit: None,
                    killed: true,
                    timed_out: false,
                    stdout: String::new(),
                });
            }
            running.push((id, child));
        }

        let started = Instant::now();
        let mut timed_out = false;
        let exit = loop {
            let step = {
                let mut running = RUNNING.lock().unwrap_or_else(|p| p.into_inner());
                match running.iter().position(|(n, _)| *n == id) {
                    None => Step::Gone, // Stop killed and reaped it
                    Some(i) => match running[i].1.try_wait() {
                        Ok(Some(status)) => {
                            running.remove(i);
                            Step::Exited(status.code())
                        }
                        _ if started.elapsed() > deadline => {
                            let (_, mut child) = running.remove(i);
                            let _ = child.kill();
                            let _ = child.wait();
                            timed_out = true;
                            Step::Gone
                        }
                        _ => Step::Running,
                    },
                }
            };
            match step {
                Step::Running => thread::sleep(Duration::from_millis(5)),
                Step::Exited(code) => break Some(code),
                Step::Gone => break None,
            }
        };
        let raw = reader.join().unwrap_or_default();
        let stdout = String::from_utf8_lossy(&raw[..raw.len().min(MAX_OUTPUT)]).into_owned();
        Ok(Output {
            exit: exit.flatten(),
            killed: exit.is_none(),
            timed_out,
            stdout,
        })
    }
}

/// Stop: kill every agent-desktop process in flight. True if there was one.
pub fn kill_all() -> bool {
    let children: Vec<(u64, Child)> = {
        let mut running = RUNNING.lock().unwrap_or_else(|p| p.into_inner());
        GENERATION.fetch_add(1, Ordering::SeqCst);
        running.drain(..).collect()
    };
    let any = !children.is_empty();
    for (_, mut child) in children {
        let _ = child.kill();
        let _ = child.wait();
    }
    any
}

//! Borrow (spec 2026-10-08-0157 §6.3): for the few actions that only work with the app in front
//! (a pop-up's menu takes the key window while it is open; `front: true` when the model asks
//! after a background try did nothing), Hands borrows the front for about a second and gives
//! everything back:
//!
//! 1. never while the user types a password (secure input) — wait;
//! 2. wait for a typing pause (no key from the user for 1.0 s, measured by the key tap; up to
//!    40 s, then `waiting_for_pause`) — Arslan never interrupts typing;
//! 3. glow on (every display);
//! 4. hold the user's keys (src/keyhold.m), with a deadline the tap enforces on its own;
//! 5. note the front app and the pointer;
//! 6. act;
//! 7. give the front back, and the pointer if Hands moved it (not if the user did);
//! 8. replay the held keys into the user's window, in order, then glow off;
//! 9. if the user moved or clicked the mouse meanwhile, say so (`yielded_to_user`).

use crate::argv::{refuse, Refusal};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::time::{Duration, Instant};

/// Tests run Hands in-process: a real borrow there would hold the developer's own keyboard and
/// light their screen. Only Rust code in the same process can turn this on; then a borrow does
/// none of that, and only counts itself.
static STAND_IN: AtomicBool = AtomicBool::new(false);
static BORROWS: AtomicUsize = AtomicUsize::new(0);

/// What a borrow is doing right now, for the island: 0 none, 1 waiting for the user to pause,
/// 2 borrowing. And the user's answers from the island while it waits.
static PHASE: AtomicUsize = AtomicUsize::new(0);
static GO_NOW: AtomicBool = AtomicBool::new(false);
static SKIP: AtomicBool = AtomicBool::new(false);

/// The island's "now" (borrow without waiting for the pause) or "not this time" (give up).
pub fn answer(now: bool) -> bool {
    if PHASE.load(Ordering::SeqCst) != 1 {
        return false;
    }
    if now {
        GO_NOW.store(true, Ordering::SeqCst);
    } else {
        SKIP.store(true, Ordering::SeqCst);
    }
    true
}

/// For the island: "waiting" / "borrowing" / none.
pub fn phase() -> Option<&'static str> {
    match PHASE.load(Ordering::SeqCst) {
        1 => Some("waiting"),
        2 => Some("borrowing"),
        _ => None,
    }
}

static TYPING: AtomicBool = AtomicBool::new(false);

pub fn stand_in_for_tests(on: bool) {
    STAND_IN.store(on, Ordering::SeqCst);
    BORROWS.store(0, Ordering::SeqCst);
    TYPING.store(false, Ordering::SeqCst);
}

/// In tests: the user is (or stops) typing, so a borrow waits for the pause.
pub fn typing_for_tests(typing: bool) {
    TYPING.store(typing, Ordering::SeqCst);
}

pub fn standing_in() -> bool {
    STAND_IN.load(Ordering::SeqCst)
}

/// How many borrows began since `stand_in_for_tests`.
pub fn borrows_for_tests() -> usize {
    BORROWS.load(Ordering::SeqCst)
}

/// No key from the user for this long counts as a pause (§6.3 step 2).
pub const PAUSE: Duration = Duration::from_millis(1_000);
/// How long a borrow waits for that pause before answering `waiting_for_pause` (inside the
/// backend's 60 s for one Hands call, with room for the action itself).
pub const WAIT_MAX: Duration = Duration::from_secs(40);
/// The key hold's own deadline: past it the user's keys are given back whatever happens.
pub const HOLD_MAX: Duration = Duration::from_secs(10);

pub struct Borrowed {
    front: Option<i32>,
    pointer: Option<(f64, f64)>,
    started: Instant,
    held: bool,
    waited: Duration,
}

/// What a borrow gave back, for the reply.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct GaveBack {
    pub front_restored: bool,
    pub keys_replayed: usize,
    pub yielded_to_user: bool,
    pub waited_ms: u64,
    pub borrowed_ms: u64,
}

/// Steps 1-5. `stopped` says whether the user pressed Stop meanwhile.
pub fn begin(wait_max: Duration, stopped: impl Fn() -> bool) -> Result<Borrowed, Refusal> {
    let standing_in = STAND_IN.load(Ordering::SeqCst);
    let held = !standing_in && crate::keyhold::start().is_ok();
    let asked = Instant::now();
    GO_NOW.store(false, Ordering::SeqCst);
    SKIP.store(false, Ordering::SeqCst);
    PHASE.store(1, Ordering::SeqCst);
    loop {
        if stopped() {
            PHASE.store(0, Ordering::SeqCst);
            return Err(refuse("stopped_by_user", "stopped before the borrow began"));
        }
        if SKIP.swap(false, Ordering::SeqCst) {
            PHASE.store(0, Ordering::SeqCst);
            return Err(refuse(
                "borrow_declined",
                "the user said not this time; nothing was done",
            ));
        }
        let secure = !standing_in && crate::keyhold::secure_input();
        let typing = if standing_in {
            TYPING.load(Ordering::SeqCst)
        } else {
            crate::keyhold::user_key_age_ms().is_some_and(|ms| ms < PAUSE.as_millis() as f64)
        };
        // "Now" from the user skips the pause - never secure input (a password is being typed).
        if !secure && (!typing || GO_NOW.swap(false, Ordering::SeqCst)) {
            break;
        }
        if asked.elapsed() >= wait_max {
            PHASE.store(0, Ordering::SeqCst);
            return Err(if secure {
                refuse(
                    "secure_input",
                    "the user is typing a password; nothing is borrowed while they do",
                )
            } else {
                refuse(
                    "waiting_for_pause",
                    "the user kept typing; Arslan waits for a pause before borrowing the front",
                )
            });
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    let waited = asked.elapsed();
    PHASE.store(2, Ordering::SeqCst);
    if standing_in {
        BORROWS.fetch_add(1, Ordering::SeqCst);
        return Ok(Borrowed {
            front: None,
            pointer: None,
            started: Instant::now(),
            held: false,
            waited,
        });
    }
    crate::glow::show();
    if held {
        crate::keyhold::arm(HOLD_MAX);
    }
    Ok(Borrowed {
        front: front_pid(),
        pointer: pointer(),
        started: Instant::now(),
        held,
        waited,
    })
}

/// Steps 7-9.
pub fn end(borrowed: Borrowed) -> GaveBack {
    let elapsed = borrowed.started.elapsed();
    if STAND_IN.load(Ordering::SeqCst) {
        PHASE.store(0, Ordering::SeqCst);
        return GaveBack {
            front_restored: true,
            keys_replayed: 0,
            yielded_to_user: false,
            waited_ms: borrowed.waited.as_millis() as u64,
            borrowed_ms: elapsed.as_millis() as u64,
        };
    }
    let user_moved =
        crate::keyhold::user_mouse_age_ms().is_some_and(|ms| ms < elapsed.as_millis() as f64);
    let mut front_restored = true;
    if let Some(before) = borrowed.front {
        if front_pid() != Some(before) {
            give_front(before);
            let until = Instant::now() + Duration::from_millis(400);
            while front_pid() != Some(before) && Instant::now() < until {
                std::thread::sleep(Duration::from_millis(20));
            }
        }
        front_restored = front_pid() == Some(before);
    }
    // The pointer goes back only if Hands moved it: if the user moved it, it is theirs.
    if !user_moved {
        if let (Some((x, y)), Some((nx, ny))) = (borrowed.pointer, pointer()) {
            if (x - nx).abs() > 0.5 || (y - ny).abs() > 0.5 {
                warp(x, y);
            }
        }
    }
    let keys_replayed = if borrowed.held {
        crate::keyhold::release()
    } else {
        0
    };
    crate::glow::hide();
    PHASE.store(0, Ordering::SeqCst);
    GaveBack {
        front_restored,
        keys_replayed,
        yielded_to_user: user_moved,
        waited_ms: borrowed.waited.as_millis() as u64,
        borrowed_ms: elapsed.as_millis() as u64,
    }
}

#[cfg(target_os = "macos")]
fn front_pid() -> Option<i32> {
    crate::macos::frontmost_pid()
}
#[cfg(target_os = "macos")]
fn give_front(pid: i32) {
    crate::macos::give_front_back(pid);
}
#[cfg(target_os = "macos")]
fn pointer() -> Option<(f64, f64)> {
    crate::macos::pointer()
}
#[cfg(target_os = "macos")]
fn warp(x: f64, y: f64) {
    crate::macos::warp_pointer(x, y);
}

#[cfg(not(target_os = "macos"))]
fn front_pid() -> Option<i32> {
    None
}
#[cfg(not(target_os = "macos"))]
fn give_front(_pid: i32) {}
#[cfg(not(target_os = "macos"))]
fn pointer() -> Option<(f64, f64)> {
    None
}
#[cfg(not(target_os = "macos"))]
fn warp(_x: f64, _y: f64) {}

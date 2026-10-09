//! Late give-back (spec 2026-10-08-0157 §5, O1; found by the P2-5 smoke on 2026-10-10): some
//! apps bring themselves forward a moment AFTER an action has answered. Notes on New Note came
//! forward ~50 ms after the press returned, so the check at the action's end (`front_back`) saw
//! nothing, and Notes stayed in front of the user's app. After each background action a watcher
//! looks a little longer and gives the front back the same way, unless something says the
//! change is not Hands' doing: the user touched the keyboard or mouse, another action started
//! (a borrow among them), a takeover is on, or the front went to some other app.

use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

pub const WATCH_FOR: Duration = Duration::from_millis(600);
const EVERY: Duration = Duration::from_millis(15);

/// Every action start moves this; a watcher stops when it moved past its own number.
static ACTIONS: AtomicU64 = AtomicU64::new(0);
/// How many times a watcher gave the front back (reported in `status`).
static GIVEN_BACK: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, PartialEq, Eq)]
pub enum Next {
    Wait,
    GiveBack,
    Leave,
}

/// What a watcher does at one look: `before` had the front when the action began, `now` has it,
/// `acted_on` is the app the action was for.
pub fn decide(
    before: i32,
    now: Option<i32>,
    acted_on: i64,
    user_moved: bool,
    newer_action: bool,
) -> Next {
    if newer_action || user_moved {
        return Next::Leave;
    }
    match now {
        Some(now) if now == before => Next::Wait,
        Some(now) if i64::from(now) == acted_on => Next::GiveBack,
        Some(_) => Next::Leave, // something else took the front: not ours to undo
        None => Next::Wait,
    }
}

/// An action begins (before its own front check).
pub fn action_begins() {
    ACTIONS.fetch_add(1, Ordering::SeqCst);
}

pub fn given_back() -> u64 {
    GIVEN_BACK.load(Ordering::SeqCst)
}

/// After a background action answered: watch for `WATCH_FOR` on a thread of its own.
pub fn watch(before: Option<i32>, acted_on: i64) {
    let Some(before) = before else { return };
    let me = ACTIONS.load(Ordering::SeqCst);
    let started = Instant::now();
    std::thread::spawn(move || {
        while started.elapsed() < WATCH_FOR {
            std::thread::sleep(EVERY);
            let newer = ACTIONS.load(Ordering::SeqCst) != me || crate::takeover::active();
            let window = started.elapsed().as_millis() as f64;
            let moved = crate::keyhold::user_key_age_ms().is_some_and(|ms| ms < window)
                || crate::keyhold::user_mouse_age_ms().is_some_and(|ms| ms < window);
            match decide(before, front(), acted_on, moved, newer) {
                Next::Wait => continue,
                Next::Leave => return,
                Next::GiveBack => {
                    if give_back(before) {
                        GIVEN_BACK.fetch_add(1, Ordering::SeqCst);
                    }
                    return;
                }
            }
        }
    });
}

#[cfg(target_os = "macos")]
fn front() -> Option<i32> {
    crate::macos::frontmost_pid()
}

#[cfg(not(target_os = "macos"))]
fn front() -> Option<i32> {
    None
}

#[cfg(target_os = "macos")]
fn give_back(pid: i32) -> bool {
    crate::macos::give_front_back(pid)
}

#[cfg(not(target_os = "macos"))]
fn give_back(_pid: i32) -> bool {
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_app_acted_on_coming_forward_late_is_given_back() {
        assert_eq!(decide(10, Some(20), 20, false, false), Next::GiveBack);
    }

    #[test]
    fn nothing_changed_yet_waits() {
        assert_eq!(decide(10, Some(10), 20, false, false), Next::Wait);
        assert_eq!(decide(10, None, 20, false, false), Next::Wait);
    }

    #[test]
    fn the_user_another_action_or_another_app_is_left_alone() {
        assert_eq!(
            decide(10, Some(20), 20, true, false),
            Next::Leave,
            "the user moved"
        );
        assert_eq!(
            decide(10, Some(20), 20, false, true),
            Next::Leave,
            "a newer action (a borrow)"
        );
        assert_eq!(
            decide(10, Some(30), 20, false, false),
            Next::Leave,
            "some other app"
        );
    }
}

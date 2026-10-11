//! Going to the window (spec 2026-10-08-0157 §15 A18): when an app's windows are all on another
//! desktop, accessibility (and so Hands) cannot see them. Hands goes there — under the borrow
//! rules, because it is the same act at a longer scale — does the steps of that piece of work,
//! and comes back:
//!
//! - going: wait for the user's typing pause, never during secure input, glow on, the user's keys
//!   held, the front app and the pointer noted (all `borrow::begin`); then activate the app, and
//!   macOS switches to its desktop;
//! - staying: every step on that app keeps the visit going; a step on another app comes back first;
//! - coming back at the first of: the work that went there ends (the backend's `visit_end`), the
//!   user presses a key or moves or clicks the mouse, `IDLE` without a step, `MAX` in all, the
//!   screen locks, Stop. First the desktops (`come_back`): the user's front app again — activated
//!   whatever NSWorkspace's copy of the front says at the end — and every window that was on screen
//!   before on screen again; then `borrow::end`: the pointer if Hands moved it,
//!   the held keys (into the user's own window), glow off.
//!
//! The key hold has its own short deadline (`borrow::HOLD_MAX`); while a visit lasts the watcher
//! renews it, and the first key the user presses ends the visit and is replayed into their window.

use crate::argv::{refuse, Refusal};
use serde_json::{json, Value};
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

/// Come back after this long with no Hands step on the app (the work may be thinking between
/// steps; the backend ends the visit when the work ends, this is the backstop).
pub const IDLE: Duration = Duration::from_secs(15);
/// Come back after this long in all, whatever happens.
pub const MAX: Duration = Duration::from_secs(10 * 60);
const WATCH_EVERY: Duration = Duration::from_millis(20);
const REARM_EVERY: Duration = Duration::from_secs(5);
/// How long to wait, after activating the app, for its window to become visible.
const VISIBLE_WAIT: Duration = Duration::from_secs(2);

struct Visit {
    pid: i64,
    app: String,
    borrowed: Option<crate::borrow::Borrowed>,
    since: Instant,
    last_step: Instant,
    /// The user's front app when the visit began (NSWorkspace, else accessibility).
    front: Option<i32>,
    /// The windows on screen when the visit began (other than the visited app's): (number, pid).
    shown_before: Vec<(u32, i32)>,
}

static STATE: Mutex<Option<Visit>> = Mutex::new(None);
/// Each visit's watcher knows its number; a newer visit (or an end) retires it.
static WATCHER: AtomicU64 = AtomicU64::new(0);
/// How the last visit ended, for the island and the backend.
static LAST: Mutex<Option<Value>> = Mutex::new(None);
/// The app Hands is about to go to while it waits for the user's pause (the island says where).
static GOING: Mutex<Option<String>> = Mutex::new(None);

// Tests run Hands in-process: no activation, no glow, no key tap (the borrow's stand-in covers
// those); `user_touch_for_tests` stands in for the user, `idle_for_tests` for time passing.
static STAND_IN: AtomicBool = AtomicBool::new(false);
static VISITS: AtomicUsize = AtomicUsize::new(0);
static TOUCHED: AtomicBool = AtomicBool::new(false);

pub fn stand_in_for_tests(on: bool) {
    STAND_IN.store(on, Ordering::SeqCst);
    VISITS.store(0, Ordering::SeqCst);
    TOUCHED.store(false, Ordering::SeqCst);
    *lock() = None;
    *LAST.lock().unwrap_or_else(|p| p.into_inner()) = None;
    WATCHER.fetch_add(1, Ordering::SeqCst);
}

/// How many visits began since `stand_in_for_tests`.
pub fn visits_for_tests() -> usize {
    VISITS.load(Ordering::SeqCst)
}

/// In tests: the user touches the keyboard or mouse.
pub fn user_touch_for_tests() {
    TOUCHED.store(true, Ordering::SeqCst);
}

/// In tests: no step for longer than `IDLE`.
pub fn idle_for_tests() {
    if let Some(visit) = lock().as_mut() {
        visit.last_step = Instant::now() - IDLE - Duration::from_millis(1);
    }
}

fn lock() -> std::sync::MutexGuard<'static, Option<Visit>> {
    STATE.lock().unwrap_or_else(|p| p.into_inner())
}

fn standing_in() -> bool {
    STAND_IN.load(Ordering::SeqCst)
}

/// Why a visit ends now, or None to stay.
pub fn decide(
    elapsed: Duration,
    idle: Duration,
    user_moved: bool,
    locked: bool,
) -> Option<&'static str> {
    if user_moved {
        Some("user")
    } else if locked {
        Some("locked")
    } else if elapsed >= MAX {
        Some("max")
    } else if idle >= IDLE {
        Some("idle")
    } else {
        None
    }
}

/// The app being visited, if any.
pub fn active_pid() -> Option<i64> {
    lock().as_ref().map(|v| v.pid)
}

pub fn active_for(pid: i64) -> bool {
    active_pid() == Some(pid)
}

/// A step on the visited app: the visit goes on.
pub fn touch() {
    if let Some(visit) = lock().as_mut() {
        visit.last_step = Instant::now();
    }
}

/// Go to app `pid`'s desktop. `visible` says whether its window can be seen yet (after the
/// activation, macOS switches desktops); `stopped` whether the user pressed Stop while Hands
/// waited for their pause.
pub fn begin(
    pid: i64,
    app: &str,
    wait_max: Duration,
    stopped: impl Fn() -> bool,
    visible: impl Fn() -> bool,
) -> Result<(), Refusal> {
    end("replaced");
    *GOING.lock().unwrap_or_else(|p| p.into_inner()) = Some(app.to_string());
    let borrowed = crate::borrow::begin(wait_max, stopped);
    *GOING.lock().unwrap_or_else(|p| p.into_inner()) = None;
    let mut borrowed = borrowed?;
    // Where the user is, noted now (after their pause, before anything moves): coming back is
    // checked against it.
    let (front, shown_before) = if standing_in() {
        (None, Vec::new())
    } else {
        let front = borrowed.front().or_else(focused_app);
        borrowed.set_front(front);
        let shown = crate::spaces::shown()
            .unwrap_or_default()
            .into_iter()
            .filter(|(_, owner)| i64::from(*owner) != pid)
            .collect();
        (front, shown)
    };
    if !standing_in() {
        if let Ok(pid) = i32::try_from(pid) {
            activate(pid);
        }
        let until = Instant::now() + VISIBLE_WAIT;
        while !visible() && Instant::now() < until {
            std::thread::sleep(Duration::from_millis(50));
        }
        if !visible() {
            come_back(&shown_before, front);
            let _ = crate::borrow::end(borrowed);
            return Err(refuse(
                "window_unreachable",
                format!(
                    "Arslan switched to {app}, but macOS did not show its window on this desktop"
                ),
            ));
        }
    }
    VISITS.fetch_add(1, Ordering::SeqCst);
    let now = Instant::now();
    *lock() = Some(Visit {
        pid,
        app: app.to_string(),
        borrowed: Some(borrowed),
        since: now,
        last_step: now,
        front,
        shown_before,
    });
    let me = WATCHER.fetch_add(1, Ordering::SeqCst) + 1;
    std::thread::spawn(move || watch(me));
    Ok(())
}

fn watch(me: u64) {
    let mut rearmed = Instant::now();
    loop {
        std::thread::sleep(WATCH_EVERY);
        if WATCHER.load(Ordering::SeqCst) != me {
            return;
        }
        let (elapsed, idle) = match lock().as_ref() {
            Some(visit) => (visit.since.elapsed(), visit.last_step.elapsed()),
            None => return,
        };
        if let Some(reason) = decide(elapsed, idle, user_input_within(elapsed), screen_locked()) {
            end(reason);
            return;
        }
        if !standing_in() && rearmed.elapsed() >= REARM_EVERY {
            // The hold's own deadline is short by design; renewed only while a visit lasts.
            crate::keyhold::arm(crate::borrow::HOLD_MAX);
            rearmed = Instant::now();
        }
    }
}

/// Did the user press a key or move or click the mouse in the last `window`? (Hands' own events,
/// and agent-desktop's, never count: the key tap tells them apart.)
fn user_input_within(window: Duration) -> bool {
    if standing_in() {
        return TOUCHED.swap(false, Ordering::SeqCst);
    }
    let window = window.as_millis() as f64;
    crate::keyhold::user_key_age_ms().is_some_and(|ms| ms < window)
        || crate::keyhold::user_mouse_age_ms().is_some_and(|ms| ms < window)
}

/// Come back (see the module doc). Returns what the borrow gave back, if a visit was going on.
pub fn end(reason: &str) -> Option<crate::borrow::GaveBack> {
    let visit = lock().take()?;
    WATCHER.fetch_add(1, Ordering::SeqCst);
    // The desktops first, so the keys the user pressed meanwhile reach their own window.
    let desktops_restored = standing_in() || come_back(&visit.shown_before, visit.front);
    let gave = visit.borrowed.map(crate::borrow::end);
    let front_restored = if standing_in() {
        gave.map(|g| g.front_restored)
    } else {
        Some(visit.front.is_none() || front_now() == visit.front)
    };
    *LAST.lock().unwrap_or_else(|p| p.into_inner()) = Some(json!({
        "app": visit.app,
        "reason": reason,
        "lasted_ms": visit.since.elapsed().as_millis() as u64,
        "front_restored": front_restored,
        "desktops_restored": desktops_restored,
        "keys_replayed": gave.map(|g| g.keys_replayed),
    }));
    gave
}

/// Back to where the user was: their front app again (macOS switches back to its desktop), then
/// every window that was on screen before the visit on screen again. A desktop that did not switch
/// back — the front app has a window on the visited desktop too, or the visit was on another
/// display — is brought back through the app of its front-most window that is missing, and then
/// the front app once more. Whether every window came back.
fn come_back(before: &[(u32, i32)], front: Option<i32>) -> bool {
    if let Some(front) = front {
        activate(front);
    }
    if back_within(before, Duration::from_millis(1200)) {
        return true;
    }
    if let Some(&(_, owner)) = missing_now(before).first() {
        activate(owner);
        let _ = back_within(before, Duration::from_millis(800));
        if let Some(front) = front {
            activate(front);
        }
    }
    back_within(before, Duration::from_millis(600))
}

fn missing_now(before: &[(u32, i32)]) -> Vec<(u32, i32)> {
    let shown: Vec<u32> = crate::spaces::shown()
        .unwrap_or_default()
        .iter()
        .map(|(n, _)| *n)
        .collect();
    if before.iter().all(|(n, _)| shown.contains(n)) {
        return Vec::new();
    }
    crate::spaces::missing(
        before,
        &shown,
        crate::spaces::ordered_in_everywhere().as_deref(),
    )
}

fn back_within(before: &[(u32, i32)], wait: Duration) -> bool {
    let until = Instant::now() + wait;
    loop {
        if missing_now(before).is_empty() {
            return true;
        }
        if Instant::now() >= until {
            return false;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
}

/// For the island and the backend: the visit going on, and how the last one ended.
pub fn status() -> Value {
    let last = LAST.lock().unwrap_or_else(|p| p.into_inner()).clone();
    match lock().as_ref() {
        Some(visit) => json!({
            "active": true,
            "app": visit.app,
            "since_s": visit.since.elapsed().as_secs(),
            "last": last,
        }),
        None => json!({
            "active": false,
            "going": GOING.lock().unwrap_or_else(|p| p.into_inner()).clone(),
            "last": last,
        }),
    }
}

#[cfg(target_os = "macos")]
fn activate(pid: i32) {
    crate::macos::give_front_back(pid);
}

#[cfg(not(target_os = "macos"))]
fn activate(_pid: i32) {}

#[cfg(target_os = "macos")]
fn focused_app() -> Option<i32> {
    crate::macos::focused_app_pid()
}

/// The app in front now, the way the visit noted it: NSWorkspace, else accessibility (which
/// cannot answer for some apps: kAXErrorCannotComplete with Codex in front, measured).
#[cfg(target_os = "macos")]
fn front_now() -> Option<i32> {
    crate::macos::frontmost_pid().or_else(focused_app)
}

#[cfg(not(target_os = "macos"))]
fn front_now() -> Option<i32> {
    None
}

#[cfg(not(target_os = "macos"))]
fn focused_app() -> Option<i32> {
    None
}

fn screen_locked() -> bool {
    if standing_in() {
        return false;
    }
    #[cfg(target_os = "macos")]
    {
        crate::macos::screen_locked()
    }
    #[cfg(not(target_os = "macos"))]
    {
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_user_comes_first_then_the_lock_the_cap_and_idle() {
        let s = Duration::from_secs;
        assert_eq!(decide(s(1), s(1), true, false), Some("user"));
        assert_eq!(decide(s(1), s(1), true, true), Some("user"));
        assert_eq!(decide(s(1), s(1), false, true), Some("locked"));
        assert_eq!(decide(MAX, s(1), false, false), Some("max"));
        assert_eq!(decide(s(30), IDLE, false, false), Some("idle"));
    }

    #[test]
    fn a_visit_with_steps_coming_stays() {
        let s = Duration::from_secs;
        assert_eq!(decide(s(120), s(3), false, false), None);
        assert_eq!(decide(s(0), s(0), false, false), None);
    }
}

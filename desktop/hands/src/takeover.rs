//! Takeover (spec 2026-10-08-0157 §6.4): after the user's yes on a card, a background job may
//! use the screen in front for up to 30 minutes. The edge glow stays on; a watcher checks the
//! user's keyboard and mouse every 20 ms (the key tap's own watch: Hands' events never count),
//! and the moment the user touches either, whatever Hands is running is ended and the takeover
//! pauses — nothing more is sent until the user says continue. It ends when the job ends, the
//! time is up, or on Stop.

use crate::argv::{refuse, Refusal};
use serde_json::{json, Value};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

pub const MAX_MINUTES: u64 = 30;
const WATCH_EVERY: Duration = Duration::from_millis(20);

struct Takeover {
    until: Instant,
    /// Input before this moment is not the user stopping the takeover (they clicked Allow).
    since: Instant,
    paused: bool,
}

static STATE: Mutex<Option<Takeover>> = Mutex::new(None);
/// Each takeover's watcher knows its own number; a newer takeover's watcher replaces it.
static WATCHER: AtomicU64 = AtomicU64::new(0);

// Tests run Hands in-process: no glow, no key tap; `touch_for_tests` stands in for the user.
static STAND_IN: AtomicBool = AtomicBool::new(false);
static TOUCHED: AtomicBool = AtomicBool::new(false);

pub fn stand_in_for_tests(on: bool) {
    STAND_IN.store(on, Ordering::SeqCst);
    TOUCHED.store(false, Ordering::SeqCst);
    *lock() = None;
}

/// In tests: the user touches the keyboard or mouse.
pub fn touch_for_tests() {
    TOUCHED.store(true, Ordering::SeqCst);
}

/// In tests: the takeover's time is up.
pub fn expire_for_tests() {
    if let Some(t) = lock().as_mut() {
        t.until = Instant::now();
    }
}

fn lock() -> std::sync::MutexGuard<'static, Option<Takeover>> {
    STATE.lock().unwrap_or_else(|p| p.into_inner())
}

fn standing_in() -> bool {
    STAND_IN.load(Ordering::SeqCst)
}

/// Did the user press a key or move / click the mouse since `since`?
fn user_input_since(since: Instant) -> bool {
    if standing_in() {
        return TOUCHED.swap(false, Ordering::SeqCst);
    }
    let window = since.elapsed().as_millis() as f64;
    crate::keyhold::user_key_age_ms().is_some_and(|ms| ms < window)
        || crate::keyhold::user_mouse_age_ms().is_some_and(|ms| ms < window)
}

/// Begin (or extend) a takeover of `minutes` (1 to 30).
pub fn begin(minutes: u64) -> Result<Value, Refusal> {
    if !(1..=MAX_MINUTES).contains(&minutes) {
        return Err(refuse("bad_request", "`minutes` is 1 to 30"));
    }
    if !standing_in() && crate::keyhold::start().is_err() {
        return Err(refuse(
            "takeover_unsafe",
            "Hands cannot watch the keyboard and mouse, so it cannot stop when the user moves: no takeover",
        ));
    }
    let now = Instant::now();
    *lock() = Some(Takeover {
        until: now + Duration::from_secs(minutes * 60),
        since: now,
        paused: false,
    });
    if !standing_in() {
        crate::glow::show();
    }
    let me = WATCHER.fetch_add(1, Ordering::SeqCst) + 1;
    std::thread::spawn(move || watch(me));
    Ok(status())
}

/// The watcher: the user's input pauses the takeover at once and ends what Hands is running;
/// the end of the time ends it.
fn watch(me: u64) {
    loop {
        std::thread::sleep(WATCH_EVERY);
        if WATCHER.load(Ordering::SeqCst) != me {
            return;
        }
        let mut state = lock();
        let Some(t) = state.as_mut() else { return };
        if Instant::now() >= t.until {
            *state = None;
            drop(state);
            if !standing_in() {
                crate::glow::hide();
            }
            return;
        }
        if !t.paused && user_input_since(t.since) {
            t.paused = true;
            drop(state);
            // Whatever is in flight ends now (the reply says paused, not stopped).
            crate::runner::kill_all();
        }
    }
}

/// End the takeover (the job is done, the user said stop, or Stop). Whether one was running.
pub fn end() -> bool {
    let was = lock().take().is_some();
    WATCHER.fetch_add(1, Ordering::SeqCst);
    if was && !standing_in() {
        crate::glow::hide();
    }
    was
}

/// The user said continue: input from now on pauses it again.
pub fn resume() -> Result<Value, Refusal> {
    let mut state = lock();
    match state.as_mut() {
        Some(t) if t.paused => {
            t.paused = false;
            t.since = Instant::now();
            drop(state);
            Ok(status())
        }
        Some(_) => Err(refuse("not_paused", "the takeover is not paused")),
        None => Err(refuse("no_takeover", "there is no takeover to continue")),
    }
}

pub fn paused() -> bool {
    lock().as_ref().is_some_and(|t| t.paused)
}

pub fn status() -> Value {
    match lock().as_ref() {
        Some(t) => json!({
            "active": true,
            "paused": t.paused,
            "remaining_s": t.until.saturating_duration_since(Instant::now()).as_secs(),
        }),
        None => json!({"active": false}),
    }
}

/// Before every action: Ok(true) inside a running takeover (the action may use the front, no
/// borrow needed), Ok(false) outside one, Err while paused (nothing is sent until continue).
pub fn check_before_action() -> Result<bool, Refusal> {
    let mut state = lock();
    match state.as_ref() {
        None => Ok(false),
        Some(t) if Instant::now() >= t.until => {
            *state = None;
            Ok(false)
        }
        Some(t) if t.paused => Err(paused_refusal()),
        Some(_) => Ok(true),
    }
}

pub fn paused_refusal() -> Refusal {
    refuse(
        "takeover_paused",
        "the user touched the keyboard or mouse, so the takeover paused; nothing more is sent until they say continue",
    )
}

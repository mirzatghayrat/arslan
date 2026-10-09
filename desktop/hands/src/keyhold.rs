//! The key hold (spec 2026-10-08-0157 §6.3 step 4, Q2): the Rust side of src/keyhold.m. While
//! Hands borrows the front, the user's key events are held in order and replayed afterwards; their
//! mouse is only watched. Hands' own events, its children's (agent-desktop) and its replays pass.

use serde_json::Value;

#[cfg(target_os = "macos")]
mod ffi {
    use std::ffi::c_char;
    extern "C" {
        pub fn hands_keyhold_start() -> i32;
        pub fn hands_keyhold_arm(max_ms: f64);
        pub fn hands_keyhold_release() -> i32;
        pub fn hands_keyhold_user_key_age_ms() -> f64;
        pub fn hands_keyhold_user_mouse_age_ms() -> f64;
        pub fn hands_keyhold_secure_input() -> bool;
        pub fn hands_keyhold_probe() -> *mut c_char;
        pub fn hands_keyhold_free(text: *mut c_char);
    }
}

/// Start the tap (once). Err when macOS would not create it (no permission for it).
#[cfg(target_os = "macos")]
pub fn start() -> Result<(), &'static str> {
    // SAFETY: no arguments; idempotent in keyhold.m.
    match unsafe { ffi::hands_keyhold_start() } {
        0 => Ok(()),
        _ => Err("the key tap could not be created"),
    }
}

/// Hold the user's key events from now on, for at most `max`: past it the tap's own thread
/// gives them back, whatever the rest of Hands is doing.
#[cfg(target_os = "macos")]
pub fn arm(max: std::time::Duration) {
    // SAFETY: a plain number.
    unsafe { ffi::hands_keyhold_arm(max.as_secs_f64() * 1000.0) }
}

/// Replay what was held, in order, and stop holding. How many were replayed.
#[cfg(target_os = "macos")]
pub fn release() -> usize {
    // SAFETY: no arguments.
    unsafe { ffi::hands_keyhold_release() }.max(0) as usize
}

/// Milliseconds since the user's last key / mouse event; None before the tap saw one.
#[cfg(target_os = "macos")]
pub fn user_key_age_ms() -> Option<f64> {
    // SAFETY: no arguments.
    Some(unsafe { ffi::hands_keyhold_user_key_age_ms() }).filter(|ms| *ms >= 0.0)
}

#[cfg(target_os = "macos")]
pub fn user_mouse_age_ms() -> Option<f64> {
    // SAFETY: no arguments.
    Some(unsafe { ffi::hands_keyhold_user_mouse_age_ms() }).filter(|ms| *ms >= 0.0)
}

/// The user is typing into a password field (macOS' secure input): keys cannot be held then.
#[cfg(target_os = "macos")]
pub fn secure_input() -> bool {
    // SAFETY: no arguments.
    unsafe { ffi::hands_keyhold_secure_input() }
}

/// What the tap has seen, for the Q2 probe (event types and source pids, never keys).
#[cfg(target_os = "macos")]
pub fn probe() -> Value {
    // SAFETY: a malloc'd NUL-terminated string, freed right after copying.
    unsafe {
        let raw = ffi::hands_keyhold_probe();
        if raw.is_null() {
            return Value::Null;
        }
        let text = std::ffi::CStr::from_ptr(raw).to_string_lossy().into_owned();
        ffi::hands_keyhold_free(raw);
        serde_json::from_str(&text).unwrap_or(Value::Null)
    }
}

#[cfg(not(target_os = "macos"))]
pub fn start() -> Result<(), &'static str> {
    Err("the key hold exists only on macOS")
}
#[cfg(not(target_os = "macos"))]
pub fn arm(_max: std::time::Duration) {}
#[cfg(not(target_os = "macos"))]
pub fn release() -> usize {
    0
}
#[cfg(not(target_os = "macos"))]
pub fn user_key_age_ms() -> Option<f64> {
    None
}
#[cfg(not(target_os = "macos"))]
pub fn user_mouse_age_ms() -> Option<f64> {
    None
}
#[cfg(not(target_os = "macos"))]
pub fn secure_input() -> bool {
    false
}
#[cfg(not(target_os = "macos"))]
pub fn probe() -> Value {
    Value::Null
}

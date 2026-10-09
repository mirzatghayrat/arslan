//! One window's screenshot (Hands v2, spec 2026-10-08-0157 §4.2 and §15 A8): the Rust side of
//! src/capture.m. The image never touches the disk; it goes back in the reply, base64.

use serde_json::Value;

/// Long edge of a screenshot, in pixels (§4.2).
pub const MAX_EDGE: i32 = 1280;

#[cfg(target_os = "macos")]
mod ffi {
    use std::ffi::c_char;
    extern "C" {
        pub fn hands_capture(pid: i32, window_id: u32, max_edge: i32) -> *mut c_char;
        pub fn hands_capture_free(json: *mut c_char);
    }
}

/// The window `window_id` of `pid` (0: its frontmost window) as JSON: `ok`, `window_id`,
/// `title`, `onscreen`, `frame` (points), `scale` (pixels per point), `width`, `height`, `mime`, `data`;
/// or `ok: false` with a `code` and `message`.
#[cfg(target_os = "macos")]
pub fn window(pid: i32, window_id: u32) -> Value {
    // SAFETY: hands_capture returns a NUL-terminated, malloc'd UTF-8 string (or NULL), freed
    // below with hands_capture_free; nothing else holds it.
    unsafe {
        let raw = ffi::hands_capture(pid, window_id, MAX_EDGE);
        if raw.is_null() {
            return failed("capture_failed", "no answer from the capture");
        }
        let text = std::ffi::CStr::from_ptr(raw).to_string_lossy().into_owned();
        ffi::hands_capture_free(raw);
        serde_json::from_str(&text)
            .unwrap_or_else(|_| failed("capture_failed", "unreadable answer"))
    }
}

#[cfg(not(target_os = "macos"))]
pub fn window(_pid: i32, _window_id: u32) -> Value {
    failed("not_supported", "window screenshots exist only on macOS")
}

fn failed(code: &str, message: &str) -> Value {
    serde_json::json!({"ok": false, "code": code, "message": message})
}

/// A window id as callers give it: agent-desktop's `w-26104`, or the number itself.
pub fn window_id(given: &Value) -> Option<u32> {
    match given {
        Value::Null => Some(0),
        Value::Number(n) => n
            .as_u64()
            .and_then(|n| u32::try_from(n).ok())
            .filter(|n| *n > 0),
        Value::String(s) => s
            .strip_prefix("w-")
            .unwrap_or(s)
            .parse()
            .ok()
            .filter(|n| *n > 0),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn window_ids_are_agent_desktops_or_numbers() {
        assert_eq!(window_id(&Value::Null), Some(0));
        assert_eq!(window_id(&json!("w-26104")), Some(26104));
        assert_eq!(window_id(&json!(26104)), Some(26104));
        for bad in [
            json!("w-"),
            json!("w-x1"),
            json!(0),
            json!(-3),
            json!("0"),
            json!([1]),
        ] {
            assert_eq!(window_id(&bad), None, "{bad}");
        }
    }
}

//! Resident mode (0.1.41): closing the main window hides it and Arslan keeps
//! working from the menu bar. Explicit quits — ⌘Q, the app menu, the menu-bar
//! "Quit Arslan", logout, an update restart — still stop the backend exactly
//! as before (see the RunEvent handler in lib.rs).
//!
//! The shell learns what is going on from one narrow, authenticated loopback
//! endpoint (`GET /api/v1/desktop/status`) and uses it for three things only:
//! the menu-bar status line, a sleep assertion while work is in flight, and
//! native notifications while the window is not in front. Nothing here
//! approves, starts or cancels work; a confirmation card still waits for the
//! user in the window, with its existing timeout.

use serde::Deserialize;
use std::io::{Read, Write};
use std::time::Duration;
use tauri::Manager;

use crate::native_locale;

pub const TRAY_ID: &str = "arslan";
pub const MENU_OPEN: &str = "tray-open";
pub const MENU_QUIT: &str = "tray-quit";
pub const MENU_STATUS: &str = "tray-status";
/// Emitted to the main webview when a notification is clicked.
pub const OPEN_CONVERSATION_EVENT: &str = "open-conversation";
const POLL_EVERY: Duration = Duration::from_secs(2);
/// Consecutive failed polls after which a held sleep assertion is dropped:
/// a backend that cannot be reached cannot be doing work worth staying up for.
const RELEASE_AFTER_FAILURES: u32 = 3;

// ── pure decisions (unit-tested) ─────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CloseAction {
    /// Hide the window; the backend keeps running.
    Hide,
    /// Let the window close as it always did.
    Close,
}

/// Only the main window hides. The launch screen and recovery windows close
/// normally, so a failed boot still quits when its window is closed.
pub fn close_action(label: &str) -> CloseAction {
    if label == crate::MAIN_LABEL {
        CloseAction::Hide
    } else {
        CloseAction::Close
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq, Deserialize)]
pub struct Event {
    pub id: u64,
    pub kind: String,
    #[serde(default)]
    pub conversation_id: Option<String>,
    #[serde(default)]
    pub outcome: Option<String>,
    #[serde(default)]
    pub task_name: Option<String>,
}

#[derive(Debug, Default, Clone, PartialEq, Eq, Deserialize)]
pub struct Status {
    #[serde(default)]
    pub cursor: u64,
    #[serde(default)]
    pub working: u32,
    #[serde(default)]
    pub awaiting: u32,
    #[serde(default)]
    pub events: Vec<Event>,
    /// Missing means OFF: never hold the Mac awake on a malformed answer.
    #[serde(default)]
    pub keep_awake: bool,
    #[serde(default)]
    pub notifications: bool,
}

/// Hold a sleep assertion only while work is actually in flight and the user
/// has not turned it off. Waiting for a confirmation is not work.
pub fn want_sleep_assertion(status: &Status) -> bool {
    status.keep_awake && status.working > 0
}

/// Notify only when the user cannot already see the window.
pub fn should_notify(enabled: bool, window_visible: bool, window_focused: bool) -> bool {
    enabled && !(window_visible && window_focused)
}

/// The events not seen yet. The first poll adopts the backend's history
/// without notifying. A backend whose cursor went BACKWARDS was restarted:
/// its ids start over, so everything it holds happened after the restart and
/// is new — filtering by the old cursor would silently drop all of it.
pub fn fresh_events(previous: Option<u64>, status: &Status) -> Vec<&Event> {
    match previous {
        None => Vec::new(),
        Some(seen) if status.cursor < seen => status.events.iter().collect(),
        Some(seen) => status.events.iter().filter(|e| e.id > seen).collect(),
    }
}

pub fn status_line(locale: &str, status: &Status, holding_sleep: bool) -> String {
    let mut line = if status.awaiting > 0 {
        native_locale::text(locale, "tray_awaiting").replace("{n}", &status.awaiting.to_string())
    } else if status.working > 0 {
        native_locale::text(locale, "tray_working").replace("{n}", &status.working.to_string())
    } else {
        native_locale::text(locale, "tray_idle")
    };
    if holding_sleep {
        line.push_str(" · ");
        line.push_str(&native_locale::text(locale, "tray_keeping_awake"));
    }
    line
}

/// Title and body for one event, or None when it should not notify. Text is
/// only ever a fixed phrase plus a scheduled task's user-chosen name: a
/// notification can be read on a locked screen, so no message content.
pub fn notification(locale: &str, event: &Event) -> Option<(String, String)> {
    let key = match (event.kind.as_str(), event.outcome.as_deref()) {
        ("turn_finished", Some("ok")) => "notify_done",
        ("turn_finished", Some("error" | "needs_review")) => "notify_attention",
        ("approval_needed", _) => "notify_approval",
        ("scheduled_finished", Some("ok")) => "notify_scheduled_done",
        ("scheduled_finished", Some("error")) => "notify_scheduled_failed",
        ("scheduled_paused", _) => "notify_scheduled_paused",
        _ => return None,
    };
    let name = event.task_name.as_deref().unwrap_or("");
    Some((
        native_locale::text(locale, &format!("{key}_title")),
        native_locale::text(locale, &format!("{key}_body")).replace("{name}", name),
    ))
}

/// Parse a raw HTTP/1.1 response from the status endpoint.
pub fn parse_response(raw: &str) -> Option<Status> {
    if !(raw.starts_with("HTTP/1.1 200") || raw.starts_with("HTTP/1.0 200")) {
        return None;
    }
    let (_, body) = raw.split_once("\r\n\r\n")?;
    serde_json::from_str(body).ok()
}

/// A notification's identifier carries the conversation to open on click.
pub fn notification_id(event: &Event) -> String {
    format!(
        "arslan|{}|{}",
        event.id,
        event.conversation_id.as_deref().unwrap_or("")
    )
}

pub fn conversation_from_id(identifier: &str) -> Option<String> {
    let mut parts = identifier.splitn(3, '|');
    if parts.next()? != "arslan" {
        return None;
    }
    parts.next()?.parse::<u64>().ok()?;
    Some(parts.next()?.to_string()).filter(|cid| !cid.is_empty())
}

// ── runtime ──────────────────────────────────────────────────────────────────

fn fetch_status(port: u16, token: Option<&str>, after: u64) -> Option<Status> {
    let addr = std::net::SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = std::net::TcpStream::connect_timeout(&addr, Duration::from_secs(1)).ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(3))).ok()?;
    let auth = token
        .map(|t| format!("Authorization: Bearer {t}\r\n"))
        .unwrap_or_default();
    let request = format!(
        "GET /api/v1/desktop/status?after={after} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n{auth}Connection: close\r\n\r\n"
    );
    stream.write_all(request.as_bytes()).ok()?;
    let mut raw = String::new();
    stream.read_to_string(&mut raw).ok()?;
    parse_response(&raw)
}

/// Show and focus the main window (Dock click, menu-bar "Open", notification click).
pub fn show_main(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window(crate::MAIN_LABEL) {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

pub struct TrayStatus(pub tauri::menu::MenuItem<tauri::Wry>);

/// Build the menu-bar item. Called once on the main thread during setup.
pub fn install_tray(app: &tauri::AppHandle) -> tauri::Result<()> {
    use tauri::menu::{MenuBuilder, MenuItem, PredefinedMenuItem};
    let locale = native_locale::selected();
    let status = MenuItem::with_id(
        app,
        MENU_STATUS,
        native_locale::text(locale, "tray_idle"),
        false,
        None::<&str>,
    )?;
    let open = MenuItem::with_id(
        app,
        MENU_OPEN,
        native_locale::text(locale, "tray_open"),
        true,
        None::<&str>,
    )?;
    let quit = MenuItem::with_id(
        app,
        MENU_QUIT,
        native_locale::text(locale, "tray_quit"),
        true,
        None::<&str>,
    )?;
    let menu = MenuBuilder::new(app)
        .item(&status)
        .item(&PredefinedMenuItem::separator(app)?)
        .item(&open)
        .item(&quit)
        .build()?;
    tauri::tray::TrayIconBuilder::with_id(TRAY_ID)
        .icon(tauri::image::Image::from_bytes(include_bytes!(
            "../icons/tray-template@2x.png"
        ))?)
        .icon_as_template(true)
        .tooltip("Arslan")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .build(app)?;
    app.manage(TrayStatus(status));
    Ok(())
}

/// Poll the backend for as long as the app lives. Started once the backend is up.
pub fn start(app: tauri::AppHandle, port: u16) {
    std::thread::spawn(move || {
        let token = crate::read_api_token();
        let mut cursor: Option<u64> = None;
        let mut failures = 0u32;
        let mut sleep = power::Assertion::default();
        loop {
            match fetch_status(port, token.as_deref(), cursor.unwrap_or(0)) {
                Some(status) => {
                    failures = 0;
                    let locale = native_locale::selected();
                    if status.notifications {
                        let window = app.get_webview_window(crate::MAIN_LABEL);
                        let visible = window
                            .as_ref()
                            .and_then(|w| w.is_visible().ok())
                            .unwrap_or(false);
                        let focused = window
                            .as_ref()
                            .and_then(|w| w.is_focused().ok())
                            .unwrap_or(false);
                        if should_notify(true, visible, focused) {
                            for event in fresh_events(cursor, &status) {
                                if let Some((title, body)) = notification(locale, event) {
                                    notify::post(&notification_id(event), &title, &body);
                                }
                            }
                        }
                    }
                    // Adopt the backend's cursor: history before we started, or
                    // before a backend restart, is never replayed.
                    cursor = Some(status.cursor);
                    sleep.hold(want_sleep_assertion(&status));
                    if let Some(item) = app.try_state::<TrayStatus>() {
                        let _ = item.0.set_text(status_line(locale, &status, sleep.held()));
                    }
                }
                None => {
                    failures += 1;
                    if failures >= RELEASE_AFTER_FAILURES {
                        sleep.hold(false);
                    }
                }
            }
            std::thread::sleep(POLL_EVERY);
        }
    });
}

// ── macOS: sleep assertion ───────────────────────────────────────────────────

pub mod power {
    /// One IOKit "prevent idle system sleep" assertion, held or not. Never
    /// prevents display sleep and never fights lid-close or battery sleep.
    #[derive(Default)]
    pub struct Assertion {
        #[allow(dead_code)]
        id: Option<u32>,
    }

    impl Assertion {
        pub fn held(&self) -> bool {
            self.id.is_some()
        }

        #[cfg(target_os = "macos")]
        pub fn hold(&mut self, want: bool) {
            match (want, self.id) {
                (true, None) => self.id = macos::create(),
                (false, Some(id)) => {
                    macos::release(id);
                    self.id = None;
                }
                _ => {}
            }
        }

        #[cfg(not(target_os = "macos"))]
        pub fn hold(&mut self, _want: bool) {}
    }

    impl Drop for Assertion {
        fn drop(&mut self) {
            self.hold(false);
        }
    }

    #[cfg(target_os = "macos")]
    mod macos {
        use std::ffi::{c_char, c_void, CString};

        type CFStringRef = *const c_void;
        const UTF8: u32 = 0x0800_0100;
        const LEVEL_ON: u32 = 255;

        #[link(name = "CoreFoundation", kind = "framework")]
        extern "C" {
            fn CFStringCreateWithCString(
                alloc: *const c_void,
                s: *const c_char,
                encoding: u32,
            ) -> CFStringRef;
            fn CFRelease(cf: *const c_void);
        }

        #[link(name = "IOKit", kind = "framework")]
        extern "C" {
            fn IOPMAssertionCreateWithName(
                kind: CFStringRef,
                level: u32,
                name: CFStringRef,
                id: *mut u32,
            ) -> i32;
            fn IOPMAssertionRelease(id: u32) -> i32;
        }

        fn cf(text: &str) -> CFStringRef {
            let c = CString::new(text).expect("static text has no NUL");
            // SAFETY: a valid NUL-terminated UTF-8 string; the caller releases it.
            unsafe { CFStringCreateWithCString(std::ptr::null(), c.as_ptr(), UTF8) }
        }

        pub fn create() -> Option<u32> {
            let kind = cf("PreventUserIdleSystemSleep");
            let name = cf("Arslan is finishing a task");
            let mut id = 0u32;
            // SAFETY: both CFStrings are valid for the call and released after it.
            let status = unsafe { IOPMAssertionCreateWithName(kind, LEVEL_ON, name, &mut id) };
            unsafe {
                CFRelease(kind);
                CFRelease(name);
            }
            (status == 0).then_some(id)
        }

        pub fn release(id: u32) {
            // SAFETY: id came from a successful IOPMAssertionCreateWithName.
            unsafe {
                IOPMAssertionRelease(id);
            }
        }
    }
}

// ── macOS: native notifications ──────────────────────────────────────────────

#[cfg(not(target_os = "macos"))]
pub mod notify {
    pub fn install(_app: &tauri::AppHandle) {}
    pub fn post(_id: &str, _title: &str, _body: &str) {}
}

#[cfg(target_os = "macos")]
pub mod notify {
    //! UNUserNotificationCenter through the objc2 runtime (already a
    //! dependency) and dynamic class lookup — no notification plugin. Only
    //! available to a bundled app: an unbundled dev binary has no bundle
    //! identifier and the center would raise, so notifications stay off there.

    use block2::{DynBlock, RcBlock};
    use objc2::rc::Retained;
    use objc2::runtime::{AnyClass, AnyObject, Bool, NSObject, NSObjectProtocol};
    use objc2::{define_class, msg_send, AnyThread};
    use std::ffi::{c_char, CStr, CString};
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::OnceLock;
    use tauri::Emitter;

    #[link(name = "UserNotifications", kind = "framework")]
    extern "C" {}

    static APP: OnceLock<tauri::AppHandle> = OnceLock::new();
    static READY: AtomicBool = AtomicBool::new(false);

    const ALERT_AND_SOUND: usize = (1 << 2) | (1 << 1);
    const PRESENT_BANNER_AND_LIST: usize = (1 << 4) | (1 << 3);

    define_class!(
        // SAFETY: NSObject has no subclassing requirements and this type has no Drop.
        #[unsafe(super(NSObject))]
        #[name = "ArslanNotificationDelegate"]
        struct Delegate;

        impl Delegate {
            #[unsafe(method(userNotificationCenter:didReceiveNotificationResponse:withCompletionHandler:))]
            fn did_receive(&self, _center: &AnyObject, response: &AnyObject, handler: &DynBlock<dyn Fn()>) {
                if let (Some(app), Some(identifier)) = (APP.get(), response_identifier(response)) {
                    super::show_main(app);
                    if let Some(cid) = super::conversation_from_id(&identifier) {
                        let _ = app.emit_to(crate::MAIN_LABEL, super::OPEN_CONVERSATION_EVENT, cid);
                    }
                }
                handler.call(());
            }

            // The app can be frontmost with its only window hidden; without this
            // macOS would swallow the banner exactly when it is needed.
            #[unsafe(method(userNotificationCenter:willPresentNotification:withCompletionHandler:))]
            fn will_present(&self, _center: &AnyObject, _notification: &AnyObject, handler: &DynBlock<dyn Fn(usize)>) {
                handler.call((PRESENT_BANNER_AND_LIST,));
            }
        }

        unsafe impl NSObjectProtocol for Delegate {}
    );

    fn string(value: &AnyObject) -> Option<String> {
        // SAFETY: `value` is an NSString; UTF8String is valid while it lives.
        let ptr: *const c_char = unsafe { msg_send![value, UTF8String] };
        (!ptr.is_null()).then(|| {
            unsafe { CStr::from_ptr(ptr) }
                .to_string_lossy()
                .into_owned()
        })
    }

    fn ns_string(text: &str) -> Option<Retained<AnyObject>> {
        let c = CString::new(text.replace('\0', "")).ok()?;
        let class = AnyClass::get(c"NSString")?;
        // SAFETY: stringWithUTF8String: copies a valid NUL-terminated string.
        unsafe { msg_send![class, stringWithUTF8String: c.as_ptr()] }
    }

    fn response_identifier(response: &AnyObject) -> Option<String> {
        // SAFETY: a UNNotificationResponse → notification → request → identifier chain.
        unsafe {
            let notification: Option<Retained<AnyObject>> = msg_send![response, notification];
            let request: Option<Retained<AnyObject>> = msg_send![&*notification?, request];
            let identifier: Option<Retained<AnyObject>> = msg_send![&*request?, identifier];
            identifier.as_deref().and_then(string)
        }
    }

    fn center() -> Option<Retained<AnyObject>> {
        let class = AnyClass::get(c"UNUserNotificationCenter")?;
        // SAFETY: class method returning the shared center (bundled apps only).
        unsafe { msg_send![class, currentNotificationCenter] }
    }

    fn bundled() -> bool {
        let Some(class) = AnyClass::get(c"NSBundle") else {
            return false;
        };
        // SAFETY: NSBundle.mainBundle.bundleIdentifier, nil when unbundled.
        unsafe {
            let bundle: Option<Retained<AnyObject>> = msg_send![class, mainBundle];
            let Some(bundle) = bundle else { return false };
            let identifier: Option<Retained<AnyObject>> = msg_send![&*bundle, bundleIdentifier];
            identifier.is_some()
        }
    }

    /// Main thread, once, during setup: install the click delegate and ask for
    /// permission. A refusal only means no banners; the menu bar still shows state.
    pub fn install(app: &tauri::AppHandle) {
        if !bundled() || APP.set(app.clone()).is_err() {
            return;
        }
        let Some(center) = center() else { return };
        let delegate: Retained<Delegate> = unsafe { msg_send![Delegate::alloc(), init] };
        // SAFETY: the center keeps a weak reference; the delegate is leaked on
        // purpose so it lives as long as the process.
        unsafe {
            let _: () = msg_send![&*center, setDelegate: &*delegate];
        }
        std::mem::forget(delegate);
        let done = RcBlock::new(|_granted: Bool, _error: *mut AnyObject| {});
        // SAFETY: documented selector; the block is copied by the callee.
        unsafe {
            let _: () = msg_send![&*center, requestAuthorizationWithOptions: ALERT_AND_SOUND, completionHandler: &*done];
        }
        READY.store(true, Ordering::SeqCst);
    }

    pub fn post(id: &str, title: &str, body: &str) {
        if !READY.load(Ordering::SeqCst) {
            return;
        }
        objc2::rc::autoreleasepool(|_| {
            let (Some(center), Some(content_class), Some(request_class)) = (
                center(),
                AnyClass::get(c"UNMutableNotificationContent"),
                AnyClass::get(c"UNNotificationRequest"),
            ) else {
                return;
            };
            let (Some(id), Some(title), Some(body)) =
                (ns_string(id), ns_string(title), ns_string(body))
            else {
                return;
            };
            // SAFETY: documented UserNotifications selectors with valid objects;
            // a nil trigger delivers immediately, a nil completion handler is allowed.
            unsafe {
                let content: Option<Retained<AnyObject>> = msg_send![content_class, new];
                let Some(content) = content else { return };
                let _: () = msg_send![&*content, setTitle: &*title];
                let _: () = msg_send![&*content, setBody: &*body];
                let request: Option<Retained<AnyObject>> = msg_send![
                    request_class,
                    requestWithIdentifier: &*id,
                    content: &*content,
                    trigger: None::<&AnyObject>
                ];
                let Some(request) = request else { return };
                let _: () = msg_send![&*center, addNotificationRequest: &*request,
                    withCompletionHandler: None::<&DynBlock<dyn Fn(*mut AnyObject)>>];
            }
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn event(id: u64, kind: &str, outcome: Option<&str>) -> Event {
        Event {
            id,
            kind: kind.into(),
            conversation_id: Some("c1".into()),
            outcome: outcome.map(Into::into),
            task_name: Some("Morning brief".into()),
        }
    }

    #[test]
    fn only_the_main_window_hides() {
        assert_eq!(close_action(crate::MAIN_LABEL), CloseAction::Hide);
        assert_eq!(close_action(crate::SPLASH_LABEL), CloseAction::Close);
        assert_eq!(close_action("recovery"), CloseAction::Close);
    }

    #[test]
    fn sleep_is_held_only_for_work_and_only_when_allowed() {
        let mut s = Status {
            keep_awake: true,
            working: 1,
            ..Status::default()
        };
        assert!(want_sleep_assertion(&s));
        s.working = 0;
        s.awaiting = 2; // waiting on the user is not work
        assert!(!want_sleep_assertion(&s));
        s.working = 1;
        s.keep_awake = false;
        assert!(!want_sleep_assertion(&s));
        let missing: Status = serde_json::from_str(r#"{"working": 3}"#).unwrap();
        assert!(
            !want_sleep_assertion(&missing),
            "a malformed answer must not keep the Mac awake"
        );
    }

    #[test]
    fn notifies_only_when_the_window_is_not_in_front() {
        assert!(should_notify(true, false, false)); // hidden
        assert!(should_notify(true, true, false)); // visible, another app in front
        assert!(!should_notify(true, true, true)); // the user is looking at it
        assert!(!should_notify(false, false, false)); // turned off
    }

    #[test]
    fn history_is_skipped_and_a_restarted_backend_is_not_lost() {
        let status = Status {
            cursor: 7,
            events: vec![
                event(6, "turn_finished", Some("ok")),
                event(7, "approval_needed", None),
            ],
            ..Status::default()
        };
        assert!(fresh_events(None, &status).is_empty()); // first poll adopts the cursor
        assert_eq!(
            fresh_events(Some(6), &status)
                .iter()
                .map(|e| e.id)
                .collect::<Vec<_>>(),
            vec![7]
        );
        // A restarted backend counts from 1 again: its events are all new.
        let restarted = Status {
            cursor: 2,
            events: vec![
                event(1, "turn_finished", Some("ok")),
                event(2, "approval_needed", None),
            ],
            ..Status::default()
        };
        assert_eq!(fresh_events(Some(40), &restarted).len(), 2);
    }

    #[test]
    fn notification_text_never_carries_message_content() {
        let done = notification("en", &event(1, "turn_finished", Some("ok"))).unwrap();
        assert!(!done.0.is_empty() && !done.0.contains("{"));
        assert!(notification("en", &event(1, "turn_finished", Some("cancelled"))).is_none());
        let (_, body) = notification("en", &event(1, "scheduled_finished", Some("ok"))).unwrap();
        assert!(
            body.contains("Morning brief"),
            "a scheduled task is named by its own label"
        );
        let (_, approval) = notification("zh", &event(1, "approval_needed", None)).unwrap();
        assert!(!approval.contains("Morning brief"));
        assert!(notification("en", &event(1, "unknown_kind", None)).is_none());
    }

    #[test]
    fn every_notification_and_tray_key_exists_in_all_six_locales() {
        let catalog: serde_json::Value =
            serde_json::from_str(include_str!("../native_messages.json")).unwrap();
        let keys = [
            "tray_idle",
            "tray_working",
            "tray_awaiting",
            "tray_keeping_awake",
            "tray_open",
            "tray_quit",
            "notify_done_title",
            "notify_done_body",
            "notify_attention_title",
            "notify_attention_body",
            "notify_approval_title",
            "notify_approval_body",
            "notify_scheduled_done_title",
            "notify_scheduled_done_body",
            "notify_scheduled_failed_title",
            "notify_scheduled_failed_body",
            "notify_scheduled_paused_title",
            "notify_scheduled_paused_body",
        ];
        for locale in ["en", "zh", "ja", "es", "de", "fr"] {
            for key in keys {
                let value = catalog[locale][key].as_str();
                assert!(
                    value.is_some_and(|v| !v.trim().is_empty()),
                    "{locale}.{key} missing"
                );
            }
        }
    }

    #[test]
    fn status_line_counts_and_marks_a_held_assertion() {
        let s = Status {
            working: 2,
            ..Status::default()
        };
        let line = status_line("en", &s, true);
        assert!(line.contains('2') && line.contains(" · "));
        let waiting = status_line(
            "en",
            &Status {
                working: 1,
                awaiting: 1,
                ..Status::default()
            },
            false,
        );
        assert_eq!(
            waiting,
            native_locale::text("en", "tray_awaiting").replace("{n}", "1")
        );
    }

    #[test]
    fn parses_only_successful_responses() {
        let ok = "HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n\r\n{\"cursor\":3,\"working\":1,\"awaiting\":0,\"events\":[],\"keep_awake\":true,\"notifications\":true}";
        assert_eq!(parse_response(ok).unwrap().cursor, 3);
        assert!(parse_response("HTTP/1.1 401 Unauthorized\r\n\r\n{}").is_none());
        assert!(parse_response("HTTP/1.1 200 OK\r\n\r\nnot json").is_none());
    }

    #[test]
    fn a_notification_id_round_trips_its_conversation() {
        let e = event(12, "turn_finished", Some("ok"));
        assert_eq!(
            conversation_from_id(&notification_id(&e)).as_deref(),
            Some("c1")
        );
        let with_bars = Event {
            conversation_id: Some("a|b".into()),
            ..e.clone()
        };
        assert_eq!(
            conversation_from_id(&notification_id(&with_bars)).as_deref(),
            Some("a|b")
        );
        assert_eq!(conversation_from_id("other|12|c1"), None);
        assert_eq!(conversation_from_id("arslan|x|c1"), None);
        assert_eq!(conversation_from_id("arslan|12|"), None);
    }
}

//! Arslan Island (0.1.51 I1): a second, transparent window at the notch.
//!
//! The shell owns the window, where it sits, which pixels take the pointer and
//! whether you are at the Mac; the page (web/island.html, served by the
//! sidecar like the app) owns everything it shows and every behaviour rule.
//!
//! - 720 × 320 points, borderless, transparent, no shadow, above the menu bar,
//!   on every Space and over full-screen apps, never in the Dock or ⌘-Tab,
//!   never key (focus stays where you were), and absent from screenshots,
//!   recordings and screen sharing (`sharingType = none`).
//! - The page reports the rectangle it is drawing (`island_shape`); a 30 Hz
//!   poll compares the pointer with it and makes the window ignore the mouse
//!   everywhere else, so the transparent area clicks through. The same poll
//!   tells the page when the pointer arrives and leaves (`island-pointer`):
//!   a window that is never key gets no reliable hover events of its own.
//! - Away: no keyboard or mouse input for three minutes (`island-presence`).
//! - Geometry: the display with a notch hosts it, sized to the notch; without
//!   one, the main display gets a small bar (`island-geometry`).
//!
//! Known limit, still open in 0.1.55: a click on the island activates Arslan (an
//! NSWindow, not a non-activating NSPanel). Since 0.1.55 the island answers cards
//! itself (Allow / Decline, POST /approvals/{id}/answer), so that click now does
//! something here AND brings Arslan forward — over a full-screen app that can switch
//! Spaces. The fix is a non-activating panel (class swap to an NSPanel subclass with
//! the nonactivating style); it is NOT done: it must be measured on a real Mac
//! (full-screen app, a waiting card, answered from the tab) before it ships.
//! `fullscreen` in the geometry (menu bar hidden) is likewise unmeasured on hardware.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tauri::{Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

pub const LABEL: &str = "island";
pub const GEOMETRY_EVENT: &str = "island-geometry";
pub const PRESENCE_EVENT: &str = "island-presence";
pub const POINTER_EVENT: &str = "island-pointer";
pub const MAIN_FOCUS_EVENT: &str = "island-main-focus";
pub const WINDOW_W: f64 = 720.0;
pub const WINDOW_H: f64 = 320.0;
const HIT_MARGIN: f64 = 6.0;
#[cfg(target_os = "macos")]
const POINTER_EVERY: Duration = Duration::from_millis(33);
#[cfg(target_os = "macos")]
const PRESENCE_EVERY: Duration = Duration::from_secs(2);
pub const AWAY_AFTER_SECS: f64 = 180.0;
const FLAT_BAR_HEIGHT: f64 = 24.0;

// ── pure decisions (unit-tested) ─────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Geometry {
    pub notch: bool,
    pub notch_width: f64,
    pub bar_height: f64,
    /// 0.1.55 decision 4: the menu bar is hidden on this display — a full-screen app
    /// (or "hide the menu bar automatically"). A waiting card then shows as a small
    /// still tab instead of the whole card, until the pointer opens it.
    pub fullscreen: bool,
}

/// A display as AppKit measures it: points, origin bottom-left.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Display {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
    /// `safeAreaInsets.top`: the notch height on a notched display, else 0.
    pub safe_top: f64,
    /// `auxiliaryTopLeftArea` / `auxiliaryTopRightArea` as (min x, max x).
    pub aux_left: Option<(f64, f64)>,
    pub aux_right: Option<(f64, f64)>,
    /// Height of the menu bar on this display (frame top − visible frame top).
    pub menu_bar: f64,
}

/// Which display hosts the island and how it is shaped. The notched display
/// wins; otherwise the first display (AppKit lists the menu-bar display first).
pub fn pick_display(displays: &[Display]) -> Option<(Display, Geometry)> {
    for d in displays {
        if let (true, Some(left), Some(right)) = (d.safe_top > 0.0, d.aux_left, d.aux_right) {
            // The gap between the two usable top areas is the notch; the
            // difference is the same in screen-local and global coordinates.
            let width = right.0 - left.1;
            if width > 40.0 && width < 600.0 {
                return Some((
                    *d,
                    Geometry {
                        notch: true,
                        notch_width: width,
                        bar_height: d.safe_top,
                        fullscreen: menu_bar_hidden(d),
                    },
                ));
            }
        }
    }
    let d = *displays.first()?;
    let bar = if d.menu_bar > 0.0 && d.menu_bar < 60.0 {
        d.menu_bar
    } else {
        FLAT_BAR_HEIGHT
    };
    Some((
        d,
        Geometry {
            notch: false,
            notch_width: 0.0,
            bar_height: bar,
            fullscreen: menu_bar_hidden(&d),
        },
    ))
}

/// No menu bar showing on this display: its visible frame reaches the top.
pub fn menu_bar_hidden(d: &Display) -> bool {
    d.menu_bar < 1.0
}

/// Bottom-left origin (AppKit) of the island window: centred on the display
/// (the notch is physically centred), its top edge on the display's top edge.
pub fn window_origin(d: &Display) -> (f64, f64) {
    (
        (d.x + d.w / 2.0 - WINDOW_W / 2.0).round(),
        d.y + d.h - WINDOW_H,
    )
}

/// The rectangle the page draws, in window points from the top-left.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Shape {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
}

/// What the page sends, checked: finite, inside the window, never negative.
pub fn sanitize_shape(x: f64, y: f64, w: f64, h: f64) -> Option<Shape> {
    if ![x, y, w, h].iter().all(|v| v.is_finite()) || w < 0.0 || h < 0.0 {
        return None;
    }
    let x0 = x.clamp(0.0, WINDOW_W);
    let y0 = y.clamp(0.0, WINDOW_H);
    Some(Shape {
        x: x0,
        y: y0,
        w: (x + w).clamp(0.0, WINDOW_W) - x0,
        h: (y + h).clamp(0.0, WINDOW_H) - y0,
    })
}

/// Is the pointer over the island? `frame` is the window's AppKit frame
/// (x, y, w, h — origin bottom-left) and `mouse` the pointer in the same space.
pub fn pointer_inside(shape: Shape, frame: (f64, f64, f64, f64), mouse: (f64, f64)) -> bool {
    if shape.w <= 0.0 || shape.h <= 0.0 {
        return false;
    }
    let rel_x = mouse.0 - frame.0;
    let rel_y = (frame.1 + frame.3) - mouse.1;
    rel_x >= shape.x - HIT_MARGIN
        && rel_x <= shape.x + shape.w + HIT_MARGIN
        && rel_y >= shape.y - HIT_MARGIN
        && rel_y <= shape.y + shape.h + HIT_MARGIN
}

pub fn is_away(idle_secs: f64) -> bool {
    idle_secs.is_finite() && idle_secs >= AWAY_AFTER_SECS
}

/// A conversation id from the page is data: short, plain characters only.
pub fn valid_conversation_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 128
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | ':' | '.' | '@'))
}

/// The initialization script: the same token the main window gets, the
/// island flag, and the geometry measured when the window was built.
pub fn init_script(token: Option<&str>, geometry: &Geometry) -> String {
    let mut s = String::from("window.__ARSLAN_ISLAND__ = true;");
    if let Some(t) = token {
        s.push_str(&format!(
            "window.__ARSLAN_TOKEN__ = {};",
            serde_json::to_string(t).unwrap_or_default()
        ));
    }
    s.push_str(&format!(
        "window.__ARSLAN_ISLAND_GEOMETRY__ = {};",
        serde_json::to_string(geometry).unwrap_or_else(|_| "null".into())
    ));
    s
}

// ── runtime ──────────────────────────────────────────────────────────────────

#[derive(Default)]
pub struct State {
    shape: Mutex<Shape>,
    inside: AtomicBool,
    away: AtomicBool,
    geometry: Mutex<Option<(Display, Geometry)>>,
    tick_pending: Arc<AtomicBool>,
}

#[tauri::command]
pub fn island_shape(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, State>,
    x: f64,
    y: f64,
    w: f64,
    h: f64,
) -> Result<(), String> {
    if window.label() != LABEL {
        return Err("island_only".into());
    }
    let shape = sanitize_shape(x, y, w, h).ok_or("invalid_shape")?;
    *state.shape.lock().unwrap() = shape;
    Ok(())
}

#[tauri::command]
pub fn island_open_conversation(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    conversation_id: Option<String>,
) -> Result<(), String> {
    if window.label() != LABEL {
        return Err("island_only".into());
    }
    crate::resident::show_main(&app);
    if let Some(cid) = conversation_id.filter(|c| valid_conversation_id(c)) {
        // The app opens only a conversation it already has (lib/openConversation.ts).
        let _ = app.emit_to(
            crate::MAIN_LABEL,
            crate::resident::OPEN_CONVERSATION_EVENT,
            cid,
        );
    }
    Ok(())
}

/// Tell the island whether the main window has focus: a chat answer you are
/// looking at does not need to pop up at the notch.
pub fn main_focus(app: &tauri::AppHandle, focused: bool) {
    let _ = app.emit_to(
        LABEL,
        MAIN_FOCUS_EVENT,
        serde_json::json!({ "focused": focused }),
    );
}

/// Build the island once the main window exists. macOS only in I1.
pub fn open(app: &tauri::AppHandle, port: u16) {
    #[cfg(target_os = "macos")]
    macos::open(app, port);
    #[cfg(not(target_os = "macos"))]
    let _ = (app, port);
}

#[cfg(target_os = "macos")]
mod macos {
    use super::*;
    use objc2::MainThreadMarker;
    use objc2_app_kit::{
        NSEvent, NSMainMenuWindowLevel, NSScreen, NSWindow, NSWindowCollectionBehavior,
        NSWindowSharingType,
    };
    use objc2_foundation::NSPoint;

    #[link(name = "CoreGraphics", kind = "framework")]
    extern "C" {
        fn CGEventSourceSecondsSinceLastEventType(state: i32, event_type: u32) -> f64;
    }
    const COMBINED_SESSION_STATE: i32 = 0;
    const ANY_INPUT_EVENT: u32 = u32::MAX;

    fn displays(mtm: MainThreadMarker) -> Vec<Display> {
        NSScreen::screens(mtm)
            .iter()
            .map(|s| {
                let f = s.frame();
                let v = s.visibleFrame();
                let inset = s.safeAreaInsets();
                let span = |r: objc2_foundation::NSRect| {
                    (r.size.width > 0.0).then_some((r.origin.x, r.origin.x + r.size.width))
                };
                Display {
                    x: f.origin.x,
                    y: f.origin.y,
                    w: f.size.width,
                    h: f.size.height,
                    safe_top: inset.top,
                    aux_left: span(s.auxiliaryTopLeftArea()),
                    aux_right: span(s.auxiliaryTopRightArea()),
                    menu_bar: (f.origin.y + f.size.height) - (v.origin.y + v.size.height),
                }
            })
            .collect()
    }

    fn ns_window(window: &tauri::WebviewWindow) -> Option<&NSWindow> {
        let ptr = window.ns_window().ok()? as *const NSWindow;
        // Owned by the tauri window, which outlives every main-thread call here.
        unsafe { ptr.as_ref() }
    }

    fn place(ns: &NSWindow, d: &Display) {
        let (x, y) = window_origin(d);
        ns.setFrameOrigin(NSPoint::new(x, y));
    }

    pub fn open(app: &tauri::AppHandle, port: u16) {
        let Some(mtm) = MainThreadMarker::new() else {
            return;
        };
        let Some((display, geometry)) = pick_display(&displays(mtm)) else {
            return;
        };
        let url: tauri::Url = match format!("http://127.0.0.1:{port}/island.html").parse() {
            Ok(u) => u,
            Err(_) => return,
        };
        let built = WebviewWindowBuilder::new(app, LABEL, WebviewUrl::External(url))
            .title("Arslan Island")
            .inner_size(WINDOW_W, WINDOW_H)
            .resizable(false)
            .decorations(false)
            .transparent(true)
            .shadow(false)
            .always_on_top(true)
            .visible_on_all_workspaces(true)
            .skip_taskbar(true)
            .focused(false)
            .focusable(false)
            .accept_first_mouse(true)
            .disable_drag_drop_handler()
            .initialization_script(init_script(crate::read_api_token().as_deref(), &geometry))
            .build();
        let window = match built {
            Ok(w) => w,
            Err(e) => {
                eprintln!("Arslan Island could not open: {e}");
                return;
            }
        };
        if let Some(ns) = ns_window(&window) {
            // Above the menu bar (so it can sit in the notch), on every Space,
            // over full-screen apps, out of the window cycle, and never in a
            // screenshot, a recording or a shared screen.
            ns.setLevel(NSMainMenuWindowLevel + 3);
            ns.setCollectionBehavior(
                NSWindowCollectionBehavior::CanJoinAllSpaces
                    | NSWindowCollectionBehavior::Stationary
                    | NSWindowCollectionBehavior::IgnoresCycle
                    | NSWindowCollectionBehavior::FullScreenAuxiliary,
            );
            // Debug builds only: ARSLAN_ISLAND_SHAREABLE=1 leaves it capturable,
            // so the island can be screenshotted while developing it.
            let capturable =
                cfg!(debug_assertions) && std::env::var_os("ARSLAN_ISLAND_SHAREABLE").is_some();
            if !capturable {
                ns.setSharingType(NSWindowSharingType::None);
            }
            ns.setHasShadow(false);
            ns.setIgnoresMouseEvents(true);
            place(ns, &display);
        }
        let state = app.state::<State>();
        *state.geometry.lock().unwrap() = Some((display, geometry));
        start_pointer(app.clone(), state.tick_pending.clone());
        start_presence(app.clone());
    }

    /// 30 Hz on the main thread, at most one tick queued at a time.
    fn start_pointer(app: tauri::AppHandle, pending: Arc<AtomicBool>) {
        std::thread::spawn(move || loop {
            std::thread::sleep(POINTER_EVERY);
            if pending.swap(true, Ordering::AcqRel) {
                continue;
            }
            let inner = app.clone();
            let flag = pending.clone();
            if app
                .run_on_main_thread(move || {
                    pointer_tick(&inner);
                    flag.store(false, Ordering::Release);
                })
                .is_err()
            {
                return;
            }
        });
    }

    fn pointer_tick(app: &tauri::AppHandle) {
        let Some(window) = app.get_webview_window(LABEL) else {
            return;
        };
        let Some(ns) = ns_window(&window) else { return };
        let state = app.state::<State>();
        let f = ns.frame();
        let m = NSEvent::mouseLocation();
        let shape = *state.shape.lock().unwrap();
        let inside = pointer_inside(
            shape,
            (f.origin.x, f.origin.y, f.size.width, f.size.height),
            (m.x, m.y),
        );
        if state.inside.swap(inside, Ordering::AcqRel) != inside {
            ns.setIgnoresMouseEvents(!inside);
            let _ = app.emit_to(
                LABEL,
                POINTER_EVENT,
                serde_json::json!({ "inside": inside }),
            );
        }
    }

    /// Every 2 s: are you at the Mac, and did the displays change?
    fn start_presence(app: tauri::AppHandle) {
        std::thread::spawn(move || loop {
            std::thread::sleep(PRESENCE_EVERY);
            let idle = unsafe {
                CGEventSourceSecondsSinceLastEventType(COMBINED_SESSION_STATE, ANY_INPUT_EVENT)
            };
            let away = is_away(idle);
            let state = app.state::<State>();
            if state.away.swap(away, Ordering::AcqRel) != away {
                let _ = app.emit_to(LABEL, PRESENCE_EVENT, serde_json::json!({ "away": away }));
            }
            let inner = app.clone();
            if app
                .run_on_main_thread(move || geometry_tick(&inner))
                .is_err()
            {
                return;
            }
        });
    }

    fn geometry_tick(app: &tauri::AppHandle) {
        let Some(mtm) = MainThreadMarker::new() else {
            return;
        };
        let Some(picked) = pick_display(&displays(mtm)) else {
            return;
        };
        let state = app.state::<State>();
        let mut current = state.geometry.lock().unwrap();
        if current.as_ref() == Some(&picked) {
            return;
        }
        *current = Some(picked);
        if let Some(window) = app.get_webview_window(LABEL) {
            if let Some(ns) = ns_window(&window) {
                place(ns, &picked.0);
            }
        }
        let _ = app.emit_to(LABEL, GEOMETRY_EVENT, picked.1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn notched() -> Display {
        // A 14" MacBook Pro at its default scaled resolution.
        Display {
            x: 0.0,
            y: 0.0,
            w: 1512.0,
            h: 982.0,
            safe_top: 32.0,
            aux_left: Some((0.0, 662.0)),
            aux_right: Some((850.0, 1512.0)),
            menu_bar: 32.0,
        }
    }
    fn external() -> Display {
        Display {
            x: 1512.0,
            y: -200.0,
            w: 2560.0,
            h: 1440.0,
            safe_top: 0.0,
            aux_left: None,
            aux_right: None,
            menu_bar: 25.0,
        }
    }

    #[test]
    fn the_notched_display_hosts_the_island_sized_to_its_notch() {
        let (d, g) = pick_display(&[external(), notched()]).unwrap();
        assert_eq!(d, notched());
        assert_eq!(
            g,
            Geometry {
                notch: true,
                notch_width: 188.0,
                bar_height: 32.0,
                fullscreen: false
            }
        );
    }

    #[test]
    fn a_hidden_menu_bar_reads_as_full_screen_on_either_kind_of_display() {
        // In a full-screen Space the menu bar is hidden: the visible frame reaches the top.
        let full = Display {
            menu_bar: 0.0,
            ..notched()
        };
        let (_, g) = pick_display(&[full]).unwrap();
        assert!(g.notch && g.fullscreen);
        // The notch height stays the bar height: the notch is still there.
        assert_eq!(g.bar_height, 32.0);
        let flat = Display {
            menu_bar: 0.0,
            ..external()
        };
        let (_, g) = pick_display(&[flat]).unwrap();
        assert!(!g.notch && g.fullscreen);
        assert!(!pick_display(&[notched()]).unwrap().1.fullscreen);
    }

    #[test]
    fn without_a_notch_the_menu_bar_display_gets_a_small_bar() {
        let (d, g) = pick_display(&[external()]).unwrap();
        assert_eq!(d, external());
        assert_eq!(
            g,
            Geometry {
                notch: false,
                notch_width: 0.0,
                bar_height: 25.0,
                fullscreen: false
            }
        );
        assert!(pick_display(&[]).is_none());
        // A safe-area inset without the two top areas is not a notch.
        let odd = Display {
            aux_left: None,
            ..notched()
        };
        assert!(!pick_display(&[odd]).unwrap().1.notch);
        // Top areas without a safe-area inset (no notch reported) are not one either.
        let flat_top = Display {
            safe_top: 0.0,
            ..notched()
        };
        assert!(!pick_display(&[flat_top]).unwrap().1.notch);
    }

    #[test]
    fn the_window_sits_centred_on_the_top_edge() {
        assert_eq!(window_origin(&notched()), (396.0, 982.0 - WINDOW_H));
        assert_eq!(
            window_origin(&external()),
            (1512.0 + 1280.0 - 360.0, -200.0 + 1440.0 - WINDOW_H)
        );
    }

    #[test]
    fn the_pointer_counts_over_the_shape_plus_a_small_margin_only() {
        let shape = Shape {
            x: 253.0,
            y: 0.0,
            w: 214.0,
            h: 32.0,
        };
        let frame = (396.0, 662.0, WINDOW_W, WINDOW_H); // window top at 982
        let at = |rel_x: f64, rel_y: f64| (396.0 + rel_x, 982.0 - rel_y);
        assert!(pointer_inside(shape, frame, at(360.0, 10.0)));
        assert!(pointer_inside(shape, frame, at(253.0 - 6.0, 0.0)));
        assert!(!pointer_inside(shape, frame, at(253.0 - 7.0, 10.0)));
        assert!(pointer_inside(shape, frame, at(360.0, 32.0 + 6.0)));
        assert!(!pointer_inside(shape, frame, at(360.0, 32.0 + 7.0)));
        assert!(
            !pointer_inside(Shape::default(), frame, at(0.0, 0.0)),
            "nothing drawn, nothing takes the pointer"
        );
    }

    #[test]
    fn shapes_from_the_page_are_checked() {
        assert_eq!(
            sanitize_shape(10.0, 0.0, 100.0, 32.0),
            Some(Shape {
                x: 10.0,
                y: 0.0,
                w: 100.0,
                h: 32.0
            })
        );
        assert_eq!(
            sanitize_shape(-20.0, 0.0, 800.0, 999.0),
            Some(Shape {
                x: 0.0,
                y: 0.0,
                w: WINDOW_W,
                h: WINDOW_H
            })
        );
        assert_eq!(sanitize_shape(f64::NAN, 0.0, 1.0, 1.0), None);
        assert_eq!(sanitize_shape(0.0, 0.0, -1.0, 1.0), None);
    }

    #[test]
    fn away_after_three_minutes_without_input() {
        assert!(!is_away(179.9));
        assert!(is_away(180.0));
        assert!(!is_away(f64::NAN));
    }

    #[test]
    fn conversation_ids_from_the_page_are_plain_data() {
        assert!(valid_conversation_id("main"));
        assert!(valid_conversation_id("c-12_ab:3"));
        assert!(!valid_conversation_id(""));
        assert!(!valid_conversation_id("../etc"));
        assert!(!valid_conversation_id("a\"b"));
        assert!(!valid_conversation_id(&"x".repeat(129)));
    }

    #[test]
    fn the_init_script_quotes_the_token_and_carries_the_geometry() {
        let g = Geometry {
            notch: true,
            notch_width: 188.0,
            bar_height: 32.0,
            fullscreen: false,
        };
        let s = init_script(Some("ab\"c"), &g);
        assert!(s.contains(r#"window.__ARSLAN_TOKEN__ = "ab\"c";"#), "{s}");
        assert!(
            s.contains(r#"{"notch":true,"notchWidth":188.0,"barHeight":32.0,"fullscreen":false}"#),
            "{s}"
        );
        assert!(!init_script(None, &g).contains("__ARSLAN_TOKEN__"));
    }
}

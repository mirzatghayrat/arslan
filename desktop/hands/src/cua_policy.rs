//! What Hands lets through to Cua Driver (spec docs/specs/2026-10-08-0157-hands-v2.md §3.4).
//!
//! Enforced here, inside the process that holds the grants, so a backend bug cannot
//! open any of it; the backend repeats it for clear messages. Three layers:
//!
//! 1. **Tools.** Reads and background actions only. Clipboard, browser, recording,
//!    configuration, update, extension, session and cursor-setting tools, whole-desktop
//!    screenshots and anything unnamed are refused. Borrowing the user's focus
//!    (`delivery_mode: "foreground"`, menus, drags) waits for the borrow mode (P2).
//! 2. **Arguments.** Nothing that reaches beyond one window of one allowed app or onto
//!    the disk: no `scope: "desktop"` (the frontmost app, whatever it is), no `target`
//!    descriptor, no `screenshot_out_file` / `debug_image_out` (a write anywhere), no
//!    caller-chosen session.
//! 3. **Elements.** An `element_token` names its window by itself, so a token Hands has
//!    not seen could point at any app: an action may only use a token from a window
//!    state Hands relayed, of the same pid. Text goes only into an element named by such
//!    a token, never into a password field (role, label, and — on macOS — the live
//!    subrole at that point), and keys never go to a focused password field.

use crate::argv::{refuse, Refusal, MAX_TEXT};
use crate::policy::{Tier, PASSWORD_WORDS};
use serde_json::{Map, Value};
use std::collections::HashMap;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    /// Not about one app: the app list, the screen size, permissions, health.
    Global,
    /// Reads one app's windows.
    Read,
    /// Acts in one app's window, in the background.
    Act,
}

pub fn kind(tool: &str) -> Result<Kind, Refusal> {
    match tool {
        "list_apps" | "get_screen_size" | "check_permissions" | "health_report" => Ok(Kind::Global),
        "list_windows" | "get_window_state" | "verify_state" | "zoom" => Ok(Kind::Read),
        "click" | "double_click" | "right_click" | "scroll" | "set_value" | "type_text"
        | "press_key" | "hotkey" => Ok(Kind::Act),
        _ => Err(refuse(
            "op_not_allowed",
            format!("`{tool}` is not something Arslan Hands lets Cua Driver do"),
        )),
    }
}

/// The tools that send text or keys.
pub fn types(tool: &str) -> bool {
    matches!(tool, "set_value" | "type_text" | "press_key" | "hotkey")
}

/// What each tier lets an action do (the same split as agent-desktop's: browsers are
/// read only, terminals and editors click and scroll but never type).
pub fn tier_allows(tier: Tier, tool: &str) -> bool {
    match tier {
        Tier::Denied | Tier::LookOnly => false,
        Tier::ClickOnly => matches!(tool, "click" | "double_click" | "right_click" | "scroll"),
        Tier::Full => true,
    }
}

/// Chords that act on the system rather than on one app: never sent.
const SYSTEM_CHORDS: [&[&str]; 7] = [
    &["cmd", "tab"],
    &["cmd", "space"],
    &["ctrl", "space"],
    &["cmd", "option", "esc"],
    &["ctrl", "cmd", "q"],
    &["cmd", "shift", "q"],
    &["cmd", "option", "shift", "q"],
];

fn chord_key(name: &str) -> String {
    match name.trim().to_ascii_lowercase().as_str() {
        "command" | "⌘" => "cmd".into(),
        "alt" | "opt" | "⌥" => "option".into(),
        "control" | "⌃" => "ctrl".into(),
        "escape" => "esc".into(),
        other => other.to_string(),
    }
}

fn is_system_chord(keys: &[String]) -> bool {
    let mut pressed: Vec<String> = keys.iter().map(|k| chord_key(k)).collect();
    pressed.sort();
    SYSTEM_CHORDS.iter().any(|chord| {
        let mut wanted: Vec<String> = chord.iter().map(|k| k.to_string()).collect();
        wanted.sort();
        wanted == pressed
    })
}

fn too_long(value: Option<&Value>) -> bool {
    value
        .and_then(Value::as_str)
        .is_some_and(|text| text.chars().count() > MAX_TEXT)
}

/// The arguments Hands passes on, or why not. `session` is the label Hands chose.
pub fn sanitize(
    tool: &str,
    kind: Kind,
    args: &Value,
    session: &str,
) -> Result<Map<String, Value>, Refusal> {
    let mut args = match args {
        Value::Null => Map::new(),
        Value::Object(map) => map.clone(),
        _ => return Err(refuse("bad_request", "`args` must be an object")),
    };
    for key in ["screenshot_out_file", "debug_image_out", "target"] {
        if args.contains_key(key) {
            return Err(refuse(
                "arg_not_allowed",
                format!("`{key}` is not passed to Cua Driver"),
            ));
        }
    }
    if args
        .get("scope")
        .is_some_and(|s| s.as_str() != Some("window"))
    {
        return Err(refuse(
            "arg_not_allowed",
            "only window-scoped input: never the desktop or the frontmost app",
        ));
    }
    if args
        .get("delivery_mode")
        .is_some_and(|m| m.as_str() != Some("background"))
    {
        return Err(refuse(
            "borrow_not_allowed",
            "borrowing the user's focus (foreground delivery) is not available yet",
        ));
    }
    args.remove("session");
    args.insert("session".into(), Value::String(session.into()));
    if kind != Kind::Global
        && !args
            .get("pid")
            .and_then(Value::as_i64)
            .is_some_and(|pid| pid > 0)
    {
        return Err(refuse("bad_request", "`pid` (a running app's) is required"));
    }
    if too_long(args.get("text")) || too_long(args.get("value")) {
        return Err(refuse("too_long", "text too long"));
    }
    if matches!(tool, "set_value" | "type_text") {
        // Text only into an element Hands has seen (so it can tell a password field):
        // never at a pixel, never into whatever happens to have the focus.
        if args.get("element_token").and_then(Value::as_str).is_none()
            || args.contains_key("x")
            || args.contains_key("y")
        {
            return Err(refuse(
                "element_required",
                "type into an element named by its element_token from a window state",
            ));
        }
    }
    if tool == "hotkey" {
        let keys: Vec<String> = args
            .get("keys")
            .and_then(Value::as_array)
            .map(|keys| {
                keys.iter()
                    .filter_map(Value::as_str)
                    .map(str::to_string)
                    .collect()
            })
            .unwrap_or_default();
        if keys.is_empty() || keys.len() > 5 {
            return Err(refuse(
                "bad_request",
                "`keys`: one chord of up to five keys",
            ));
        }
        if is_system_chord(&keys) {
            return Err(refuse(
                "arg_not_allowed",
                "that chord acts on the system, not on the app",
            ));
        }
    }
    Ok(args)
}

/// A window state without what is not the app's own: the system's Apple menu (its Recent
/// Items lists the user's recent documents and apps, and Log Out names the user — seen in a
/// harness run, 2026-10-09) is cut from `elements`, and `tree_markdown`, the same tree as
/// text, is dropped: Hands relays the structured elements only.
pub fn without_system_menu(result: &mut Value) {
    let Some(state) = result
        .get_mut("structuredContent")
        .and_then(Value::as_object_mut)
    else {
        return;
    };
    state.remove("tree_markdown");
    let Some(elements) = state.get_mut("elements").and_then(Value::as_array_mut) else {
        return;
    };
    let mut kept = Vec::with_capacity(elements.len());
    let mut cutting_below: Option<i64> = None;
    for element in elements.drain(..) {
        let depth = element.get("depth").and_then(Value::as_i64).unwrap_or(0);
        if let Some(cut) = cutting_below {
            if depth > cut {
                continue;
            }
            cutting_below = None;
        }
        let role = element.get("role").and_then(Value::as_str).unwrap_or("");
        let label = element.get("label").and_then(Value::as_str).unwrap_or("");
        if role == "AXMenuBarItem" && label == "Apple" {
            cutting_below = Some(depth);
            continue;
        }
        kept.push(element);
    }
    let count = kept.len();
    *elements = kept;
    if state.contains_key("returned_element_count") {
        state.insert("returned_element_count".into(), Value::from(count));
    }
}

/// One element Hands relayed from a window state.
#[derive(Debug, Clone, PartialEq)]
pub struct Element {
    pub pid: i64,
    pub window_id: i64,
    pub role: String,
    pub label: String,
    /// Screen points: x, y, width, height.
    pub frame: Option<[f64; 4]>,
}

impl Element {
    /// A password field by what the window state says of it.
    pub fn looks_secure(&self) -> bool {
        let role = self.role.to_lowercase();
        let label = self.label.to_lowercase();
        role.contains("secure") || PASSWORD_WORDS.iter().any(|w| label.contains(w))
    }

    pub fn center(&self) -> Option<(f64, f64)> {
        self.frame.map(|[x, y, w, h]| (x + w / 2.0, y + h / 2.0))
    }
}

/// Upper bound on remembered elements: a window state of a huge app can list thousands.
const MAX_ELEMENTS: usize = 50_000;

/// The element tokens of every window state Hands relayed, by token.
#[derive(Debug, Default)]
pub struct Tokens {
    elements: HashMap<String, Element>,
}

fn snapshot_of(token: &str) -> &str {
    token
        .split_once(':')
        .map_or(token, |(snapshot, _)| snapshot)
}

impl Tokens {
    /// Remember the elements of a `get_window_state` result. A new state of a window
    /// replaces that window's elements, and snapshots the driver says it invalidated
    /// are forgotten.
    pub fn record(&mut self, result: &Value) {
        let Some(state) = result.get("structuredContent") else {
            return;
        };
        let (Some(pid), Some(window_id)) = (
            state.get("pid").and_then(Value::as_i64),
            state.get("window_id").and_then(Value::as_i64),
        ) else {
            return;
        };
        let invalidated: Vec<String> = state
            .get("invalidated_snapshot_ids")
            .and_then(Value::as_array)
            .map(|ids| {
                ids.iter()
                    .filter_map(Value::as_str)
                    .map(str::to_string)
                    .collect()
            })
            .unwrap_or_default();
        self.elements.retain(|token, element| {
            !(element.pid == pid && element.window_id == window_id)
                && !invalidated.iter().any(|id| id == snapshot_of(token))
        });
        if self.elements.len() > MAX_ELEMENTS {
            self.elements.clear();
        }
        for entry in state
            .get("elements")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            let Some(token) = entry.get("element_token").and_then(Value::as_str) else {
                continue;
            };
            let text = |key: &str| {
                entry
                    .get(key)
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string()
            };
            let number = |key: &str| {
                entry
                    .pointer(&format!("/frame/{key}"))
                    .and_then(Value::as_f64)
            };
            let frame = match (number("x"), number("y"), number("w"), number("h")) {
                (Some(x), Some(y), Some(w), Some(h)) => Some([x, y, w, h]),
                _ => None,
            };
            self.elements.insert(
                token.to_string(),
                Element {
                    pid,
                    window_id,
                    role: text("role"),
                    label: text("label"),
                    frame,
                },
            );
        }
    }

    /// The element a token names, if Hands relayed it for this very app.
    pub fn get(&self, token: &str, pid: i64) -> Result<&Element, Refusal> {
        let element = self.elements.get(token).ok_or_else(|| {
            refuse(
                "ref_unknown",
                "this element_token is not from a window state Arslan Hands relayed; look again",
            )
        })?;
        if element.pid != pid {
            return Err(refuse(
                "ref_wrong_app",
                "this element_token belongs to another app",
            ));
        }
        Ok(element)
    }

    pub fn len(&self) -> usize {
        self.elements.len()
    }

    pub fn is_empty(&self) -> bool {
        self.elements.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn state(pid: i64, window: i64, elements: Value) -> Value {
        json!({"content": [], "structuredContent": {"pid": pid, "window_id": window, "elements": elements}})
    }

    #[test]
    fn only_reads_and_background_actions_exist() {
        for tool in [
            "list_apps",
            "get_window_state",
            "click",
            "type_text",
            "hotkey",
        ] {
            assert!(kind(tool).is_ok(), "{tool}");
        }
        for tool in [
            "get_accessibility_tree",
            "clipboard_read",
            "clipboard_write",
            "browser_click",
            "page",
            "get_desktop_state",
            "set_config",
            "check_for_update",
            "start_recording",
            "replay_trajectory",
            "kill_app",
            "launch_app",
            "invoke_menu",
            "drag",
            "bring_to_front",
            "move_cursor",
            "set_window_frame",
            "start_session",
            "escalate_session",
            "set_agent_cursor_enabled",
            "parse_visual_regions",
            "install_ffmpeg",
            "get_cursor_position",
            "anything",
        ] {
            assert_eq!(kind(tool).unwrap_err().code, "op_not_allowed", "{tool}");
        }
    }

    #[test]
    fn tiers_limit_actions() {
        assert!(tier_allows(Tier::Full, "type_text"));
        assert!(tier_allows(Tier::ClickOnly, "click") && tier_allows(Tier::ClickOnly, "scroll"));
        for tool in ["type_text", "set_value", "press_key", "hotkey"] {
            assert!(!tier_allows(Tier::ClickOnly, tool), "{tool}");
        }
        assert!(!tier_allows(Tier::LookOnly, "click"));
        assert!(!tier_allows(Tier::Denied, "click"));
    }

    #[test]
    fn arguments_that_reach_beyond_one_window_are_refused() {
        let refused = |tool: &str, args: Value| {
            let kind = kind(tool).unwrap();
            sanitize(tool, kind, &args, "arslan").unwrap_err().code
        };
        assert_eq!(
            refused(
                "type_text",
                json!({"pid": 5, "text": "x", "scope": "desktop"})
            ),
            "arg_not_allowed"
        );
        assert_eq!(
            refused(
                "get_window_state",
                json!({"pid": 5, "window_id": 1, "screenshot_out_file": "/tmp/x.png"})
            ),
            "arg_not_allowed"
        );
        assert_eq!(
            refused(
                "click",
                json!({"pid": 5, "x": 1, "y": 1, "debug_image_out": "/tmp/x"})
            ),
            "arg_not_allowed"
        );
        assert_eq!(
            refused("click", json!({"pid": 5, "target": {"kind": "desktop"}})),
            "arg_not_allowed"
        );
        assert_eq!(
            refused("click", json!({"pid": 5, "delivery_mode": "foreground"})),
            "borrow_not_allowed"
        );
        assert_eq!(refused("click", json!({"x": 1, "y": 1})), "bad_request");
        assert_eq!(
            refused("type_text", json!({"pid": 5, "text": "x"})),
            "element_required"
        );
        assert_eq!(
            refused(
                "type_text",
                json!({"pid": 5, "text": "x", "element_token": "s1:2", "x": 1, "y": 2})
            ),
            "element_required"
        );
        assert_eq!(
            refused("hotkey", json!({"pid": 5, "keys": ["cmd", "tab"]})),
            "arg_not_allowed"
        );
        assert_eq!(
            refused(
                "hotkey",
                json!({"pid": 5, "keys": ["Escape", "Option", "Command"]})
            ),
            "arg_not_allowed"
        );
        assert_eq!(
            refused(
                "set_value",
                json!({"pid": 5, "element_token": "s1:2", "value": "x".repeat(MAX_TEXT + 1)})
            ),
            "too_long"
        );
    }

    #[test]
    fn hands_chooses_the_session() {
        let args = sanitize(
            "click",
            Kind::Act,
            &json!({"pid": 5, "session": "someone-else"}),
            "arslan-job-1",
        )
        .unwrap();
        assert_eq!(args["session"], "arslan-job-1");
        let ok = sanitize(
            "hotkey",
            Kind::Act,
            &json!({"pid": 5, "keys": ["cmd", "n"]}),
            "s",
        )
        .unwrap();
        assert_eq!(ok["keys"], json!(["cmd", "n"]));
    }

    #[test]
    fn tokens_belong_to_the_window_state_they_came_from() {
        let mut tokens = Tokens::default();
        tokens.record(&state(5, 10, json!([
            {"role": "AXButton", "label": "Save", "element_token": "s00000001:0", "frame": {"x": 10.0, "y": 20.0, "w": 40.0, "h": 20.0}},
            {"role": "AXStaticText", "label": "Title", "display_only": true},
        ])));
        assert_eq!(tokens.len(), 1);
        let save = tokens.get("s00000001:0", 5).unwrap();
        assert_eq!(save.center(), Some((30.0, 30.0)));
        assert_eq!(
            tokens.get("s00000001:0", 6).unwrap_err().code,
            "ref_wrong_app"
        );
        assert_eq!(
            tokens.get("s0000000f:3", 5).unwrap_err().code,
            "ref_unknown"
        );
        // A new state of the same window replaces its elements.
        tokens.record(&state(
            5,
            10,
            json!([{"role": "AXButton", "label": "Done", "element_token": "s00000002:0"}]),
        ));
        assert_eq!(
            tokens.get("s00000001:0", 5).unwrap_err().code,
            "ref_unknown"
        );
        assert!(tokens.get("s00000002:0", 5).is_ok());
        // Another window's state keeps it; an invalidation drops it.
        tokens.record(&state(
            5,
            11,
            json!([{"role": "AXButton", "element_token": "s00000003:0"}]),
        ));
        assert!(tokens.get("s00000002:0", 5).is_ok());
        let mut invalidating = state(5, 12, json!([]));
        invalidating["structuredContent"]["invalidated_snapshot_ids"] = json!(["s00000002"]);
        tokens.record(&invalidating);
        assert_eq!(
            tokens.get("s00000002:0", 5).unwrap_err().code,
            "ref_unknown"
        );
    }

    #[test]
    fn the_apple_menu_and_the_text_tree_are_not_relayed() {
        let mut result = json!({"content": [], "structuredContent": {"pid": 5, "window_id": 1,
            "tree_markdown": "- Log Out Someone", "returned_element_count": 6, "elements": [
            {"role": "AXButton", "label": "Save", "depth": 2},
            {"role": "AXMenuBar", "label": "", "depth": 1},
            {"role": "AXMenuBarItem", "label": "Apple", "depth": 2},
            {"role": "AXMenu", "label": "", "depth": 3},
            {"role": "AXMenuItem", "label": "secret-plan.pdf", "depth": 4},
            {"role": "AXMenuItem", "label": "Log Out Someone", "depth": 4},
            {"role": "AXMenuBarItem", "label": "Fixture", "depth": 2},
            {"role": "AXMenuItem", "label": "Bold", "depth": 4}]}});
        without_system_menu(&mut result);
        let state = &result["structuredContent"];
        assert!(state.get("tree_markdown").is_none());
        let labels: Vec<&str> = state["elements"]
            .as_array()
            .unwrap()
            .iter()
            .map(|e| e["label"].as_str().unwrap())
            .collect();
        assert_eq!(labels, ["Save", "", "Fixture", "Bold"]);
        assert_eq!(state["returned_element_count"], 4);
    }

    #[test]
    fn password_fields_are_recognised_by_role_or_label() {
        let element = |role: &str, label: &str| Element {
            pid: 1,
            window_id: 1,
            role: role.into(),
            label: label.into(),
            frame: None,
        };
        assert!(element("AXSecureTextField", "").looks_secure());
        assert!(element("AXTextField", "Password").looks_secure());
        assert!(element("AXTextField", "密码").looks_secure());
        assert!(!element("AXTextField", "Search").looks_secure());
    }
}

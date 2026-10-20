//! Which apps Hands may look at or act on (spec §2.4).
//!
//! The lists live in `desktop/hands/policy.json`, compiled in here and read by
//! the backend for Settings, so the list a person sees is the list enforced.
//! The backend may only ADD apps (the user's own "never touch" entries); it can
//! never take one of these out, because this check runs here.

use serde::Deserialize;
use std::sync::OnceLock;

const POLICY_JSON: &str = include_str!("../policy.json");

#[derive(Debug, Deserialize)]
struct Group {
    #[allow(dead_code)]
    label: String,
    bundle_ids: Vec<String>,
    names: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct Policy {
    denied: Vec<Group>,
    look_only: Vec<Group>,
    click_only: Vec<Group>,
    sends_on_return: Group,
}

fn policy() -> &'static Policy {
    static POLICY: OnceLock<Policy> = OnceLock::new();
    POLICY.get_or_init(|| serde_json::from_str(POLICY_JSON).expect("policy.json is valid"))
}

/// Words that mark a password field by its label (lower case), in the UI languages.
pub const PASSWORD_WORDS: [&str; 8] = [
    "password",
    "passcode",
    "passphrase",
    "密码",
    "口令",
    "パスワード",
    "contraseña",
    "passwort",
];

/// What Hands may do in one app.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tier {
    /// Not even looked at.
    Denied,
    /// Read the tree; never act (web browsers: acting goes through Arslan's own browser).
    LookOnly,
    /// Read, click and scroll; never type or press keys (terminals and editors:
    /// typing there would run commands outside the command sandbox).
    ClickOnly,
    Full,
}

fn bundle_matches(pattern: &str, bundle_id: &str) -> bool {
    match pattern.strip_suffix(".*") {
        Some(prefix) => {
            bundle_id.eq_ignore_ascii_case(prefix)
                || (bundle_id.len() > prefix.len() + 1
                    && bundle_id
                        .get(..prefix.len())
                        .is_some_and(|head| head.eq_ignore_ascii_case(prefix))
                    && bundle_id.as_bytes().get(prefix.len()) == Some(&b'.'))
        }
        None => bundle_id.eq_ignore_ascii_case(pattern),
    }
}

/// Some apps report their bundle id with a Team ID prefix
/// (`2BUA8C4S2C.com.1password.browser-helper`, seen on a real Mac): match the
/// id without it, so the prefix cannot hide an app from the lists.
fn without_team_prefix(bundle_id: &str) -> &str {
    match bundle_id.split_once('.') {
        Some((team, rest))
            if team.len() == 10
                && team
                    .bytes()
                    .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit())
                && !rest.is_empty() =>
        {
            rest
        }
        _ => bundle_id,
    }
}

fn in_group(group: &Group, bundle_id: &str, name: &str) -> bool {
    let name = name.trim();
    let bundle_id = without_team_prefix(bundle_id);
    (!bundle_id.is_empty()
        && group
            .bundle_ids
            .iter()
            .any(|p| bundle_matches(p, bundle_id)))
        || group.names.iter().any(|n| n.eq_ignore_ascii_case(name))
}

/// The tier of one running app. `extra_denied` are the user's own additions
/// (names or bundle ids), sent by the backend with each request.
pub fn tier(bundle_id: &str, name: &str, extra_denied: &[String]) -> Tier {
    let p = policy();
    let bundle_id = without_team_prefix(bundle_id);
    let extra = extra_denied.iter().any(|e| {
        let e = e.trim();
        !e.is_empty() && (e.eq_ignore_ascii_case(name.trim()) || bundle_matches(e, bundle_id))
    });
    if extra || p.denied.iter().any(|g| in_group(g, bundle_id, name)) {
        Tier::Denied
    } else if p.look_only.iter().any(|g| in_group(g, bundle_id, name)) {
        Tier::LookOnly
    } else if p.click_only.iter().any(|g| in_group(g, bundle_id, name)) {
        Tier::ClickOnly
    } else {
        Tier::Full
    }
}

/// Return sends a message in this app (asked every time by the backend; Hands
/// reports it so the backend's decision rests on the real app, not a name).
pub fn sends_on_return(bundle_id: &str, name: &str) -> bool {
    in_group(&policy().sends_on_return, bundle_id, name)
}

/// The operations a tier allows. Reading covers listing windows, the tree,
/// finding, reading a property and waiting for text.
pub fn allows(tier: Tier, op: &str) -> bool {
    let read = matches!(
        op,
        "list_windows" | "snapshot" | "find" | "get" | "wait" | "describe" | "capture_window"
    );
    match tier {
        Tier::Denied => false,
        Tier::LookOnly => read,
        Tier::ClickOnly => read || matches!(op, "click" | "scroll"),
        Tier::Full => {
            read || matches!(
                op,
                "click" | "scroll" | "type" | "set_value" | "select" | "press" | "menu"
            )
        }
    }
}

pub fn tier_name(tier: Tier) -> &'static str {
    match tier {
        Tier::Denied => "denied",
        Tier::LookOnly => "look_only",
        Tier::ClickOnly => "click_only",
        Tier::Full => "full",
    }
}

/// Keys that never put a character into a field, with or without shift or option. An allowlist:
/// a key name not here (a letter, a digit, `space`, a punctuation name) may type one.
/// Function keys (`f1`…) are matched by shape in keys_may_type.
const NON_TEXT_KEYS: [&str; 16] = [
    "return",
    "enter",
    "tab",
    "escape",
    "esc",
    "delete",
    "backspace",
    "forwarddelete",
    "up",
    "down",
    "left",
    "right",
    "home",
    "end",
    "pageup",
    "pagedown",
];

/// Whether pressing `keys` (a combo agent-desktop presses, `argv::combo_ok`) may put text into the
/// focused field: a key outside NON_TEXT_KEYS with no modifier, shift or option (which type
/// characters too, `option+e`), a paste (`cmd+v`), or Cocoa's `ctrl+y` / `ctrl+o`. Other cmd and
/// ctrl shortcuts do not.
pub fn keys_may_type(keys: &str) -> bool {
    let parts: Vec<&str> = keys.split('+').collect();
    let Some((key, mods)) = parts.split_last() else {
        return true;
    };
    let held = |names: [&str; 2]| mods.iter().any(|m| names.contains(m));
    if held(["cmd", "command"]) {
        return *key == "v";
    }
    if held(["ctrl", "control"]) {
        return matches!(*key, "y" | "o"); // Cocoa text: yank (the kill ring), open line
    }
    let function_key =
        key.len() > 1 && key.starts_with('f') && key[1..].bytes().all(|b| b.is_ascii_digit());
    !(NON_TEXT_KEYS.contains(key) || function_key)
}

/// Why `press` is refused, given whether the app's focused element is a password field (None: the
/// app did not say). "Arslan never types into password fields" holds for keys too (0.1.63): type and
/// set_value check their target; a press has none, so the focused element is asked. Unknown refuses
/// only keys that may type, so return and tab still work where an app leaves focus unanswered.
pub fn press_refusal(keys: &str, focused_secure: Option<bool>) -> Option<&'static str> {
    match focused_secure {
        Some(true) => {
            Some("the focused field is a password field; Arslan never types into password fields")
        }
        Some(false) => None,
        None if keys_may_type(keys) => Some(
            "this app did not say whether its focused field is a password field, and these keys \
             may type; Arslan never types into password fields",
        ),
        None => None,
    }
}

/// Whether a menu item puts text into the focused field: a paste, by its key equivalent (command
/// with `v`, whatever else is held: Paste, Paste and Match Style) or its English title. Not covered
/// (③Hands, #251): a paste item with no key equivalent and a title in another language.
pub fn menu_item_may_type(path: &[String], shortcut: Option<&(String, i64)>) -> bool {
    let paste_key = shortcut.is_some_and(|(key, bits)| key == "v" && bits & 8 == 0);
    let paste_title = path
        .last()
        .is_some_and(|title| title.to_lowercase().contains("paste"));
    paste_key || paste_title
}

/// Why a menu item is not pressed, given whether the app's focused element is a password field: a
/// menu item acts on that element as keys do (Edit › Paste is cmd+v), so the same rule as press.
pub fn menu_refusal(
    path: &[String],
    shortcut: Option<&(String, i64)>,
    focused_secure: Option<bool>,
) -> Option<&'static str> {
    match focused_secure {
        Some(true) => {
            Some("the focused field is a password field; Arslan presses no menu item into it")
        }
        Some(false) => None,
        None if menu_item_may_type(path, shortcut) => Some(
            "this app did not say whether its focused field is a password field, and this item \
             pastes; Arslan never types into password fields",
        ),
        None => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_press_into_a_focused_password_field_is_refused_and_unknown_refuses_only_typing_keys() {
        // (keys, focused secure, unknown): printable single keys, a modifier combo, non-printable keys.
        let cases = [
            ("a", true, true),
            ("1", true, true),
            ("space", true, true),
            ("shift+a", true, true),
            ("option+e", true, true),
            ("cmd+v", true, true),
            ("period", true, true), // a key name Hands does not know may type
            ("cmd+b", true, false),
            ("ctrl+a", true, false),
            ("shift+tab", true, false),
            ("return", true, false),
            ("tab", true, false),
            ("delete", true, false),
            ("escape", true, false),
            ("down", true, false),
            ("f12", true, false),
            ("ctrl+y", true, true), // yank
            ("ctrl+o", true, true),
            ("cmd+o", true, false),
            ("f", true, true),
        ];
        for (keys, refused_when_secure, refused_when_unknown) in cases {
            assert_eq!(
                press_refusal(keys, Some(true)).is_some(),
                refused_when_secure,
                "{keys} secure"
            );
            assert!(
                press_refusal(keys, Some(false)).is_none(),
                "{keys} not secure"
            );
            assert_eq!(
                press_refusal(keys, None).is_some(),
                refused_when_unknown,
                "{keys} unknown"
            );
        }
    }

    #[test]
    fn a_menu_item_that_pastes_is_refused_into_a_password_field_and_when_focus_is_unknown() {
        let path = |titles: &[&str]| titles.iter().map(|t| t.to_string()).collect::<Vec<_>>();
        let key = |c: &str, bits: i64| Some((c.to_string(), bits));
        // (path, key equivalent, pastes)
        let cases = [
            (path(&["Edit", "Paste"]), key("v", 0), true),
            (path(&["Edit", "Paste and Match Style"]), key("v", 3), true),
            (path(&["Edit", "粘贴"]), key("v", 0), true),
            (path(&["Edit", "Paste Special"]), None, true),
            (path(&["Format", "Font", "Bold"]), key("b", 0), false),
            (path(&["Edit", "Copy"]), key("c", 0), false),
            (path(&["View", "Page Down"]), key("v", 4 | 8), false), // ctrl+v, no command
        ];
        for (p, k, pastes) in cases {
            assert!(
                menu_refusal(&p, k.as_ref(), Some(true)).is_some(),
                "{p:?} secure"
            );
            assert!(
                menu_refusal(&p, k.as_ref(), Some(false)).is_none(),
                "{p:?} not secure"
            );
            assert_eq!(
                menu_refusal(&p, k.as_ref(), None).is_some(),
                pastes,
                "{p:?} unknown"
            );
        }
    }

    #[test]
    fn password_managers_settings_and_arslan_itself_are_denied() {
        for (bundle, name) in [
            ("com.apple.keychainaccess", "Keychain Access"),
            ("com.1password.1password", "1Password"),
            ("com.agilebits.onepassword7", "1Password 7"),
            ("com.apple.systempreferences", "System Settings"),
            ("com.apple.SecurityAgent", "SecurityAgent"),
            ("com.apple.notificationcenterui", "Notification Center"),
            ("com.arslan.desktop", "Arslan"),
            ("com.arslan.desktop.hands", "Arslan Hands"),
            ("com.arslan.desktop.hands.dev", "Arslan Hands (dev)"),
        ] {
            assert_eq!(tier(bundle, name, &[]), Tier::Denied, "{bundle}");
        }
        // A Team ID prefix does not hide an app (seen: 1Password's browser helper).
        assert_eq!(
            tier(
                "2BUA8C4S2C.com.1password.browser-helper",
                "1Password Browser Helper",
                &[]
            ),
            Tier::Denied
        );
        assert_eq!(
            tier("2BUA8C4S2C.com.apple.Safari", "x", &[]),
            Tier::LookOnly
        );
        assert_eq!(tier("com.notateam.app", "x", &[]), Tier::Full);
        // A renamed copy is still caught by its bundle id, and a missing bundle id by its name.
        assert_eq!(tier("com.1password.1password", "Vault", &[]), Tier::Denied);
        assert_eq!(tier("", "keychain access", &[]), Tier::Denied);
    }

    #[test]
    fn prefixes_match_whole_components_only() {
        assert!(bundle_matches("com.jetbrains.*", "com.jetbrains.pycharm"));
        assert!(!bundle_matches("com.jetbrains.*", "com.jetbrainsx.evil"));
        assert!(bundle_matches(
            "com.arslan.desktop.*",
            "com.arslan.desktop.hands"
        ));
        assert!(!bundle_matches(
            "com.arslan.desktop.*",
            "com.arslan.desktopx"
        ));
    }

    #[test]
    fn browsers_look_terminals_click_everything_else_acts() {
        assert_eq!(tier("com.apple.Safari", "Safari", &[]), Tier::LookOnly);
        assert_eq!(tier("com.apple.Terminal", "Terminal", &[]), Tier::ClickOnly);
        assert_eq!(
            tier("com.jetbrains.pycharm", "PyCharm", &[]),
            Tier::ClickOnly
        );
        assert_eq!(tier("com.apple.Notes", "Notes", &[]), Tier::Full);
        assert_eq!(tier("com.apple.finder", "Finder", &[]), Tier::Full);
    }

    #[test]
    fn the_user_can_add_but_not_remove() {
        let extra = vec!["Notes".to_string(), "com.example.*".to_string()];
        assert_eq!(tier("com.apple.Notes", "Notes", &extra), Tier::Denied);
        assert_eq!(tier("com.example.app", "Thing", &extra), Tier::Denied);
        // Nothing the backend sends can lift a built-in denial.
        assert_eq!(
            tier("com.apple.keychainaccess", "Keychain Access", &["".into()]),
            Tier::Denied
        );
    }

    #[test]
    fn tiers_allow_exactly_their_operations() {
        for op in [
            "snapshot",
            "find",
            "get",
            "wait",
            "list_windows",
            "describe",
        ] {
            assert!(
                allows(Tier::LookOnly, op) && allows(Tier::ClickOnly, op) && allows(Tier::Full, op)
            );
            assert!(!allows(Tier::Denied, op));
        }
        for op in ["click", "scroll"] {
            assert!(
                !allows(Tier::LookOnly, op)
                    && allows(Tier::ClickOnly, op)
                    && allows(Tier::Full, op)
            );
        }
        for op in ["type", "set_value", "select", "press"] {
            assert!(!allows(Tier::ClickOnly, op) && allows(Tier::Full, op));
        }
        assert!(!allows(Tier::Full, "screenshot") && !allows(Tier::Full, "launch"));
    }

    #[test]
    fn messaging_apps_send_on_return() {
        assert!(sends_on_return("com.apple.MobileSMS", "Messages"));
        assert!(sends_on_return("com.tinyspeck.slackmacgap", "Slack"));
        assert!(!sends_on_return("com.apple.Notes", "Notes"));
    }
}

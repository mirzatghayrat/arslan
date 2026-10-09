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

#[cfg(test)]
mod tests {
    use super::*;

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

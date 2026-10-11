//! Which running app a request means (spec 2026-10-08-0157 §15 A19). An app's name is not unique
//! on a real Mac: WeChat's mini-program helper WeChatAppEx is also called "WeChat", and every
//! running Claude Code session is listed as "claude" (no bundle id) beside the Claude app. So the
//! candidates — those with that exact bundle id if any, else those with that name, any case — are
//! narrowed, in order, until one is left (a step that would leave none is skipped): apps with a
//! Dock icon over helpers and processes; the exact name, case and all; the app in front; an app
//! with a window on some desktop. Several left: the request is ambiguous.

use std::sync::Mutex;

/// A running app, as agent-desktop lists it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Candidate {
    pub name: String,
    pub bundle_id: String,
    pub pid: i64,
}

/// What the resolver asks about the candidates (macOS in the app; tests stand in).
pub trait Facts {
    /// The app has a Dock icon (NSApplicationActivationPolicyRegular).
    fn regular(&self, pid: i64) -> bool;
    /// The app in front.
    fn front(&self) -> Option<i64>;
    /// The app has a window on some desktop.
    fn has_window(&self, pid: i64) -> bool;
}

#[derive(Debug, PartialEq, Eq)]
pub enum Choice {
    /// The index of the one app meant.
    One(usize),
    None,
    /// The indexes of the apps still left.
    Several(Vec<usize>),
}

/// The app `wanted` (a bundle id or a name) means among `apps`.
pub fn choose(apps: &[Candidate], wanted: &str, facts: &dyn Facts) -> Choice {
    let wanted = wanted.trim();
    let by_bundle: Vec<usize> = (0..apps.len())
        .filter(|&i| {
            !apps[i].bundle_id.is_empty() && apps[i].bundle_id.eq_ignore_ascii_case(wanted)
        })
        .collect();
    let mut left = if by_bundle.is_empty() {
        (0..apps.len())
            .filter(|&i| apps[i].name.eq_ignore_ascii_case(wanted))
            .collect()
    } else {
        by_bundle
    };
    if left.is_empty() {
        return Choice::None;
    }
    narrow(&mut left, |i| facts.regular(apps[i].pid));
    narrow(&mut left, |i| apps[i].name == wanted);
    if left.len() > 1 {
        if let Some(front) = facts.front() {
            narrow(&mut left, |i| apps[i].pid == front);
        }
    }
    narrow(&mut left, |i| facts.has_window(apps[i].pid));
    match left.as_slice() {
        [one] => Choice::One(*one),
        _ => Choice::Several(left),
    }
}

/// Keep those `keep` says, unless that is none of them.
fn narrow(left: &mut Vec<usize>, keep: impl Fn(usize) -> bool) {
    if left.len() <= 1 {
        return;
    }
    let kept: Vec<usize> = left.iter().copied().filter(|&i| keep(i)).collect();
    if !kept.is_empty() {
        *left = kept;
    }
}

/// Another running app has `chosen`'s name (any case): agent-desktop, which finds apps by name,
/// would refuse it, so Hands reaches the app through one of its windows instead.
pub fn name_shared(apps: &[Candidate], chosen: &Candidate) -> bool {
    apps.iter()
        .filter(|a| a.name.eq_ignore_ascii_case(&chosen.name))
        .count()
        > 1
}

/// Tests (fake pids, no macOS to ask) stand in for the facts; only Rust code in this process can.
#[derive(Clone, Copy)]
pub struct TestFacts {
    pub regular: fn(i64) -> bool,
    pub front: Option<i64>,
    pub has_window: fn(i64) -> bool,
}

static TEST_FACTS: Mutex<Option<TestFacts>> = Mutex::new(None);

pub fn set_facts_for_tests(facts: Option<TestFacts>) {
    *TEST_FACTS.lock().unwrap_or_else(|p| p.into_inner()) = facts;
}

/// The facts the running Hands uses: the test stand-in if set, else macOS.
pub struct Live;

impl Facts for Live {
    fn regular(&self, pid: i64) -> bool {
        if let Some(t) = *TEST_FACTS.lock().unwrap_or_else(|p| p.into_inner()) {
            return (t.regular)(pid);
        }
        #[cfg(target_os = "macos")]
        {
            i32::try_from(pid).is_ok_and(crate::macos::is_regular_app)
        }
        #[cfg(not(target_os = "macos"))]
        {
            false
        }
    }

    fn front(&self) -> Option<i64> {
        if let Some(t) = *TEST_FACTS.lock().unwrap_or_else(|p| p.into_inner()) {
            return t.front;
        }
        #[cfg(target_os = "macos")]
        {
            crate::macos::frontmost_pid().map(i64::from)
        }
        #[cfg(not(target_os = "macos"))]
        {
            None
        }
    }

    fn has_window(&self, pid: i64) -> bool {
        if let Some(t) = *TEST_FACTS.lock().unwrap_or_else(|p| p.into_inner()) {
            return (t.has_window)(pid);
        }
        let Ok(pid) = i32::try_from(pid) else {
            return false;
        };
        let windows = crate::spaces::windows(pid);
        windows.on_screen > 0 || windows.elsewhere > 0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn app(name: &str, bundle_id: &str, pid: i64) -> Candidate {
        Candidate {
            name: name.into(),
            bundle_id: bundle_id.into(),
            pid,
        }
    }

    struct Mac {
        regular: Vec<i64>,
        front: Option<i64>,
        windows: Vec<i64>,
    }

    impl Facts for Mac {
        fn regular(&self, pid: i64) -> bool {
            self.regular.contains(&pid)
        }
        fn front(&self) -> Option<i64> {
            self.front
        }
        fn has_window(&self, pid: i64) -> bool {
            self.windows.contains(&pid)
        }
    }

    /// The user's Mac, 2026-10-11: two "WeChat", and Claude beside three Claude Code sessions.
    fn the_users_mac() -> (Vec<Candidate>, Mac) {
        (
            vec![
                app("WeChat", "com.tencent.flue.WeChatAppEx", 1279),
                app("claude", "", 7001),
                app("Claude", "com.anthropic.claudefordesktop", 642),
                app("claude", "", 7002),
                app("WeChat", "com.tencent.xinWeChat", 630),
                app("claude", "", 7003),
                app("Notes", "com.apple.Notes", 900),
            ],
            Mac {
                regular: vec![630, 642, 900],
                front: Some(900),
                windows: vec![630, 642, 900],
            },
        )
    }

    #[test]
    fn wechat_is_the_app_with_a_dock_icon_not_its_helper() {
        let (apps, mac) = the_users_mac();
        assert_eq!(choose(&apps, "WeChat", &mac), Choice::One(4));
        assert_eq!(choose(&apps, "wechat", &mac), Choice::One(4));
        assert_eq!(
            choose(&apps, "com.tencent.flue.WeChatAppEx", &mac),
            Choice::One(0),
            "an exact bundle id is that app, helper or not"
        );
        assert!(
            name_shared(&apps, &apps[4]),
            "agent-desktop must not get the name"
        );
        assert!(!name_shared(&apps, &apps[6]));
    }

    #[test]
    fn claude_is_the_app_not_the_claude_code_sessions_whatever_the_case() {
        let (apps, mac) = the_users_mac();
        assert_eq!(choose(&apps, "Claude", &mac), Choice::One(2));
        assert_eq!(choose(&apps, "claude", &mac), Choice::One(2));
        assert_eq!(
            choose(&apps, "com.anthropic.claudefordesktop", &mac),
            Choice::One(2)
        );
    }

    #[test]
    fn the_exact_name_then_the_front_then_a_window_break_a_tie() {
        let apps = vec![
            app("Fixture", "a", 1),
            app("fixture", "b", 2),
            app("Fixture", "c", 3),
        ];
        let all = Mac {
            regular: vec![1, 2, 3],
            front: None,
            windows: vec![1, 2, 3],
        };
        assert_eq!(
            choose(&apps, "fixture", &all),
            Choice::One(1),
            "the exact name"
        );
        let front = Mac {
            front: Some(3),
            ..all
        };
        assert_eq!(
            choose(&apps, "Fixture", &front),
            Choice::One(2),
            "the app in front"
        );
        let windowed = Mac {
            regular: vec![1, 3],
            front: Some(99),
            windows: vec![3],
        };
        assert_eq!(
            choose(&apps, "Fixture", &windowed),
            Choice::One(2),
            "the one with a window"
        );
    }

    #[test]
    fn a_step_that_would_leave_none_is_skipped_and_a_true_tie_stays_several() {
        let apps = vec![
            app("Twin", "x", 1),
            app("Twin", "x", 2),
            app("Other", "y", 3),
        ];
        let none = Mac {
            regular: vec![],
            front: Some(3),
            windows: vec![],
        };
        assert_eq!(choose(&apps, "Twin", &none), Choice::Several(vec![0, 1]));
        assert_eq!(choose(&apps, "x", &none), Choice::Several(vec![0, 1]));
        assert_eq!(choose(&apps, "Nothing", &none), Choice::None);
        assert_eq!(choose(&apps, "", &none), Choice::None);
    }
}

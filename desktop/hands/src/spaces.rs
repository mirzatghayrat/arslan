//! Which desktop an app's windows are on (spec 2026-10-08-0157 §15 A18): src/spaces.m counts them
//! through the window server, which — unlike accessibility — sees every desktop.

use std::sync::Mutex;

/// An app's ordinary windows: on the desktops being shown, and elsewhere.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Windows {
    pub on_screen: usize,
    pub elsewhere: usize,
}

type Probe = fn(i32) -> Windows;

/// Tests (fake pids, no window server) stand in here; only Rust code in this process can set it.
static PROBE: Mutex<Option<Probe>> = Mutex::new(None);

pub fn set_probe_for_tests(probe: Option<Probe>) {
    *PROBE.lock().unwrap_or_else(|p| p.into_inner()) = probe;
}

#[cfg(target_os = "macos")]
extern "C" {
    fn hands_app_windows(pid: i32, on_screen: *mut i32, elsewhere: *mut i32) -> i32;
}

pub fn windows(pid: i32) -> Windows {
    if let Some(probe) = *PROBE.lock().unwrap_or_else(|p| p.into_inner()) {
        return probe(pid);
    }
    #[cfg(target_os = "macos")]
    {
        let (mut on_screen, mut elsewhere) = (0i32, 0i32);
        // SAFETY: two out-parameters this function owns; spaces.m writes both before returning.
        if unsafe { hands_app_windows(pid, &mut on_screen, &mut elsewhere) } != 0 {
            return Windows::default();
        }
        Windows {
            on_screen: on_screen.max(0) as usize,
            elsewhere: elsewhere.max(0) as usize,
        }
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = pid;
        Windows::default()
    }
}

/// The app's windows are all on another desktop: accessibility (which sees only the desktops being
/// shown) lists none of them, and the window server lists some that are not on screen.
/// `ax_windows`: how many windows accessibility lists (None when it could not be read: then
/// nothing is assumed, and nothing is gone to).
pub fn elsewhere(ax_windows: Option<usize>, windows: Windows) -> bool {
    ax_windows == Some(0) && windows.on_screen == 0 && windows.elsewhere > 0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn windows_only_elsewhere_and_none_in_accessibility_are_on_another_desktop() {
        let away = Windows {
            on_screen: 0,
            elsewhere: 2,
        };
        assert!(elsewhere(Some(0), away));
        assert!(
            !elsewhere(Some(1), away),
            "accessibility sees one: it is here (a minimized one counts too)"
        );
        assert!(
            !elsewhere(None, away),
            "accessibility unreadable: assume nothing"
        );
        assert!(!elsewhere(
            Some(0),
            Windows {
                on_screen: 1,
                elsewhere: 2
            }
        ));
        assert!(
            !elsewhere(Some(0), Windows::default()),
            "no window at all: nothing to go to"
        );
    }
}

//! Which desktop an app's windows are on (spec 2026-10-08-0157 §15 A18): src/spaces.m lists them
//! through the window server, which — unlike accessibility — sees every desktop, and gives AppKit's
//! list of windows ordered in on every desktop, which tells a window on another desktop from a
//! closed one the app keeps (the window server lists both as "not on screen").

use std::sync::Mutex;

/// An app's ordinary windows: on the desktops being shown, and — counted only when none is — on
/// another desktop (a closed window the app keeps, or a minimized one, is not elsewhere).
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Windows {
    pub on_screen: usize,
    pub elsewhere: usize,
}

/// One of an app's ordinary windows, as the window server lists it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Listed {
    pub number: u32,
    pub on_screen: bool,
}

/// Counts `listed`: on screen; and, only when none is, those that are ordered in on another
/// desktop. `ordered_in`: AppKit's numbers of every window ordered in on any desktop, None when it
/// did not answer — then nothing is assumed to be elsewhere (and nothing is gone to).
pub fn count(listed: &[Listed], ordered_in: Option<&[u32]>) -> Windows {
    let on_screen = listed.iter().filter(|w| w.on_screen).count();
    let elsewhere = match ordered_in {
        Some(ordered) if on_screen == 0 => listed
            .iter()
            .filter(|w| !w.on_screen && ordered.contains(&w.number))
            .count(),
        _ => 0,
    };
    Windows {
        on_screen,
        elsewhere,
    }
}

type Probe = fn(i32) -> Windows;

/// Tests (fake pids, no window server) stand in here; only Rust code in this process can set it.
static PROBE: Mutex<Option<Probe>> = Mutex::new(None);

pub fn set_probe_for_tests(probe: Option<Probe>) {
    *PROBE.lock().unwrap_or_else(|p| p.into_inner()) = probe;
}

#[cfg(target_os = "macos")]
extern "C" {
    fn hands_app_window_list(
        pid: i32,
        shown_only: i32,
        numbers: *mut u32,
        on_screen: *mut u8,
        cap: i32,
    ) -> i32;
    fn hands_ordered_in_everywhere(numbers: *mut u32, cap: i32) -> i32;
    fn hands_shown_windows(numbers: *mut u32, owners: *mut i32, cap: i32) -> i32;
}

/// App `pid`'s ordinary windows (all of them, or only those on screen); None when the window
/// server did not answer.
#[cfg(target_os = "macos")]
fn listed(pid: i32, shown_only: bool) -> Option<Vec<Listed>> {
    const CAP: usize = 512;
    let mut numbers = vec![0u32; CAP];
    let mut on_screen = vec![0u8; CAP];
    // SAFETY: both buffers hold CAP entries and spaces.m writes at most `cap` of each.
    let n = unsafe {
        hands_app_window_list(
            pid,
            i32::from(shown_only),
            numbers.as_mut_ptr(),
            on_screen.as_mut_ptr(),
            CAP as i32,
        )
    };
    let n = usize::try_from(n).ok()?.min(CAP);
    Some(
        (0..n)
            .map(|i| Listed {
                number: numbers[i],
                on_screen: on_screen[i] != 0,
            })
            .collect(),
    )
}

/// AppKit's numbers of every window ordered in on any desktop, all apps; None when it did not
/// answer.
#[cfg(target_os = "macos")]
pub fn ordered_in_everywhere() -> Option<Vec<u32>> {
    let mut cap = 4096usize;
    loop {
        let mut numbers = vec![0u32; cap];
        // SAFETY: the buffer holds `cap` entries and spaces.m writes at most `cap`.
        let n = unsafe { hands_ordered_in_everywhere(numbers.as_mut_ptr(), cap as i32) };
        let n = usize::try_from(n).ok()?;
        if n <= cap {
            numbers.truncate(n);
            return Some(numbers);
        }
        cap = n; // more windows than room: ask again with room for all
    }
}

/// Every ordinary window on screen, all apps, front to back: (window number, its app's pid).
/// None when the window server did not answer.
#[cfg(target_os = "macos")]
pub fn shown() -> Option<Vec<(u32, i32)>> {
    const CAP: usize = 1024;
    let mut numbers = vec![0u32; CAP];
    let mut owners = vec![0i32; CAP];
    // SAFETY: both buffers hold CAP entries and spaces.m writes at most `cap` of each.
    let n = unsafe { hands_shown_windows(numbers.as_mut_ptr(), owners.as_mut_ptr(), CAP as i32) };
    let n = usize::try_from(n).ok()?.min(CAP);
    Some((0..n).map(|i| (numbers[i], owners[i])).collect())
}

#[cfg(not(target_os = "macos"))]
pub fn shown() -> Option<Vec<(u32, i32)>> {
    None
}

#[cfg(not(target_os = "macos"))]
pub fn ordered_in_everywhere() -> Option<Vec<u32>> {
    None
}

/// Of the windows that were on screen before a visit (`before`: number, app pid), those not back:
/// not on screen now (`shown_now`) though still ordered in on some desktop (`ordered_in`; None when
/// AppKit did not answer: then each is taken to still exist). A window closed meanwhile is not
/// waited for.
pub fn missing(
    before: &[(u32, i32)],
    shown_now: &[u32],
    ordered_in: Option<&[u32]>,
) -> Vec<(u32, i32)> {
    before
        .iter()
        .filter(|(number, _)| {
            !shown_now.contains(number) && ordered_in.map_or(true, |o| o.contains(number))
        })
        .copied()
        .collect()
}

pub fn windows(pid: i32) -> Windows {
    if let Some(probe) = *PROBE.lock().unwrap_or_else(|p| p.into_inner()) {
        return probe(pid);
    }
    #[cfg(target_os = "macos")]
    {
        // The cheap list of windows on screen answers nearly every request.
        let Some(shown) = listed(pid, true) else {
            return Windows::default();
        };
        if !shown.is_empty() {
            return count(&shown, None);
        }
        let Some(all) = listed(pid, false) else {
            return Windows::default();
        };
        if all.is_empty() {
            return Windows::default();
        }
        count(&all, ordered_in_everywhere().as_deref())
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = pid;
        Windows::default()
    }
}

/// The app's windows are all on another desktop: accessibility (which sees only the desktops being
/// shown) lists none of them, and the window server lists some that are ordered in elsewhere.
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

    const SHOWN: Listed = Listed {
        number: 10,
        on_screen: true,
    };
    // Off screen and ordered in on another desktop (AppKit lists it).
    const AWAY: Listed = Listed {
        number: 20,
        on_screen: false,
    };
    // Off screen and not ordered in anywhere: a closed window the app keeps (Finder, Music).
    const CLOSED: Listed = Listed {
        number: 30,
        on_screen: false,
    };
    const ORDERED: &[u32] = &[10, 20, 99];

    #[test]
    fn a_closed_window_the_app_keeps_is_not_on_another_desktop() {
        assert_eq!(
            count(&[CLOSED], Some(ORDERED)),
            Windows::default(),
            "nothing to go to: going there would show nothing"
        );
        assert_eq!(
            count(&[CLOSED, AWAY], Some(ORDERED)),
            Windows {
                on_screen: 0,
                elsewhere: 1
            }
        );
    }

    #[test]
    fn coming_back_waits_for_every_window_that_was_on_screen_and_still_exists() {
        let before = [(10, 1), (20, 2), (30, 3)];
        assert!(missing(&before, &[30, 10, 20, 99], Some(&[10, 20, 30])).is_empty());
        assert_eq!(
            missing(&before, &[10], Some(&[10, 20, 30])),
            vec![(20, 2), (30, 3)],
            "front to back, as they were"
        );
        assert_eq!(
            missing(&before, &[10, 20], Some(&[10, 20])),
            Vec::<(u32, i32)>::new(),
            "30 was closed meanwhile: nothing to wait for"
        );
        assert_eq!(
            missing(&before, &[10, 20], None),
            vec![(30, 3)],
            "AppKit did not answer: taken to still exist"
        );
    }

    #[test]
    fn elsewhere_is_counted_only_when_nothing_is_on_screen_and_appkit_answered() {
        assert_eq!(
            count(&[SHOWN, AWAY], Some(ORDERED)),
            Windows {
                on_screen: 1,
                elsewhere: 0
            }
        );
        assert_eq!(
            count(&[AWAY], None),
            Windows::default(),
            "AppKit did not answer: assume nothing"
        );
    }
}

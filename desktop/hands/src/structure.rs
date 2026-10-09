//! The structural-change check (spec 2026-10-08-0157 §4.6, §15 A2 item 3 and A8): at each look
//! Hands notes an app's structure — its windows, the sheets and dialogs on them, which window
//! is in front, whether a menu is open — and before every action it reads it again. If it
//! differs, the action is refused (`changed`): the look it was planned on is out of date (in
//! the bake-off every engine but arc pressed a button under a sheet that opened after the look).
//!
//! Windows are told apart by their accessibility element (its CFHash), never by title: a
//! document's title changes as it is edited, and that is not a change of structure. Values are
//! not structure either, so several actions on one look still work.

/// One window of the app, as accessibility reports it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Window {
    /// Identity: the window element's CFHash (stable while the window exists).
    pub id: u64,
    /// AXStandardWindow, AXDialog, AXFloatingWindow… (a dialog is its own window).
    pub subrole: String,
    /// For telling the model what changed; never compared.
    pub title: String,
    /// Sheets, drawers and popovers attached to it.
    pub sheets: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Structure {
    pub windows: Vec<Window>,
    /// The id of the app's focused window.
    pub focused: Option<u64>,
    /// A menu of the app is open (its focused element is a menu or menu item).
    pub menu_open: bool,
}

type Probe = fn(i32) -> Option<Structure>;

/// Tests (which run Hands in-process with fake pids) stand in for accessibility here. Only Rust
/// code in the same process can set it; nothing a request carries reaches it.
static PROBE: std::sync::Mutex<Option<Probe>> = std::sync::Mutex::new(None);

pub fn set_probe_for_tests(probe: Option<Probe>) {
    *PROBE.lock().unwrap_or_else(|p| p.into_inner()) = probe;
}

/// App `pid`'s structure now, or None when it cannot be read (then nothing is compared).
pub fn read(pid: i64) -> Option<Structure> {
    let pid = i32::try_from(pid).ok()?;
    if let Some(probe) = *PROBE.lock().unwrap_or_else(|p| p.into_inner()) {
        return probe(pid);
    }
    #[cfg(target_os = "macos")]
    {
        crate::macos::structure(pid)
    }
    #[cfg(not(target_os = "macos"))]
    {
        None
    }
}

fn named(window: &Window) -> String {
    if window.title.is_empty() {
        "a window".to_string()
    } else {
        format!("“{}”", window.title.chars().take(60).collect::<String>())
    }
}

/// What changed from `before` (the look) to `now`, in words; empty when nothing structural did.
pub fn changes(before: &Structure, now: &Structure) -> Vec<String> {
    let mut out = Vec::new();
    for window in &now.windows {
        match before.windows.iter().find(|w| w.id == window.id) {
            None => out.push(format!("{} opened", named(window))),
            Some(old) if window.sheets > old.sheets => {
                out.push(format!("a sheet or popover opened on {}", named(window)))
            }
            Some(old) if window.sheets < old.sheets => {
                out.push(format!("a sheet or popover closed on {}", named(window)))
            }
            Some(old) if old.subrole != window.subrole => {
                out.push(format!("{} changed kind", named(window)))
            }
            _ => {}
        }
    }
    for window in &before.windows {
        if !now.windows.iter().any(|w| w.id == window.id) {
            out.push(format!("{} closed", named(window)));
        }
    }
    if now.focused != before.focused && now.focused.is_some() {
        let front = now.windows.iter().find(|w| Some(w.id) == now.focused);
        out.push(format!(
            "{} is now the app's front window",
            front.map(named).unwrap_or_else(|| "another window".into())
        ));
    }
    if now.menu_open && !before.menu_open {
        out.push("a menu is open".into());
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn window(id: u64, title: &str, sheets: usize) -> Window {
        Window {
            id,
            subrole: "AXStandardWindow".into(),
            title: title.into(),
            sheets,
        }
    }

    fn look() -> Structure {
        Structure {
            windows: vec![window(1, "Groceries", 0), window(2, "Ideas", 0)],
            focused: Some(1),
            menu_open: false,
        }
    }

    #[test]
    fn a_title_or_order_change_is_not_structure() {
        let mut now = look();
        now.windows.reverse();
        now.windows[1].title = "Groceries — Edited".into();
        assert!(changes(&look(), &now).is_empty());
    }

    #[test]
    fn a_sheet_a_new_window_a_closed_one_the_front_and_a_menu_are() {
        let mut sheet = look();
        sheet.windows[0].sheets = 1;
        assert_eq!(
            changes(&look(), &sheet),
            ["a sheet or popover opened on “Groceries”"]
        );

        let mut opened = look();
        opened.windows.push(Window {
            subrole: "AXDialog".into(),
            ..window(3, "Save changes?", 0)
        });
        opened.focused = Some(3);
        assert_eq!(
            changes(&look(), &opened),
            [
                "“Save changes?” opened",
                "“Save changes?” is now the app's front window"
            ]
        );

        let mut closed = look();
        closed.windows.remove(1);
        assert_eq!(changes(&look(), &closed), ["“Ideas” closed"]);

        let mut menu = look();
        menu.menu_open = true;
        assert_eq!(changes(&look(), &menu), ["a menu is open"]);

        let mut front = look();
        front.focused = Some(2);
        assert_eq!(
            changes(&look(), &front),
            ["“Ideas” is now the app's front window"]
        );
    }

    #[test]
    fn a_sheet_closing_is_said_too() {
        let mut before = look();
        before.windows[0].sheets = 1;
        assert_eq!(
            changes(&before, &look()),
            ["a sheet or popover closed on “Groceries”"]
        );
    }
}

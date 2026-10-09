//! Menus pressed in the background (spec 2026-10-08-0157 §5.5, §15 A2 item 4 and A8): Hands
//! reads an app's menu bar through accessibility and presses an item by its path, or — when a
//! key combo cannot be delivered to an app with nothing focused — the item that has that combo
//! as its shortcut. The system's Apple menu is never read or pressed (macos.rs skips it).

/// One item of an app's menu bar.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MenuItem {
    /// Titles, top level first: ["Format", "Font", "Bold"].
    pub path: Vec<String>,
    pub enabled: bool,
    /// Its key equivalent: the character (lower case) and the AXMenuItemCmdModifiers bits
    /// (1 shift, 2 option, 4 control, 8 = without command).
    pub shortcut: Option<(String, i64)>,
}

type Reader = fn(i32) -> Option<Vec<MenuItem>>;
type Presser = fn(i32, &[String]) -> Option<bool>;

/// Tests (Hands in-process, fake pids) stand in for accessibility here; only Rust code in the
/// same process can set it.
static STAND_IN: std::sync::Mutex<Option<(Reader, Presser)>> = std::sync::Mutex::new(None);

pub fn set_stand_in_for_tests(stand_in: Option<(Reader, Presser)>) {
    *STAND_IN.lock().unwrap_or_else(|p| p.into_inner()) = stand_in;
}

pub fn read(pid: i64) -> Option<Vec<MenuItem>> {
    let pid = i32::try_from(pid).ok()?;
    if let Some((reader, _)) = *STAND_IN.lock().unwrap_or_else(|p| p.into_inner()) {
        return reader(pid);
    }
    #[cfg(target_os = "macos")]
    {
        crate::macos::menu_items(pid)
    }
    #[cfg(not(target_os = "macos"))]
    {
        None
    }
}

pub fn press(pid: i64, path: &[String]) -> Option<bool> {
    let pid = i32::try_from(pid).ok()?;
    if let Some((_, presser)) = *STAND_IN.lock().unwrap_or_else(|p| p.into_inner()) {
        return presser(pid, path);
    }
    #[cfg(target_os = "macos")]
    {
        crate::macos::press_menu_item(pid, path)
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = path;
        None
    }
}

/// Titles compared as a person reads them: case, surrounding space and "…" vs "..." ignored.
pub fn same_title(a: &str, b: &str) -> bool {
    let norm = |s: &str| s.trim().replace('…', "...").to_lowercase();
    norm(a) == norm(b)
}

/// Why a path cannot be pressed.
#[derive(Debug, PartialEq, Eq)]
pub enum NotThere {
    /// No such item; the titles that exist where the path stopped matching.
    Missing(Vec<String>),
    Disabled,
    Ambiguous,
}

/// The one menu item `wanted` names.
pub fn find<'a>(items: &'a [MenuItem], wanted: &[String]) -> Result<&'a MenuItem, NotThere> {
    let matching: Vec<&MenuItem> = items
        .iter()
        .filter(|i| {
            i.path.len() == wanted.len() && i.path.iter().zip(wanted).all(|(a, b)| same_title(a, b))
        })
        .collect();
    match matching.as_slice() {
        [] => {
            // The deepest level the path still matched, and what is there.
            let mut depth = 0;
            while depth < wanted.len()
                && items.iter().any(|i| {
                    i.path.len() > depth
                        && i.path[..=depth]
                            .iter()
                            .zip(&wanted[..=depth])
                            .all(|(a, b)| same_title(a, b))
                })
            {
                depth += 1;
            }
            let mut there: Vec<String> = Vec::new();
            for i in items.iter().filter(|i| {
                i.path.len() > depth
                    && i.path[..depth]
                        .iter()
                        .zip(&wanted[..depth])
                        .all(|(a, b)| same_title(a, b))
            }) {
                if !there.contains(&i.path[depth]) && there.len() < 40 {
                    there.push(i.path[depth].clone());
                }
            }
            Err(NotThere::Missing(there))
        }
        [one] if !one.enabled => Err(NotThere::Disabled),
        [one] => Ok(one),
        _ => Err(NotThere::Ambiguous),
    }
}

/// A combo as Hands' `press` takes it ("cmd+shift+b") → (character, AX modifier bits), for
/// combos with command or control only (plain keys are never menu shortcuts here).
pub fn combo(keys: &str) -> Option<(String, i64)> {
    let parts: Vec<String> = keys.split('+').map(|p| p.trim().to_lowercase()).collect();
    let (key, mods) = parts.split_last()?;
    if key.chars().count() != 1 {
        return None;
    }
    let mut bits = 8; // without command, until cmd is seen
    let mut any = false;
    for m in mods {
        match m.as_str() {
            "cmd" | "command" => {
                bits &= !8;
                any = true
            }
            "ctrl" | "control" => {
                bits |= 4;
                any = true
            }
            "shift" => bits |= 1,
            "alt" | "option" | "opt" => bits |= 2,
            _ => return None,
        }
    }
    any.then(|| (key.clone(), bits))
}

/// The enabled item whose shortcut is `keys`, if exactly one.
pub fn by_shortcut<'a>(items: &'a [MenuItem], keys: &str) -> Option<&'a MenuItem> {
    let wanted = combo(keys)?;
    let mut found = items
        .iter()
        .filter(|i| i.enabled && i.shortcut.as_ref() == Some(&wanted));
    let one = found.next()?;
    found.next().is_none().then_some(one)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn item(path: &[&str], enabled: bool, shortcut: Option<(&str, i64)>) -> MenuItem {
        MenuItem {
            path: path.iter().map(|s| s.to_string()).collect(),
            enabled,
            shortcut: shortcut.map(|(c, m)| (c.to_string(), m)),
        }
    }

    fn bar() -> Vec<MenuItem> {
        vec![
            item(&["File", "New"], true, Some(("n", 0))),
            item(&["File", "Save…"], true, Some(("s", 0))),
            item(&["File", "Export"], false, None),
            item(&["Format", "Font", "Bold"], true, Some(("b", 0))),
            item(&["Format", "Font", "Bigger"], true, Some(("+", 0))),
            item(&["Edit", "Find"], true, Some(("f", 0))),
            item(&["Edit", "Find Next"], true, Some(("g", 0))),
            item(&["Window", "Zoom"], true, None),
            item(&["Window", "Zoom"], true, None),
        ]
    }

    fn path(p: &[&str]) -> Vec<String> {
        p.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn a_path_is_matched_as_read_and_ellipses_are_one() {
        assert_eq!(
            find(&bar(), &path(&["file", "Save..."])).unwrap().path[1],
            "Save…"
        );
        assert_eq!(
            find(&bar(), &path(&["Format", "Font", "Bold"]))
                .unwrap()
                .shortcut,
            Some(("b".into(), 0))
        );
    }

    #[test]
    fn missing_disabled_and_ambiguous_are_said() {
        assert_eq!(
            find(&bar(), &path(&["File", "Export"])),
            Err(NotThere::Disabled)
        );
        assert_eq!(
            find(&bar(), &path(&["Window", "Zoom"])),
            Err(NotThere::Ambiguous)
        );
        assert_eq!(
            find(&bar(), &path(&["Format", "Font", "Italic"])),
            Err(NotThere::Missing(vec!["Bold".into(), "Bigger".into()]))
        );
        assert_eq!(
            find(&bar(), &path(&["Fiel", "New"])),
            Err(NotThere::Missing(vec![
                "File".into(),
                "Format".into(),
                "Edit".into(),
                "Window".into()
            ]))
        );
    }

    #[test]
    fn combos_become_ax_modifier_bits() {
        assert_eq!(combo("cmd+b"), Some(("b".into(), 0)));
        assert_eq!(combo("Cmd+Shift+S"), Some(("s".into(), 1)));
        assert_eq!(combo("cmd+option+i"), Some(("i".into(), 2)));
        assert_eq!(combo("ctrl+a"), Some(("a".into(), 12)));
        assert_eq!(combo("b"), None, "a plain key is not a menu shortcut");
        assert_eq!(combo("shift+b"), None);
        assert_eq!(combo("cmd+return"), None);
        assert_eq!(combo("cmd+hyper+b"), None);
    }

    #[test]
    fn a_shortcut_finds_its_one_enabled_item() {
        assert_eq!(
            by_shortcut(&bar(), "cmd+b").unwrap().path,
            path(&["Format", "Font", "Bold"])
        );
        assert!(by_shortcut(&bar(), "cmd+shift+b").is_none());
        let mut twice = bar();
        twice.push(item(&["View", "Bold too"], true, Some(("b", 0))));
        assert!(
            by_shortcut(&twice, "cmd+b").is_none(),
            "two items: not guessed"
        );
        let mut off = bar();
        off[3].enabled = false;
        assert!(
            by_shortcut(&off, "cmd+b").is_none(),
            "a disabled item is not pressed"
        );
    }
}

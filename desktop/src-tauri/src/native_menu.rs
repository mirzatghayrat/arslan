//! Localized labels on native menu roles; no replacement JS action handlers.
use std::sync::Mutex;
use tauri::menu::{
    AboutMetadata, IsMenuItem, Menu, MenuItem, MenuItemKind, PredefinedMenuItem, Submenu,
};
use tauri::{AppHandle, Manager, Wry};

pub struct NativeMenu {
    labels: Vec<(MenuItemKind<Wry>, &'static str)>,
    locale: Mutex<&'static str>,
}

fn text(locale: &str, key: &str) -> String {
    if key == "check_title" {
        return crate::native_locale::text(locale, key);
    }
    static COPY: std::sync::OnceLock<serde_json::Value> = std::sync::OnceLock::new();
    let copy = COPY.get_or_init(|| {
        serde_json::from_str(include_str!("../native_menu_messages.json")).unwrap()
    });
    copy.get(locale)
        .and_then(|row| row.get(key))
        .or_else(|| copy["en"].get(key))
        .and_then(|value| value.as_str())
        .unwrap_or("Arslan")
        .to_string()
}

fn labelled<T: IsMenuItem<Wry>>(
    labels: &mut Vec<(MenuItemKind<Wry>, &'static str)>,
    item: T,
    key: &'static str,
) -> T {
    labels.push((item.kind(), key));
    item
}

pub fn install(app: &AppHandle) -> tauri::Result<()> {
    let locale = crate::native_locale::selected();
    let mut labels = Vec::new();
    macro_rules! role {
        ($method:ident, $key:literal) => {
            labelled(
                &mut labels,
                PredefinedMenuItem::$method(app, Some(&text(locale, $key)))?,
                $key,
            )
        };
    }
    let about = labelled(
        &mut labels,
        PredefinedMenuItem::about(
            app,
            Some(&text(locale, "about")),
            Some(AboutMetadata {
                name: Some(app.package_info().name.clone()),
                version: Some(app.package_info().version.to_string()),
                copyright: app.config().bundle.copyright.clone(),
                authors: app.config().bundle.publisher.clone().map(|p| vec![p]),
                ..Default::default()
            }),
        )?,
        "about",
    );
    let check = labelled(
        &mut labels,
        MenuItem::with_id(
            app,
            "check-for-updates",
            text(locale, "check_title"),
            true,
            None::<&str>,
        )?,
        "check_title",
    );
    let app_menu = Submenu::with_items(
        app,
        "Arslan",
        true,
        &[
            &about,
            &check,
            &PredefinedMenuItem::separator(app)?,
            &role!(services, "services"),
            &PredefinedMenuItem::separator(app)?,
            &role!(hide, "hide"),
            &role!(hide_others, "hide_others"),
            &PredefinedMenuItem::separator(app)?,
            &role!(quit, "quit"),
        ],
    )?;
    let file = Submenu::with_items(
        app,
        text(locale, "file"),
        true,
        &[&role!(close_window, "close")],
    )?;
    let edit = Submenu::with_items(
        app,
        text(locale, "edit"),
        true,
        &[
            &role!(undo, "undo"),
            &role!(redo, "redo"),
            &PredefinedMenuItem::separator(app)?,
            &role!(cut, "cut"),
            &role!(copy, "copy"),
            &role!(paste, "paste"),
            &role!(select_all, "select_all"),
        ],
    )?;
    let view = Submenu::with_items(
        app,
        text(locale, "view"),
        true,
        &[&role!(fullscreen, "fullscreen")],
    )?;
    // These IDs retain Tauri/macOS's special Window and Help menu registration.
    let window = Submenu::with_id_and_items(
        app,
        "__tauri_window_menu__",
        text(locale, "window"),
        true,
        &[
            &role!(minimize, "minimize"),
            &role!(maximize, "maximize"),
            &PredefinedMenuItem::separator(app)?,
            &role!(close_window, "close"),
        ],
    )?;
    let help =
        Submenu::with_id_and_items(app, "__tauri_help_menu__", text(locale, "help"), true, &[])?;
    for (item, key) in [
        (&file, "file"),
        (&edit, "edit"),
        (&view, "view"),
        (&window, "window"),
        (&help, "help"),
    ] {
        labels.push((item.kind(), key));
    }
    app.set_menu(Menu::with_items(
        app,
        &[&app_menu, &file, &edit, &view, &window, &help],
    )?)?;
    app.manage(NativeMenu {
        labels,
        locale: Mutex::new(locale),
    });
    Ok(())
}

pub fn refresh(app: &AppHandle) {
    // Serialize label mutation on the UI thread. Never hold the locale lock on
    // a worker while waiting for native UI calls (focus events refresh too).
    let handle = app.clone();
    if let Err(error) = app.run_on_main_thread(move || refresh_on_main_thread(&handle)) {
        eprintln!("Could not schedule native menu refresh: {error}");
    }
}

fn refresh_on_main_thread(app: &AppHandle) {
    let Some(menu) = app.try_state::<NativeMenu>() else {
        return;
    };
    let next = crate::native_locale::selected();
    let mut current = menu.locale.lock().unwrap();
    if *current == next {
        return;
    }
    for (item, key) in &menu.labels {
        let label = text(next, key);
        let result = match item {
            MenuItemKind::Submenu(item) => item.set_text(label),
            MenuItemKind::Predefined(item) => item.set_text(label),
            MenuItemKind::MenuItem(item) => item.set_text(label),
            _ => continue,
        };
        if let Err(error) = result {
            eprintln!("Could not refresh native menu label {key}: {error}");
            return; // Retry on the next refresh rather than caching partial success.
        }
    }
    *current = next;
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn every_native_menu_label_has_six_translations() {
        let copy: serde_json::Value =
            serde_json::from_str(include_str!("../native_menu_messages.json")).unwrap();
        let english = copy["en"].as_object().unwrap();
        assert_eq!(english.len(), 20);
        assert_eq!(copy.as_object().unwrap().len(), 6);
        for locale in ["en", "zh", "ja", "es", "de", "fr"] {
            assert_eq!(copy[locale].as_object().unwrap().len(), english.len());
            for key in english.keys() {
                assert!(!text(locale, key).trim().is_empty());
                assert_eq!(text(locale, key), copy[locale][key].as_str().unwrap());
            }
        }
        assert_eq!(text("unknown", "edit"), "Edit");
        assert_eq!(
            text("ja", "check_title"),
            crate::native_locale::text("ja", "check_title")
        );
    }
}

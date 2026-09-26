//! Fixed bundled choices only: the remote UI never supplies image data or paths.
use tauri::Manager;

#[derive(Clone, Copy, Default, serde::Serialize, serde::Deserialize, PartialEq, Debug)]
#[serde(rename_all = "lowercase")]
pub enum IconStyle {
    #[default]
    Frosted,
    Monochrome,
}

fn preference(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    app.path()
        .app_config_dir()
        .map(|p| p.join("icon-style.json"))
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub fn get_app_icon(app: tauri::AppHandle) -> IconStyle {
    preference(&app)
        .ok()
        .and_then(|p| std::fs::read(p).ok())
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default()
}

fn bytes(style: IconStyle) -> &'static [u8] {
    match style {
        IconStyle::Frosted => include_bytes!("../../../web/public/brand/frosted.png"),
        IconStyle::Monochrome => include_bytes!("../../../web/public/brand/monochrome.png"),
    }
}

/// Must run on the event thread. macOS Dock icons are application-wide.
fn apply(app: &tauri::AppHandle, style: IconStyle) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        use objc2::{AnyThread, MainThreadMarker};
        use objc2_app_kit::{NSApplication, NSImage};
        let mtm = MainThreadMarker::new().ok_or("Icon update requires the main thread")?;
        let data = objc2_foundation::NSData::with_bytes(bytes(style));
        let image = NSImage::initWithData(NSImage::alloc(), &data).ok_or("Invalid bundled icon")?;
        // A valid retained NSImage is supplied, never nil; AppKit retains it.
        unsafe {
            NSApplication::sharedApplication(mtm).setApplicationIconImage(Some(&image));
        }
    }
    // Windows/Linux use the window icon; also updates any native window menu.
    let icon = tauri::image::Image::from_bytes(bytes(style)).map_err(|e| e.to_string())?;
    for window in app.webview_windows().values() {
        window.set_icon(icon.clone()).map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn restore(app: &tauri::AppHandle) {
    let style = get_app_icon(app.clone());
    if let Err(error) = apply(app, style) {
        eprintln!("Could not restore app icon: {error}");
    }
}

#[tauri::command]
pub async fn set_app_icon(app: tauri::AppHandle, style: IconStyle) -> Result<(), String> {
    let (tx, rx) = std::sync::mpsc::sync_channel(1);
    let handle = app.clone();
    app.run_on_main_thread(move || {
        let previous = get_app_icon(handle.clone());
        let result = (|| {
            apply(&handle, style)?;
            let path = preference(&handle)?;
            std::fs::create_dir_all(path.parent().ok_or("Missing settings directory")?)
                .map_err(|e| e.to_string())?;
            let temp = path.with_extension("tmp");
            std::fs::write(
                &temp,
                serde_json::to_vec(&style).map_err(|e| e.to_string())?,
            )
            .map_err(|e| e.to_string())?;
            std::fs::rename(temp, path).map_err(|e| e.to_string())
        })();
        if result.is_err() {
            let _ = apply(&handle, previous);
        }
        let _ = tx.send(result);
    })
    .map_err(|e| e.to_string())?;
    rx.recv().map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn only_bundled_icon_identifiers_are_accepted() {
        for style in [IconStyle::Frosted, IconStyle::Monochrome] {
            let encoded = serde_json::to_vec(&style).unwrap();
            assert_eq!(
                serde_json::from_slice::<IconStyle>(&encoded).unwrap(),
                style
            );
            assert!(bytes(style).starts_with(b"\x89PNG"));
        }
        assert!(serde_json::from_str::<IconStyle>("\"/tmp/arbitrary.png\"").is_err());
        assert!(serde_json::from_str::<IconStyle>("\"unknown\"").is_err());
    }
}

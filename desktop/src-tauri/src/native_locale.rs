//! Product-owned native dialog copy. The hint is display-only, never authority.
use std::io::Read;
use std::path::Path;

pub fn read_locale(path: &Path) -> &'static str {
    let Ok(metadata) = std::fs::symlink_metadata(path) else {
        return "en";
    };
    if !metadata.is_file() || metadata.len() > 16 {
        return "en";
    }
    let Ok(file) = std::fs::File::open(path) else {
        return "en";
    };
    let mut value = String::new();
    if file.take(17).read_to_string(&mut value).is_err() {
        return "en";
    }
    match value.trim() {
        "zh" => "zh",
        "ja" => "ja",
        "es" => "es",
        "de" => "de",
        "fr" => "fr",
        _ => "en",
    }
}

pub fn selected() -> &'static str {
    let Some(home) = std::env::var_os("HOME") else {
        return "en";
    };
    read_locale(&Path::new(&home).join("Library/Application Support/Arslan/ui_language"))
}

pub fn text(locale: &str, key: &str) -> String {
    if key.starts_with("restore_") {
        static RECOVERY: std::sync::OnceLock<serde_json::Value> = std::sync::OnceLock::new();
        let copy = RECOVERY.get_or_init(|| serde_json::from_str(include_str!("../recovery_messages.json"))
            .expect("recovery dialog catalog must be valid JSON"));
        return copy.get(locale).and_then(|row| row.get(key)).or_else(|| copy["en"].get(key))
            .and_then(|value| value.as_str()).unwrap_or("Arslan").to_string();
    }
    static COPY: std::sync::OnceLock<serde_json::Value> = std::sync::OnceLock::new();
    let copy = COPY.get_or_init(|| {
        serde_json::from_str(include_str!("../native_messages.json"))
            .expect("native dialog catalog must be valid JSON")
    });
    copy.get(locale)
        .and_then(|row| row.get(key))
        .or_else(|| copy["en"].get(key))
        .and_then(|value| value.as_str())
        .unwrap_or("Arslan")
        .to_string()
}

/// Inject only display data into the bundled splash, never the remote webview.
pub fn boot_script(locale: &str) -> String {
    let locale = match locale {
        "zh" | "ja" | "es" | "de" | "fr" => locale,
        _ => "en",
    };
    let copy = serde_json::json!({
        "locale": locale,
        "starting": text(locale, "boot_starting"),
        "slow": text(locale, "boot_slow"),
    });
    format!("window.__ARSLAN_BOOT_COPY__ = {copy};")
}

pub fn boot_error_script(locale: &str, detail: &str) -> String {
    let message = format!("{}\n\n{detail}", text(locale, "boot_failed"));
    let encoded = serde_json::to_string(&message).expect("strings serialize as JSON");
    format!("window.__arslanBootError && window.__arslanBootError({encoded});")
}

pub fn refresh_boot_script(locale: &str) -> String {
    format!("{} window.__arslanRefreshBootCopy && window.__arslanRefreshBootCopy();", boot_script(locale))
}

pub fn recovery_script(locale: &str, paused: bool) -> String {
    let copy = serde_json::json!({
        "locale": locale,
        "heading": text(locale, if paused { "restore_paused_title" } else { "restore_working" }),
        "detail": text(locale, if paused { "restore_paused" } else { "restore_working_body" }),
    });
    format!("window.__ARSLAN_RECOVERY_COPY__ = {copy}; window.__arslanRenderRecovery && window.__arslanRenderRecovery();")
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn recovery_ui_copy_covers_all_six_locales() {
        let copy: serde_json::Value = serde_json::from_str(include_str!("../recovery_messages.json")).unwrap();
        let keys = copy["en"].as_object().unwrap();
        assert_eq!(keys.len(), 14);
        assert_eq!(copy.as_object().unwrap().len(), 6);
        for locale in ["en", "zh", "ja", "es", "de", "fr"] {
            assert_eq!(copy[locale].as_object().unwrap().len(), keys.len());
            for key in keys.keys() {
                assert_eq!(text(locale, key), copy[locale][key].as_str().unwrap());
                assert!(!text(locale, key).trim().is_empty());
            }
        }
    }
    #[test]
    fn boot_data_and_error_details_are_json_not_executable_content() {
        for locale in ["en", "zh", "ja", "es", "de", "fr"] {
            let script = boot_script(locale);
            let encoded = script
                .strip_prefix("window.__ARSLAN_BOOT_COPY__ = ")
                .unwrap()
                .strip_suffix(';')
                .unwrap();
            let copy: serde_json::Value = serde_json::from_str(encoded).unwrap();
            assert_eq!(copy["locale"], locale);
            assert_eq!(copy["starting"], text(locale, "boot_starting"));
            assert_eq!(copy["slow"], text(locale, "boot_slow"));
            assert_eq!(refresh_boot_script(locale), format!(
                "{script} window.__arslanRefreshBootCopy && window.__arslanRefreshBootCopy();"));
            let detail = "\"\\\r\n\t); window.injected = true; //";
            let error = boot_error_script(locale, detail);
            let argument = error
                .strip_prefix("window.__arslanBootError && window.__arslanBootError(")
                .unwrap()
                .strip_suffix(");")
                .unwrap();
            let decoded: String = serde_json::from_str(argument).unwrap();
            assert_eq!(
                decoded,
                format!("{}\n\n{detail}", text(locale, "boot_failed"))
            );
        }
        assert_eq!(boot_script("unknown"), boot_script("en"));
    }

    #[test]
    fn hint_is_bounded_and_missing_or_invalid_is_english() {
        let path = std::env::temp_dir().join(format!(
            "arslan-locale-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        assert_eq!(read_locale(&path), "en");
        for locale in ["en", "zh", "ja", "es", "de", "fr"] {
            std::fs::write(&path, format!("{locale}\n")).unwrap();
            assert_eq!(read_locale(&path), locale);
        }
        for invalid in [
            "fr<script>",
            "../../fr",
            "fr\nsecret",
            "fr                 ",
        ] {
            std::fs::write(&path, invalid).unwrap();
            assert_eq!(read_locale(&path), "en");
        }
        std::fs::remove_file(&path).unwrap();
        #[cfg(unix)]
        {
            std::os::unix::fs::symlink("/dev/zero", &path).unwrap();
            assert_eq!(read_locale(&path), "en");
            std::fs::remove_file(&path).unwrap();
        }
    }

    #[test]
    fn catalog_covers_six_languages() {
        let copy: serde_json::Value =
            serde_json::from_str(include_str!("../native_messages.json")).unwrap();
        let keys = copy["en"].as_object().unwrap();
        assert_eq!(copy.as_object().unwrap().len(), 6);
        for locale in ["en", "zh", "ja", "es", "de", "fr"] {
            assert_eq!(copy[locale].as_object().unwrap().len(), keys.len());
            for key in keys.keys() {
                assert!(!text(locale, key).trim().is_empty());
                assert_eq!(text(locale, key), copy[locale][key].as_str().unwrap());
            }
        }
        assert_eq!(text("untrusted", "latest"), text("en", "latest"));
    }
}

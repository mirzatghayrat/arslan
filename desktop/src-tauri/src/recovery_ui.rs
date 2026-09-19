//! Trusted native picker/dialog adapter; deliberately absent from invoke_handler.
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::sync::{atomic::{AtomicBool, Ordering}, Arc};
use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

use crate::recovery_control::{self, Outcome as Reply, Request};
use crate::recovery_coordinator::{self, Outcome, Steps};
use crate::recovery_secret::{read_existing, DurableSecret, ExistingSecret};

const RECOVERY_LABEL: &str = "recovery";

#[derive(PartialEq)]
struct LaunchInputs {
    home: PathBuf,
    environment: String,
    explicit: Option<String>,
    file_override: Option<String>,
}

fn optional_env(name: &str) -> Result<Option<String>, ()> {
    match std::env::var(name) {
        Ok(value) => Ok(Some(value)),
        Err(std::env::VarError::NotPresent) => Ok(None),
        Err(_) => Err(()),
    }
}

impl LaunchInputs {
    fn read() -> Result<Self, ()> {
        let home = PathBuf::from(std::env::var_os("HOME").ok_or(())?);
        if !home.is_absolute() {
            return Err(());
        }
        Ok(Self {
            home,
            environment: optional_env("ARSLAN_ENV")?
                .unwrap_or_else(|| "dev".into())
                .to_lowercase(),
            explicit: optional_env("ARSLAN_SECRET_KEY")?,
            file_override: optional_env("ARSLAN_SECRET_KEY_FILE")?,
        })
    }
    fn profile(&self) -> PathBuf {
        self.home.join("Library/Application Support/Arslan")
    }
    fn durable(&self) -> Result<DurableSecret, ()> {
        DurableSecret::load(
            &self.home,
            &self.profile(),
            &self.environment,
            self.explicit.as_deref(),
            self.file_override.as_deref(),
        )
        .map_err(|_| ())
    }
}

#[derive(PartialEq)]
struct ArchiveStamp(u64, u64, u64, i64, i64, i64, i64);
fn archive_stamp(path: &Path) -> Result<ArchiveStamp, ()> {
    if !path.is_absolute()
        || path
            .components()
            .any(|c| c == std::path::Component::ParentDir)
    {
        return Err(());
    }
    let m = std::fs::symlink_metadata(path).map_err(|_| ())?;
    if !m.is_file() || m.len() == 0 || m.len() > 2 * 1024 * 1024 * 1024 {
        return Err(());
    }
    Ok(ArchiveStamp(
        m.dev(),
        m.ino(),
        m.len(),
        m.mtime(),
        m.mtime_nsec(),
        m.ctime(),
        m.ctime_nsec(),
    ))
}

struct Selection {
    inputs: LaunchInputs,
    archive: PathBuf,
    archive_stamp: ArchiveStamp,
    key_path: PathBuf,
    source: ExistingSecret,
    target: DurableSecret,
    candidate: String,
}

struct NativeSteps {
    app: AppHandle,
    locale: &'static str,
    executable: PathBuf,
    selection: Option<Selection>,
    paused: Arc<AtomicBool>,
}

impl NativeSteps {
    fn text(&self, key: &str) -> String {
        crate::native_locale::text(self.locale, key)
    }
    fn dialog_window(&self) -> Option<tauri::WebviewWindow> {
        self.app.get_webview_window(RECOVERY_LABEL)
            .or_else(|| self.app.get_webview_window(crate::MAIN_LABEL))
    }
    fn show_maintenance(&self) -> Result<(), ()> {
        let app = self.app.clone();
        let locale = self.locale;
        let paused = self.paused.clone();
        let (tx, rx) = std::sync::mpsc::sync_channel(1);
        self.app.run_on_main_thread(move || {
            let result = (|| {
                let main = app.get_webview_window(crate::MAIN_LABEL).ok_or(())?;
                // Keep the old DOM (including unsent drafts), but do not let
                // it appear usable after the service is stopped. No recovery
                // window is granted an IPC capability.
                main.set_enabled(false).map_err(|_| ())?;
                let page_paused = paused.clone();
                let window = tauri::WebviewWindowBuilder::new(
                    &app, RECOVERY_LABEL,
                    tauri::WebviewUrl::App("recovery.html".into()),
                )
                .title(crate::native_locale::text(locale, "restore_working"))
                .initialization_script(crate::native_locale::recovery_script(locale, false))
                .on_page_load(move |webview, payload| {
                    if matches!(payload.event(), tauri::webview::PageLoadEvent::Finished) {
                        let _ = webview.eval(&crate::native_locale::recovery_script(
                            locale, page_paused.load(Ordering::SeqCst),
                        ));
                    }
                })
                .inner_size(crate::WINDOW_W, crate::WINDOW_H)
                .min_inner_size(480.0, 360.0)
                .center()
                // Quit remains available in the native menu. Closing just this
                // window would strand a hidden, intentionally disabled main.
                .closable(false)
                .build().map_err(|_| ())?;
                // If main-thread dispatch ran after the worker timed out,
                // show the paused state rather than stale progress. Publishing
                // the window before this load also lets show_paused find it.
                if paused.load(Ordering::SeqCst) {
                    window.set_title(&crate::native_locale::text(locale, "restore_paused_title")).map_err(|_| ())?;
                    window.eval(&crate::native_locale::recovery_script(locale, true)).map_err(|_| ())?;
                }
                main.hide().map_err(|_| ())?;
                window.set_focus().map_err(|_| ())?;
                Ok(())
            })();
            let _ = tx.send(result);
        }).map_err(|_| ())?;
        // A timeout is an uncertain, fail-closed outcome, never permission to
        // continue stopping/switching or to re-enable the old workspace.
        rx.recv_timeout(std::time::Duration::from_secs(10)).map_err(|_| ())?
    }
    fn show_paused(&self) {
        self.paused.store(true, Ordering::SeqCst);
        if let Some(window) = self.app.get_webview_window(RECOVERY_LABEL) {
            let _ = window.set_title(&self.text("restore_paused_title"));
            let _ = window.eval(&crate::native_locale::recovery_script(self.locale, true));
        }
    }
    fn confirm(&self, message: String, accept: &str, cancel: &str) -> bool {
        let Some(window) = self.dialog_window() else {
            return false;
        };
        self.app
            .dialog()
            .message(message)
            .parent(&window)
            .title(self.text("restore_title"))
            .kind(MessageDialogKind::Warning)
            .buttons(MessageDialogButtons::OkCancelCustom(
                self.text(accept),
                self.text(cancel),
            ))
            .blocking_show()
    }
    fn selected(&self) -> Result<&Selection, ()> {
        self.selection.as_ref().ok_or(())
    }
}

impl Steps for NativeSteps {
    fn select_and_validate(&mut self) -> Result<bool, ()> {
        crate::refresh_update_menu(&self.app);
        // A failed/absent backend cannot be treated as acknowledged stopped.
        if self
            .app
            .state::<crate::Sidecar>()
            .0
            .lock()
            .map_err(|_| ())?
            .is_none()
        {
            return Err(());
        }
        let inputs = LaunchInputs::read()?;
        let target = inputs.durable()?;
        let Some(archive) = self
            .app
            .dialog()
            .file()
            .set_title(self.text("restore_archive"))
            .add_filter("ZIP", &["zip"])
            .blocking_pick_file()
        else {
            return Ok(false);
        };
        let archive = archive.into_path().map_err(|_| ())?;
        let stamp = archive_stamp(&archive)?;
        let Some(key) = self
            .app
            .dialog()
            .file()
            .set_title(self.text("restore_key"))
            // NSOpenPanel is shared. rfd only resets allowed file types when
            // at least one filter exists; an empty extension list explicitly
            // clears the preceding ZIP filter (keys need no extension).
            .add_filter("", &[])
            .blocking_pick_file()
        else {
            return Ok(false);
        };
        let key_path = key.into_path().map_err(|_| ())?;
        // The selected original backup secret is not the current environment's
        // secret. Never apply normal explicit-env precedence to this selection.
        let source = read_existing(&key_path).map_err(|_| ())?;
        let candidate = format!(
            ".arslan-restored-{}",
            crate::recovery_trial::token().map_err(|_| ())?
        );
        self.selection = Some(Selection {
            inputs,
            archive,
            archive_stamp: stamp,
            key_path,
            source,
            target,
            candidate,
        });
        self.recheck_target()?;
        Ok(true)
    }
    fn confirm_adaptation(&mut self) -> bool {
        let Ok(s) = self.selected() else {
            return false;
        };
        self.confirm(
            format!(
                "{}\n\n{}\n{}",
                self.text("restore_confirm"),
                s.archive.display(),
                s.key_path.display()
            ),
            "restore_begin",
            "not_now",
        )
    }
    fn recheck_target(&mut self) -> Result<(), ()> {
        let s = self.selected()?;
        if LaunchInputs::read()? != s.inputs || archive_stamp(&s.archive)? != s.archive_stamp {
            return Err(());
        }
        s.target.recheck().map_err(|_| ())
    }
    fn stop(&mut self) -> Result<(), ()> {
        self.show_maintenance()?;
        let _ = crate::listen::voice_stop(self.app.clone());
        let _ = crate::voice::voice_conversation_stop(self.app.clone());
        let child = self
            .app
            .state::<crate::Sidecar>()
            .0
            .lock()
            .map_err(|_| ())?
            .take()
            .ok_or(())?;
        crate::recovery_shutdown::stop(child.process, child.shutdown).map_err(|_| ())
    }
    fn prepare(&mut self) -> Result<(), ()> {
        let s = self.selected()?;
        match recovery_control::run(
            &self.executable,
            &Request::Prepare {
                archive: &s.archive,
                candidate: &s.candidate,
            },
        ) {
            Ok(Reply::Prepared { .. }) => Ok(()),
            _ => Err(()),
        }
    }
    fn rewrap(&mut self) -> Result<(), ()> {
        let s = self.selected()?;
        match recovery_control::run(
            &self.executable,
            &Request::Rewrap {
                candidate: &s.candidate,
                source: &s.source,
                target: &s.target,
            },
        ) {
            Ok(Reply::Rewrapped { .. }) => Ok(()),
            _ => Err(()),
        }
    }
    fn switch(&mut self) -> Result<String, ()> {
        let s = self.selected()?;
        match recovery_control::run(
            &self.executable,
            &Request::Switch {
                candidate: &s.candidate,
                secret: s.target.secret(),
            },
        ) {
            Ok(Reply::TrialPending(operation)) => Ok(operation),
            _ => Err(()),
        }
    }
    fn trial(&mut self, operation: &str) -> Result<(), ()> {
        crate::recovery_trial::run(
            &self.executable,
            operation,
            self.selected()?.target.secret(),
        )
        .map_err(|_| ())
    }
    fn confirm_finalization(&mut self, _operation: &str) -> bool {
        self.confirm(
            self.text("restore_activate_prompt"),
            "restore_activate",
            "recovery_keep_paused",
        )
    }
    fn finalize(&mut self, operation: &str) -> Result<(), ()> {
        match recovery_control::run(
            &self.executable,
            &Request::Finalize {
                operation_id: operation,
                secret: self.selected()?.target.secret(),
            },
        ) {
            Ok(Reply::Finalized { .. }) => Ok(()),
            _ => Err(()),
        }
    }
    fn restart(&mut self) -> Result<(), ()> {
        self.recheck_target()?;
        // Never return a success merely for requesting relaunch. The fresh
        // normal desktop boot owns child health, key bootstrap and window reveal.
        // No second backend is started here (which could run scheduled work twice).
        self.app.restart()
    }
}

pub(crate) fn begin(app: AppHandle) {
    std::thread::spawn(move || {
        let locale = crate::native_locale::selected();
        let executable = match app.path().resolve(
            "sidecar/arslan-server",
            tauri::path::BaseDirectory::Resource,
        ) {
            Ok(path) => path,
            Err(_) => return,
        };
        let mut steps = NativeSteps {
            app: app.clone(),
            locale,
            executable,
            selection: None,
            paused: Arc::new(AtomicBool::new(false)),
        };
        let result =
            recovery_coordinator::run(&app.state::<crate::maintenance::Gate>(), &mut steps);
        crate::refresh_update_menu(&app);
        if matches!(result, Outcome::Paused(_)) {
            steps.show_paused();
        }
        let message = match result {
            Outcome::Refused => Some("restore_refused"),
            Outcome::Paused(_) => Some("restore_paused"),
            Outcome::Busy | Outcome::Cancelled | Outcome::Complete => None,
        };
        if let Some(key) = message {
            let Some(window) = steps.dialog_window() else {
                return;
            };
            app.dialog()
                .message(steps.text(key))
                .parent(&window)
                .title(steps.text("restore_title"))
                .kind(MessageDialogKind::Warning)
                .buttons(MessageDialogButtons::OkCustom(steps.text("restore_ack")))
                .blocking_show();
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn archive_selection_is_regular_bounded_and_detects_replacement() {
        let base = std::env::temp_dir().join(format!(
            "arslan-archive-selection-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&base).unwrap();
        let path = base.join("selected.zip");
        assert!(archive_stamp(&path).is_err());
        std::fs::write(&path, b"synthetic-archive").unwrap();
        let stamp = archive_stamp(&path).unwrap();
        assert!(archive_stamp(&path).unwrap() == stamp);
        let replacement = base.join("replacement.zip");
        std::fs::write(&replacement, b"synthetic-archive").unwrap();
        std::fs::rename(replacement, &path).unwrap();
        assert!(archive_stamp(&path).unwrap() != stamp);
        let link = base.join("link.zip");
        std::os::unix::fs::symlink(&path, &link).unwrap();
        assert!(archive_stamp(&link).is_err());
        assert!(archive_stamp(&base).is_err());
        std::fs::remove_dir_all(base).unwrap();
    }
}

//! Manual art review shell. Uses only an explicitly supplied loopback fixture;
//! never starts the real sidecar or reads the user's Arslan data.
#[path = "../src/app_icon.rs"]
mod app_icon;
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

fn main() {
    let url: tauri::Url = std::env::var("ARSLAN_ART_PREVIEW_URL")
        .expect("Start the isolated companion UI harness and set ARSLAN_ART_PREVIEW_URL")
        .parse()
        .expect("valid fixture URL");
    assert_eq!(url.scheme(), "http");
    assert_eq!(url.host_str(), Some("127.0.0.1"));
    let mut context = tauri::generate_context!();
    context.config_mut().identifier = "com.arslan.art-preview".into();
    context.config_mut().product_name = Some("Arslan Art Preview".into());
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            app_icon::get_app_icon,
            app_icon::set_app_icon
        ])
        .setup(move |app| {
            app_icon::restore(app.handle());
            WebviewWindowBuilder::new(app, "splash", WebviewUrl::App("index.html".into()))
                .title("Arslan — Splash Review")
                .inner_size(1280.0, 840.0)
                .resizable(false)
                .decorations(false)
                .transparent(true)
                .center()
                .build()?;
            if std::env::var_os("ARSLAN_ART_PREVIEW_SPLASH_ONLY").is_none() {
                WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
                    .title("Arslan — Art Preview")
                    .inner_size(1280.0, 840.0)
                    .min_inner_size(900.0, 600.0)
                    .visible(false)
                    .center()
                    .build()?;
                let handle = app.handle().clone();
                std::thread::spawn(move || {
                    std::thread::sleep(std::time::Duration::from_secs(4));
                    let work = handle.clone();
                    let _ = handle.run_on_main_thread(move || {
                        if let Some(window) = work.get_webview_window("main") {
                            let _ = window.show();
                        }
                        if let Some(window) = work.get_webview_window("splash") {
                            let _ = window.close();
                        }
                    });
                });
            }
            Ok(())
        })
        .run(context)
        .expect("art review shell");
}

fn main() {
    // The two app-defined commands must be declared here or tauri-build
    // generates no permissions for them, and capabilities/remote-ui-drag.json
    // (which grants them to the sidecar-served origin) fails validation.
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&["update_status", "install_update"]),
        ),
    )
    .expect("failed to run tauri-build");
}

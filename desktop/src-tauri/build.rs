fn main() {
    // Every app-defined command must be declared here or tauri-build
    // generates no permission for it, and no capability can ever grant it to
    // the sidecar-served origin: invoke() from the UI is then refused by the
    // ACL. That is silent in the other direction — a command registered in
    // generate_handler! but missing here builds fine and fails only on a
    // packaged install (v0.1.36 shipped hold-to-talk that way). The list is
    // asserted against generate_handler! by
    // tests/server/test_tauri_command_acl_lockstep.py.
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "update_status",
            "install_update",
            "open_external",
            "voice_start",
            "voice_stop",
        ]),
    ))
    .expect("failed to run tauri-build");
}

//! Arslan Hands takes no arguments and reads no environment for its own
//! configuration (spec §2.1): its folder comes from the account database, and
//! agent-desktop sits NEXT TO the bundle (`…/hands/agent-desktop`, beside
//! `…/hands/Arslan Hands.app`), checked against the sha256 recorded inside the
//! bundle (see integrity.rs for why it is not inside).

use arslan_hands::{paths, server};
use std::time::Duration;

fn main() {
    let Some(home) = paths::account_home() else {
        eprintln!("arslan-hands: no home directory for this account");
        std::process::exit(1);
    };
    // …/hands/Arslan Hands.app/Contents/MacOS/arslan-hands
    let Some(contents) = std::env::current_exe().ok().and_then(|exe| {
        exe.parent()
            .and_then(|macos| macos.parent())
            .map(|c| c.to_path_buf())
    }) else {
        eprintln!("arslan-hands: cannot locate itself");
        std::process::exit(1);
    };
    let Some(agent_desktop) = contents
        .parent()
        .and_then(|bundle| bundle.parent())
        .map(|hands| hands.join("agent-desktop"))
    else {
        eprintln!("arslan-hands: cannot locate agent-desktop");
        std::process::exit(1);
    };
    let agent_desktop_sha256 =
        arslan_hands::integrity::recorded(&contents.join("Resources/agent-desktop.sha256"));
    #[cfg(all(target_os = "macos", not(feature = "dev-unverified-peer")))]
    let team = arslan_hands::macos::own_team();
    #[cfg(all(target_os = "macos", feature = "dev-unverified-peer"))]
    let team = {
        eprintln!("arslan-hands: DEVELOPMENT BUILD — the peer check is off");
        None
    };
    #[cfg(not(target_os = "macos"))]
    let team = None;
    if agent_desktop_sha256.is_none() && team.is_some() {
        // A signed Hands always carries the record; without it, refuse rather
        // than run an unchecked binary that would inherit the grant.
        eprintln!("arslan-hands: no agent-desktop.sha256 in a signed build");
        std::process::exit(1);
    }
    // Hands v2: Cua Driver, beside the bundle like agent-desktop, when this build has it.
    // A signed Hands runs it only against the sha256 recorded inside its bundle.
    let cua_binary = contents
        .parent()
        .and_then(|bundle| bundle.parent())
        .map(|hands| hands.join("cua-driver"))
        .filter(|path| path.is_file());
    let cua_driver_sha256 =
        arslan_hands::integrity::recorded(&contents.join("Resources/cua-driver.sha256"));
    let cua_driver = match (cua_binary, &cua_driver_sha256) {
        (Some(_), None) if team.is_some() => {
            eprintln!(
                "arslan-hands: cua-driver without its sha256 record in a signed build: not used"
            );
            None
        }
        (binary, _) => binary,
    };
    let config = server::Config {
        folder: paths::folder(&home),
        agent_desktop,
        agent_desktop_sha256,
        home,
        idle: Duration::from_secs(15 * 60),
        team,
        cua_driver,
        cua_driver_sha256,
        host_bundle_id: arslan_hands::paths::own_bundle_id(&contents),
    };
    let bound = match server::bind(&config) {
        Ok(bound) => bound,
        Err(error) => {
            eprintln!("arslan-hands: {error}");
            // A second launch while one runs is normal (LaunchServices may start it twice).
            std::process::exit(if error.contains("already running") {
                0
            } else {
                1
            });
        }
    };
    // The socket is served off the main thread; on macOS the main thread runs the
    // Cocoa app that LaunchServices and the Accessibility list expect.
    let serving = std::thread::spawn(move || server::serve(config, bound));
    #[cfg(target_os = "macos")]
    {
        let _ = serving;
        // The key tap watches from launch (holding nothing until a borrow): how long the user
        // has been away (§6.5) and whether they are typing need it. Without Accessibility it
        // cannot start; borrows and takeovers then start it, or say why not.
        let _ = arslan_hands::keyhold::start();
        arslan_hands::macos::run_app_loop();
    }
    #[cfg(not(target_os = "macos"))]
    if let Ok(Err(error)) = serving.join() {
        eprintln!("arslan-hands: {error}");
        std::process::exit(1);
    }
}

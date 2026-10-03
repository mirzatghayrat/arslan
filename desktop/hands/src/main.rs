//! Arslan Hands takes no arguments and reads no environment for its own
//! configuration (spec §2.1): its folder comes from the account database and
//! agent-desktop sits next to its own executable.

use arslan_hands::{paths, server};
use std::time::Duration;

fn main() {
    let Some(home) = paths::account_home() else {
        eprintln!("arslan-hands: no home directory for this account");
        std::process::exit(1);
    };
    let Some(agent_desktop) = std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|dir| dir.join("agent-desktop")))
    else {
        eprintln!("arslan-hands: cannot locate itself");
        std::process::exit(1);
    };
    #[cfg(all(target_os = "macos", not(feature = "dev-unverified-peer")))]
    let team = arslan_hands::macos::own_team();
    #[cfg(all(target_os = "macos", feature = "dev-unverified-peer"))]
    let team = {
        eprintln!("arslan-hands: DEVELOPMENT BUILD — the peer check is off");
        None
    };
    #[cfg(not(target_os = "macos"))]
    let team = None;
    let config = server::Config {
        folder: paths::folder(&home),
        agent_desktop,
        home,
        idle: Duration::from_secs(15 * 60),
        team,
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
        arslan_hands::macos::run_app_loop();
    }
    #[cfg(not(target_os = "macos"))]
    if let Ok(Err(error)) = serving.join() {
        eprintln!("arslan-hands: {error}");
        std::process::exit(1);
    }
}

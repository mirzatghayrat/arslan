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
    #[cfg(target_os = "macos")]
    let team = arslan_hands::macos::own_team();
    #[cfg(not(target_os = "macos"))]
    let team = None;
    let config = server::Config {
        folder: paths::folder(&home),
        agent_desktop,
        home,
        idle: Duration::from_secs(15 * 60),
        team,
    };
    if let Err(error) = server::run(config) {
        eprintln!("arslan-hands: {error}");
        // A second launch while one runs is normal (LaunchServices may start it twice).
        std::process::exit(if error.contains("already running") {
            0
        } else {
            1
        });
    }
}

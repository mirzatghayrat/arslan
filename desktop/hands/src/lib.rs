//! Arslan Hands (0.1.53): the helper app that holds the Accessibility grant and
//! runs agent-desktop for Arslan's backend. Spec:
//! docs/specs/2026-10-03-0153-hands-agent-desktop.md.

pub mod argv;
pub mod borrow;
pub mod capture;
pub mod cua;
pub mod cua_policy;
pub mod glow;
pub mod integrity;
pub mod keyhold;
pub mod late_front;
#[cfg(target_os = "macos")]
pub mod macos;
pub mod menus;
pub mod outcome;
pub mod paths;
pub mod policy;
pub mod refmap;
pub mod runner;
pub mod server;
pub mod structure;
pub mod takeover;

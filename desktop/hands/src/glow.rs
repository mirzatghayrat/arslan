//! The edge glow (spec 2026-10-08-0157 §6.6): src/glow.m draws it on every display, above
//! full-screen apps, click-through and left out of every screen capture.

/// The glow's colour (sRGB, 0…1). Blue, the mascot's "working" colour, until the user picks
/// another in the mock (amber means "needs you" and red "stopped", so neither is used here).
pub const COLOR: (f64, f64, f64) = (10.0 / 255.0, 132.0 / 255.0, 1.0);

#[cfg(target_os = "macos")]
extern "C" {
    fn hands_glow_show(r: f64, g: f64, b: f64);
    fn hands_glow_hide();
}

#[cfg(target_os = "macos")]
pub fn show() {
    // SAFETY: plain numbers; glow.m does its AppKit work on the main queue.
    unsafe { hands_glow_show(COLOR.0, COLOR.1, COLOR.2) }
}

#[cfg(target_os = "macos")]
pub fn hide() {
    // SAFETY: no arguments; main queue as above.
    unsafe { hands_glow_hide() }
}

#[cfg(not(target_os = "macos"))]
pub fn show() {}
#[cfg(not(target_os = "macos"))]
pub fn hide() {}

//! The two things Hands asks macOS directly (spec §2.2): whether it holds
//! Accessibility (and showing the system's prompt once), and who is on the other
//! end of the socket.
//!
//! Peer check: in a signed build only Arslan's own backend may talk to Hands —
//! code signed by Hands' own Team ID with the identifier `arslan-server`.
//! Without it, any process of the user that can read the token file could
//! borrow Hands' Accessibility grant. Hands reads its Team ID from its own
//! signature; an unsigned or ad-hoc build has none and skips the check (and says
//! so in `status`).

#![allow(non_upper_case_globals)]

use std::ffi::{c_char, c_void, CStr};
use std::os::fd::RawFd;

type CFTypeRef = *const c_void;
type CFIndex = isize;

const UTF8: u32 = 0x0800_0100;
const SIGNING_INFORMATION: u32 = 1 << 1;
const SOL_LOCAL: libc::c_int = 0;
const LOCAL_PEERPID: libc::c_int = 0x002;
const LOCAL_PEERTOKEN: libc::c_int = 0x006;

#[link(name = "CoreFoundation", kind = "framework")]
extern "C" {
    static kCFBooleanTrue: CFTypeRef;
    static kCFTypeDictionaryKeyCallBacks: [usize; 6];
    static kCFTypeDictionaryValueCallBacks: [usize; 5];
    fn CFDictionaryCreate(
        allocator: CFTypeRef,
        keys: *const CFTypeRef,
        values: *const CFTypeRef,
        count: CFIndex,
        key_callbacks: *const c_void,
        value_callbacks: *const c_void,
    ) -> CFTypeRef;
    fn CFDictionaryGetValue(dict: CFTypeRef, key: CFTypeRef) -> CFTypeRef;
    fn CFDataCreate(allocator: CFTypeRef, bytes: *const u8, length: CFIndex) -> CFTypeRef;
    fn CFStringCreateWithBytes(
        allocator: CFTypeRef,
        bytes: *const u8,
        length: CFIndex,
        encoding: u32,
        external: u8,
    ) -> CFTypeRef;
    fn CFStringGetCString(s: CFTypeRef, buffer: *mut c_char, size: CFIndex, encoding: u32) -> u8;
    fn CFGetTypeID(cf: CFTypeRef) -> usize;
    fn CFStringGetTypeID() -> usize;
    fn CFArrayGetTypeID() -> usize;
    fn CFArrayGetCount(array: CFTypeRef) -> CFIndex;
    fn CFArrayGetValueAtIndex(array: CFTypeRef, index: CFIndex) -> CFTypeRef;
    fn CFHash(cf: CFTypeRef) -> usize;
    fn CFBooleanGetValue(boolean: CFTypeRef) -> u8;
    fn CFBooleanGetTypeID() -> usize;
    fn CFNumberGetValue(number: CFTypeRef, kind: CFIndex, out: *mut c_void) -> u8;
    fn CFNumberGetTypeID() -> usize;
    fn CFRelease(cf: CFTypeRef);
}

#[link(name = "Security", kind = "framework")]
extern "C" {
    static kSecGuestAttributeAudit: CFTypeRef;
    static kSecCodeInfoTeamIdentifier: CFTypeRef;
    fn SecCodeCopySelf(flags: u32, code: *mut CFTypeRef) -> i32;
    fn SecCodeCopySigningInformation(code: CFTypeRef, flags: u32, info: *mut CFTypeRef) -> i32;
    fn SecCodeCopyGuestWithAttributes(
        host: CFTypeRef,
        attributes: CFTypeRef,
        flags: u32,
        guest: *mut CFTypeRef,
    ) -> i32;
    fn SecRequirementCreateWithString(
        text: CFTypeRef,
        flags: u32,
        requirement: *mut CFTypeRef,
    ) -> i32;
    fn SecCodeCheckValidity(code: CFTypeRef, flags: u32, requirement: CFTypeRef) -> i32;
}

#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    static kAXTrustedCheckOptionPrompt: CFTypeRef;
    fn AXIsProcessTrusted() -> u8;
    fn AXIsProcessTrustedWithOptions(options: CFTypeRef) -> u8;
    fn AXUIElementCreateApplication(pid: i32) -> CFTypeRef;
    fn AXUIElementCopyAttributeValue(
        element: CFTypeRef,
        attribute: CFTypeRef,
        value: *mut CFTypeRef,
    ) -> i32;
    fn AXUIElementCopyElementAtPosition(
        application: CFTypeRef,
        x: f32,
        y: f32,
        element: *mut CFTypeRef,
    ) -> i32;
    fn AXUIElementGetPid(element: CFTypeRef, pid: *mut i32) -> i32;
    fn AXUIElementPerformAction(element: CFTypeRef, action: CFTypeRef) -> i32;
}

/// Releases a CF object when dropped.
struct Owned(CFTypeRef);

impl Drop for Owned {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe { CFRelease(self.0) }
        }
    }
}

fn cf_string(text: &str) -> Owned {
    Owned(unsafe {
        CFStringCreateWithBytes(
            std::ptr::null(),
            text.as_ptr(),
            text.len() as CFIndex,
            UTF8,
            0,
        )
    })
}

fn rust_string(s: CFTypeRef) -> Option<String> {
    if s.is_null() || unsafe { CFGetTypeID(s) != CFStringGetTypeID() } {
        return None;
    }
    let mut buf = [0 as c_char; 256];
    let ok = unsafe { CFStringGetCString(s, buf.as_mut_ptr(), buf.len() as CFIndex, UTF8) };
    if ok == 0 {
        return None;
    }
    unsafe { CStr::from_ptr(buf.as_ptr()) }
        .to_str()
        .ok()
        .map(str::to_string)
}

fn dictionary(key: CFTypeRef, value: CFTypeRef) -> Owned {
    let keys = [key];
    let values = [value];
    Owned(unsafe {
        CFDictionaryCreate(
            std::ptr::null(),
            keys.as_ptr(),
            values.as_ptr(),
            1,
            std::ptr::addr_of!(kCFTypeDictionaryKeyCallBacks).cast(),
            std::ptr::addr_of!(kCFTypeDictionaryValueCallBacks).cast(),
        )
    })
}

fn ax_text(element: CFTypeRef, attribute: &str) -> Option<String> {
    let name = cf_string(attribute);
    let mut value: CFTypeRef = std::ptr::null();
    let rc = unsafe { AXUIElementCopyAttributeValue(element, name.0, &mut value) };
    let value = Owned(value);
    (rc == 0).then(|| rust_string(value.0)).flatten()
}

/// A password field by what macOS itself says of it: the role or subrole
/// `AXSecureTextField` (agent-desktop and Cua Driver both type into them).
fn secure(element: CFTypeRef) -> bool {
    ["AXRole", "AXSubrole"]
        .iter()
        .any(|a| ax_text(element, a).is_some_and(|v| v.contains("SecureTextField")))
}

/// Whether the element of app `pid` at screen point (x, y) is a password field.
/// None when there is no element of that app there to ask (covered, gone).
pub fn secure_at(pid: i32, x: f64, y: f64) -> Option<bool> {
    let app = Owned(unsafe { AXUIElementCreateApplication(pid) });
    if app.0.is_null() {
        return None;
    }
    let mut hit: CFTypeRef = std::ptr::null();
    let rc = unsafe { AXUIElementCopyElementAtPosition(app.0, x as f32, y as f32, &mut hit) };
    let hit = Owned(hit);
    if rc != 0 || hit.0.is_null() {
        return None;
    }
    let mut owner = 0;
    if unsafe { AXUIElementGetPid(hit.0, &mut owner) } != 0 || owner != pid {
        return None;
    }
    Some(secure(hit.0))
}

/// Whether app `pid`'s focused element is a password field. None when it has none.
pub fn focused_secure(pid: i32) -> Option<bool> {
    let app = Owned(unsafe { AXUIElementCreateApplication(pid) });
    if app.0.is_null() {
        return None;
    }
    let name = cf_string("AXFocusedUIElement");
    let mut focused: CFTypeRef = std::ptr::null();
    let rc = unsafe { AXUIElementCopyAttributeValue(app.0, name.0, &mut focused) };
    let focused = Owned(focused);
    if rc != 0 || focused.0.is_null() {
        return None;
    }
    Some(secure(focused.0))
}

/// An attribute's value, owned (null when absent).
fn ax_copy(element: CFTypeRef, attribute: &str) -> Owned {
    let name = cf_string(attribute);
    let mut value: CFTypeRef = std::ptr::null();
    let rc = unsafe { AXUIElementCopyAttributeValue(element, name.0, &mut value) };
    let value = Owned(value);
    if rc == 0 {
        value
    } else {
        Owned(std::ptr::null())
    }
}

/// The elements of an array-valued attribute (borrowed from `array`, which owns them).
fn items(array: &Owned) -> Vec<CFTypeRef> {
    if array.0.is_null() || unsafe { CFGetTypeID(array.0) != CFArrayGetTypeID() } {
        return Vec::new();
    }
    let count = unsafe { CFArrayGetCount(array.0) }.clamp(0, 200);
    (0..count)
        .map(|i| unsafe { CFArrayGetValueAtIndex(array.0, i) })
        .filter(|e| !e.is_null())
        .collect()
}

/// App `pid`'s structure for the structural-change check (src/structure.rs): its windows (with
/// the sheets, drawers and popovers on each), its focused window, whether a menu is open.
/// None when accessibility answers nothing for that pid (no such app, no permission).
pub fn structure(pid: i32) -> Option<crate::structure::Structure> {
    let app = Owned(unsafe { AXUIElementCreateApplication(pid) });
    if app.0.is_null() {
        return None;
    }
    let listed = ax_copy(app.0, "AXWindows");
    if listed.0.is_null() {
        return None;
    }
    let windows = items(&listed)
        .into_iter()
        .map(|w| {
            let children = ax_copy(w, "AXChildren");
            let sheets = items(&children)
                .into_iter()
                .filter(|c| {
                    ax_text(*c, "AXRole")
                        .is_some_and(|r| matches!(r.as_str(), "AXSheet" | "AXDrawer" | "AXPopover"))
                })
                .count();
            crate::structure::Window {
                id: unsafe { CFHash(w) } as u64,
                subrole: ax_text(w, "AXSubrole").unwrap_or_default(),
                title: ax_text(w, "AXTitle").unwrap_or_default(),
                sheets,
            }
        })
        .collect();
    let focused = ax_copy(app.0, "AXFocusedWindow");
    let element = ax_copy(app.0, "AXFocusedUIElement");
    let menu_open = !element.0.is_null()
        && ax_text(element.0, "AXRole").is_some_and(|r| r == "AXMenu" || r == "AXMenuItem");
    Some(crate::structure::Structure {
        windows,
        focused: (!focused.0.is_null()).then(|| unsafe { CFHash(focused.0) } as u64),
        menu_open,
    })
}

fn ax_bool(element: CFTypeRef, attribute: &str) -> Option<bool> {
    let value = ax_copy(element, attribute);
    (!value.0.is_null() && unsafe { CFGetTypeID(value.0) == CFBooleanGetTypeID() })
        .then(|| unsafe { CFBooleanGetValue(value.0) } != 0)
}

fn ax_int(element: CFTypeRef, attribute: &str) -> Option<i64> {
    let value = ax_copy(element, attribute);
    if value.0.is_null() || unsafe { CFGetTypeID(value.0) != CFNumberGetTypeID() } {
        return None;
    }
    let mut out: i64 = 0;
    const SINT64: CFIndex = 4; // kCFNumberSInt64Type
    (unsafe { CFNumberGetValue(value.0, SINT64, (&mut out as *mut i64).cast()) } != 0)
        .then_some(out)
}

/// Every item of app `pid`'s menu bar below its first menu (the system's Apple menu is never
/// read or pressed), to `depth` levels of submenus. None when the app has no menu bar to read.
pub fn menu_items(pid: i32) -> Option<Vec<crate::menus::MenuItem>> {
    let mut found = Vec::new();
    walk_menus(pid, |path, item| {
        let character = ax_text(item, "AXMenuItemCmdChar").filter(|c| !c.trim().is_empty());
        found.push(crate::menus::MenuItem {
            path: path.to_vec(),
            enabled: ax_bool(item, "AXEnabled").unwrap_or(false),
            shortcut: character.map(|c| {
                (
                    c.to_lowercase(),
                    ax_int(item, "AXMenuItemCmdModifiers").unwrap_or(0),
                )
            }),
        });
        false
    })?;
    Some(found)
}

/// Press the menu item at `path` (titles, top level first) through accessibility: the app's own
/// action, delivered in the background. Some(true) pressed, Some(false) the press failed, None
/// no such item.
pub fn press_menu_item(pid: i32, path: &[String]) -> Option<bool> {
    let mut pressed = None;
    walk_menus(pid, |at, item| {
        if at == path {
            let action = cf_string("AXPress");
            pressed = Some(unsafe { AXUIElementPerformAction(item, action.0) } == 0);
            return true;
        }
        false
    })?;
    pressed
}

/// Visit every menu item under the menu bar (skipping the Apple menu) with its path; `visit`
/// returns true to stop. None when there is no menu bar.
fn walk_menus(pid: i32, mut visit: impl FnMut(&[String], CFTypeRef) -> bool) -> Option<()> {
    let app = Owned(unsafe { AXUIElementCreateApplication(pid) });
    if app.0.is_null() {
        return None;
    }
    let bar = ax_copy(app.0, "AXMenuBar");
    if bar.0.is_null() {
        return None;
    }
    let tops = ax_copy(bar.0, "AXChildren");
    for top in items(&tops).into_iter().skip(1) {
        let title = ax_text(top, "AXTitle").unwrap_or_default();
        if title.is_empty() {
            continue;
        }
        if descend(top, &mut vec![title], &mut visit, 0) {
            break;
        }
    }
    Some(())
}

/// The menu under `element` (its one AXMenu child) and that menu's items, recursively.
fn descend(
    element: CFTypeRef,
    path: &mut Vec<String>,
    visit: &mut impl FnMut(&[String], CFTypeRef) -> bool,
    depth: usize,
) -> bool {
    if depth > 3 {
        return false;
    }
    let children = ax_copy(element, "AXChildren");
    for menu in items(&children) {
        if ax_text(menu, "AXRole").as_deref() != Some("AXMenu") {
            continue;
        }
        let entries = ax_copy(menu, "AXChildren");
        for item in items(&entries) {
            let title = ax_text(item, "AXTitle").unwrap_or_default();
            if title.is_empty() {
                continue; // separators
            }
            path.push(title);
            let stop = visit(path, item) || descend(item, path, visit, depth + 1);
            path.pop();
            if stop {
                return true;
            }
        }
    }
    false
}

#[repr(C)]
#[derive(Clone, Copy)]
struct CGPoint {
    x: f64,
    y: f64,
}

#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGEventCreate(source: CFTypeRef) -> CFTypeRef;
    fn CGEventGetLocation(event: CFTypeRef) -> CGPoint;
    fn CGWarpMouseCursorPosition(point: CGPoint) -> i32;
}

/// Where the pointer is now (global display coordinates, top-left origin).
pub fn pointer() -> Option<(f64, f64)> {
    let event = Owned(unsafe { CGEventCreate(std::ptr::null()) });
    if event.0.is_null() {
        return None;
    }
    let at = unsafe { CGEventGetLocation(event.0) };
    Some((at.x, at.y))
}

/// Put the pointer back where it was (no click; the user sees it move there).
pub fn warp_pointer(x: f64, y: f64) -> bool {
    unsafe { CGWarpMouseCursorPosition(CGPoint { x, y }) == 0 }
}

/// Hands holds Accessibility (as its own responsible process).
pub fn accessibility_trusted() -> bool {
    unsafe { AXIsProcessTrusted() != 0 }
}

#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGPreflightScreenCaptureAccess() -> u8;
    fn CGRequestScreenCaptureAccess() -> u8;
}

/// Hands holds Screen Recording (Cua Driver's window screenshots are Hands').
pub fn screen_recording() -> bool {
    unsafe { CGPreflightScreenCaptureAccess() != 0 }
}

/// Ask macOS to show its Screen Recording prompt for Hands (once; afterwards the
/// user switches it on in System Settings, and macOS wants Hands relaunched).
pub fn request_screen_recording() -> bool {
    unsafe { CGRequestScreenCaptureAccess() != 0 }
}

/// Ask macOS to show its Accessibility prompt for Arslan Hands (D3: the user
/// clicks Allow once). Returns whether it is trusted right now.
pub fn request_accessibility() -> bool {
    let options = dictionary(unsafe { kAXTrustedCheckOptionPrompt }, unsafe {
        kCFBooleanTrue
    });
    unsafe { AXIsProcessTrustedWithOptions(options.0) != 0 }
}

/// This process's own Team ID, or None when unsigned or ad-hoc signed.
pub fn own_team() -> Option<String> {
    let mut me: CFTypeRef = std::ptr::null();
    if unsafe { SecCodeCopySelf(0, &mut me) } != 0 || me.is_null() {
        return None;
    }
    let me = Owned(me);
    let mut info: CFTypeRef = std::ptr::null();
    if unsafe { SecCodeCopySigningInformation(me.0, SIGNING_INFORMATION, &mut info) } != 0
        || info.is_null()
    {
        return None;
    }
    let info = Owned(info);
    let team = rust_string(unsafe { CFDictionaryGetValue(info.0, kSecCodeInfoTeamIdentifier) })?;
    valid_team(&team).then_some(team)
}

pub fn valid_team(team: &str) -> bool {
    team.len() == 10
        && team
            .bytes()
            .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit())
}

/// The code requirement a peer must meet.
pub fn requirement(team: &str) -> String {
    format!(
        "anchor apple generic and certificate leaf[subject.OU] = \"{team}\" and identifier \"arslan-server\""
    )
}

pub fn peer_pid(fd: RawFd) -> Option<i32> {
    let mut pid: libc::pid_t = 0;
    let mut len = std::mem::size_of::<libc::pid_t>() as libc::socklen_t;
    let rc = unsafe {
        libc::getsockopt(
            fd,
            SOL_LOCAL,
            LOCAL_PEERPID,
            std::ptr::addr_of_mut!(pid).cast(),
            &mut len,
        )
    };
    (rc == 0).then_some(pid)
}

/// Does the process on the other end of `fd` satisfy `requirement(team)`?
/// Judged by its audit token (not its pid, which can be recycled).
pub fn peer_allowed(fd: RawFd, team: &str) -> bool {
    if !valid_team(team) {
        return false;
    }
    let mut token = [0u8; 32];
    let mut len = token.len() as libc::socklen_t;
    let rc = unsafe {
        libc::getsockopt(
            fd,
            SOL_LOCAL,
            LOCAL_PEERTOKEN,
            token.as_mut_ptr().cast(),
            &mut len,
        )
    };
    if rc != 0 || len as usize != token.len() {
        return false;
    }
    let data =
        Owned(unsafe { CFDataCreate(std::ptr::null(), token.as_ptr(), token.len() as CFIndex) });
    let attributes = dictionary(unsafe { kSecGuestAttributeAudit }, data.0);
    let mut guest: CFTypeRef = std::ptr::null();
    if unsafe { SecCodeCopyGuestWithAttributes(std::ptr::null(), attributes.0, 0, &mut guest) } != 0
        || guest.is_null()
    {
        return false;
    }
    let guest = Owned(guest);
    let text = cf_string(&requirement(team));
    let mut req: CFTypeRef = std::ptr::null();
    if unsafe { SecRequirementCreateWithString(text.0, 0, &mut req) } != 0 || req.is_null() {
        return false;
    }
    let req = Owned(req);
    unsafe { SecCodeCheckValidity(guest.0, 0, req.0) == 0 }
}

#[link(name = "AppKit", kind = "framework")]
extern "C" {}

#[link(name = "objc")]
extern "C" {
    fn objc_getClass(name: *const c_char) -> *mut c_void;
    fn sel_registerName(name: *const c_char) -> *mut c_void;
    fn objc_msgSend();
}

type Msg0 = unsafe extern "C" fn(*mut c_void, *mut c_void) -> *mut c_void;

fn class(name: &CStr) -> *mut c_void {
    unsafe { objc_getClass(name.as_ptr()) }
}

fn sel(name: &CStr) -> *mut c_void {
    unsafe { sel_registerName(name.as_ptr()) }
}

/// The pid of the app in front (NSWorkspace.frontmostApplication), if any.
pub fn frontmost_pid() -> Option<i32> {
    type MsgPid = unsafe extern "C" fn(*mut c_void, *mut c_void) -> i32;
    unsafe {
        let send0: Msg0 = std::mem::transmute(objc_msgSend as *const ());
        let send_pid: MsgPid = std::mem::transmute(objc_msgSend as *const ());
        let workspace = send0(class(c"NSWorkspace"), sel(c"sharedWorkspace"));
        let front = send0(workspace, sel(c"frontmostApplication"));
        (!front.is_null()).then(|| send_pid(front, sel(c"processIdentifier")))
    }
}

/// The running app `pid` belongs to: (name, bundle id), straight from
/// NSRunningApplication. Hands resolves a pid this way before every Cua call: Cua's own
/// app list scans installed apps too and took ~0.9 s (measured 2026-10-09).
pub fn app_of_pid(pid: i32) -> Option<(String, String)> {
    type MsgWithPid = unsafe extern "C" fn(*mut c_void, *mut c_void, i32) -> *mut c_void;
    type MsgUtf8 = unsafe extern "C" fn(*mut c_void, *mut c_void) -> *const c_char;
    unsafe {
        let send0: Msg0 = std::mem::transmute(objc_msgSend as *const ());
        let send_with_pid: MsgWithPid = std::mem::transmute(objc_msgSend as *const ());
        let send_utf8: MsgUtf8 = std::mem::transmute(objc_msgSend as *const ());
        let app = send_with_pid(
            class(c"NSRunningApplication"),
            sel(c"runningApplicationWithProcessIdentifier:"),
            pid,
        );
        if app.is_null() {
            return None;
        }
        let text = |object: *mut c_void| -> String {
            if object.is_null() {
                return String::new();
            }
            let raw = send_utf8(object, sel(c"UTF8String"));
            if raw.is_null() {
                String::new()
            } else {
                CStr::from_ptr(raw).to_string_lossy().into_owned()
            }
        };
        let name = text(send0(app, sel(c"localizedName")));
        let bundle = text(send0(app, sel(c"bundleIdentifier")));
        (!name.is_empty()).then_some((name, bundle))
    }
}

/// Put `pid`'s app back in front (NSRunningApplication activate). Used when an
/// app Hands acted on brought itself forward: Hands never takes the focus, and
/// a user typing elsewhere must keep typing there.
pub fn give_front_back(pid: i32) -> bool {
    type MsgWithPid = unsafe extern "C" fn(*mut c_void, *mut c_void, i32) -> *mut c_void;
    type MsgActivate = unsafe extern "C" fn(*mut c_void, *mut c_void, usize) -> i8;
    unsafe {
        let send_with_pid: MsgWithPid = std::mem::transmute(objc_msgSend as *const ());
        let send_activate: MsgActivate = std::mem::transmute(objc_msgSend as *const ());
        let app = send_with_pid(
            class(c"NSRunningApplication"),
            sel(c"runningApplicationWithProcessIdentifier:"),
            pid,
        );
        // NSApplicationActivateAllWindows = 1 << 0 is not wanted: just bring it back.
        !app.is_null() && send_activate(app, sel(c"activateWithOptions:"), 0) != 0
    }
}

/// Run as a real (Dock-less) Cocoa app on the main thread: NSApplication,
/// accessory policy, its run loop. Without this, LaunchServices never sees the
/// app finish launching and reports it "not responding" (seen on a real Mac:
/// Finder refused to open it, and it never appeared in the Accessibility list).
pub fn run_app_loop() -> ! {
    type MsgPolicy = unsafe extern "C" fn(*mut c_void, *mut c_void, isize) -> i8;
    unsafe {
        let send0: Msg0 = std::mem::transmute(objc_msgSend as *const ());
        let send_policy: MsgPolicy = std::mem::transmute(objc_msgSend as *const ());
        let class = objc_getClass(c"NSApplication".as_ptr());
        let app = send0(class, sel_registerName(c"sharedApplication".as_ptr()));
        // NSApplicationActivationPolicyAccessory: no Dock icon, never takes focus by itself.
        send_policy(app, sel_registerName(c"setActivationPolicy:".as_ptr()), 1);
        send0(app, sel_registerName(c"run".as_ptr()));
    }
    std::process::exit(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn team_ids_are_ten_upper_alphanumerics_so_the_requirement_cannot_be_injected() {
        assert!(valid_team("XULY3SAJ22"));
        for bad in [
            "",
            "xuly3saj22",
            "XULY3SAJ2",
            "ABC\" or true",
            "XULY3SAJ22X",
        ] {
            assert!(!valid_team(bad), "{bad}");
        }
        assert!(requirement("XULY3SAJ22").ends_with("identifier \"arslan-server\""));
    }

    #[test]
    fn an_unsigned_test_binary_has_no_team_and_a_stranger_is_refused() {
        // cargo's test binaries are ad-hoc signed by the linker: no Team ID.
        assert_eq!(own_team(), None);
        let (a, _b) = std::os::unix::net::UnixStream::pair().unwrap();
        use std::os::fd::AsRawFd;
        assert_eq!(peer_pid(a.as_raw_fd()), Some(std::process::id() as i32));
        // This test process is not signed as arslan-server by any team.
        assert!(!peer_allowed(a.as_raw_fd(), "XULY3SAJ22"));
    }
}

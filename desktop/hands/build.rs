//! On macOS, compile Hands' one Objective-C file (window screenshots through
//! ScreenCaptureKit, src/capture.m) with the system clang and link it in. No build
//! crate: Hands' dependencies run with its grants, so there are as few as possible.
use std::env;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    println!("cargo:rerun-if-changed=src/capture.m");
    if env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("macos") {
        return;
    }
    let out = PathBuf::from(env::var("OUT_DIR").expect("OUT_DIR"));
    let object = out.join("capture.o");
    let library = out.join("libhandscapture.a");
    let target = match env::var("CARGO_CFG_TARGET_ARCH").as_deref() {
        Ok("x86_64") => "x86_64-apple-macos11.0",
        _ => "arm64-apple-macos11.0",
    };
    let status = Command::new("xcrun")
        .args([
            "clang",
            "-fobjc-arc",
            "-O2",
            "-Wall",
            "-Werror",
            "-target",
            target,
            "-c",
        ])
        .arg("src/capture.m")
        .arg("-o")
        .arg(&object)
        .status()
        .expect("xcrun clang");
    assert!(status.success(), "compiling src/capture.m failed");
    let status = Command::new("xcrun")
        .args(["ar", "rcs"])
        .arg(&library)
        .arg(&object)
        .status()
        .expect("xcrun ar");
    assert!(status.success(), "archiving capture.o failed");
    // `@available` in capture.m calls clang's runtime (__isPlatformVersionAtLeast), which
    // rustc does not link (-nodefaultlibs): link the OS X piece of it explicitly.
    let runtime = Command::new("xcrun")
        .args(["clang", "-print-runtime-dir"])
        .output()
        .expect("xcrun clang -print-runtime-dir");
    let runtime = String::from_utf8(runtime.stdout).expect("utf-8 path");
    println!("cargo:rustc-link-arg={}/libclang_rt.osx.a", runtime.trim());
    println!("cargo:rustc-link-search=native={}", out.display());
    println!("cargo:rustc-link-lib=static=handscapture");
    for framework in ["CoreGraphics", "ImageIO", "Foundation"] {
        println!("cargo:rustc-link-lib=framework={framework}");
    }
    // Arslan runs on macOS 11; ScreenCaptureKit's screenshots exist from 14. Weak, so Hands
    // starts on older systems and capture.m answers `needs_macos_14` there.
    println!("cargo:rustc-link-arg=-Wl,-weak_framework,ScreenCaptureKit");
}

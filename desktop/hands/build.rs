//! On macOS, compile Hands' Objective-C files (window screenshots through ScreenCaptureKit,
//! src/capture.m; the key hold, src/keyhold.m; the edge glow, src/glow.m) with the system
//! clang and link them in. No build crate: Hands' dependencies run with its grants, so there
//! are as few as possible.
use std::env;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    let sources = ["src/capture.m", "src/keyhold.m", "src/glow.m"];
    for source in sources {
        println!("cargo:rerun-if-changed={source}");
    }
    if env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("macos") {
        return;
    }
    let out = PathBuf::from(env::var("OUT_DIR").expect("OUT_DIR"));
    let library = out.join("libhandscapture.a");
    let target = match env::var("CARGO_CFG_TARGET_ARCH").as_deref() {
        Ok("x86_64") => "x86_64-apple-macos11.0",
        _ => "arm64-apple-macos11.0",
    };
    let mut objects = Vec::new();
    for source in sources {
        let object = out.join(format!(
            "{}.o",
            source.trim_start_matches("src/").trim_end_matches(".m")
        ));
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
            .arg(source)
            .arg("-o")
            .arg(&object)
            .status()
            .expect("xcrun clang");
        assert!(status.success(), "compiling {source} failed");
        objects.push(object);
    }
    let _ = std::fs::remove_file(&library);
    let status = Command::new("xcrun")
        .args(["ar", "rcs"])
        .arg(&library)
        .args(&objects)
        .status()
        .expect("xcrun ar");
    assert!(status.success(), "archiving the Objective-C objects failed");
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
    // Carbon: IsSecureEventInputEnabled (keyhold.m: no borrow while the user types a password).
    for framework in [
        "CoreGraphics",
        "ImageIO",
        "Foundation",
        "Carbon",
        "AppKit",
        "QuartzCore",
    ] {
        println!("cargo:rustc-link-lib=framework={framework}");
    }
    // Arslan runs on macOS 11; ScreenCaptureKit's screenshots exist from 14. Weak, so Hands
    // starts on older systems and capture.m answers `needs_macos_14` there.
    println!("cargo:rustc-link-arg=-Wl,-weak_framework,ScreenCaptureKit");
}

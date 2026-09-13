# Dependency status — 2026-09-14

The frontend npm audit and desktop npm audit reported zero known advisories after
the lockfile updates. This does **not** mean every ecosystem or platform is clear.
The pypdf lock was also upgraded to 6.16.1 for the reported Python advisories.
Audit results are point-in-time; repeat them when releasing.

## Remaining Linux-only GTK dependency

Cargo.lock still resolves `glib 0.18.5` through GTK3, WebKitGTK and Tauri's Linux
dependency chain. [GHSA-wrw7-89jp-8q8g](https://github.com/advisories/GHSA-wrw7-89jp-8q8g)
describes unsound `VariantStrIter` iteration and possible null-pointer crashes;
the advisory's patched version is 0.20.0. The transitive GTK3 stack here requires
the 0.18 series, so forcing a different major-compatible series is not a safe
lockfile-only repair.

`cargo tree --locked --manifest-path desktop/src-tauri/Cargo.toml --target
aarch64-apple-darwin -i glib` reports no matching target dependency. The same
query for `x86_64-unknown-linux-gnu` shows the GTK3/Tauri chain. This supports
excluding this dependency from the shipped macOS ARM64 target, not declaring the
repository advisory resolved. The release workflow currently builds macOS ARM64
only. Linux desktop distribution must remain unverified until the upstream stack
or a reviewed backport resolves this issue and Linux acceptance is rerun.

Do not dismiss the alert or suppress it to make a dashboard green. Default-branch
alerts for fixed npm/Python locks may remain until those changes reach main and
GitHub rescans them.

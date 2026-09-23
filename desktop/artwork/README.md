# Arslan artwork — September 2026

The approved tapered face retains the silver frosted-glass finish, warm orange
transmitted light, four small nodes, three recessed medium-fine branches and a
smooth nose bridge. `frosted-source.png` is the approved artwork; `mark-source.png`
is the isolated head produced using the built-in imagegen editor from that image.
The flat black/white face is editable vector geometry in the export script.

`node scripts/build_brand_assets.mjs` exports all desktop sizes, ICNS/ICO, web
favicons, previews and avatars. Requires `npm ci --prefix web`, ImageMagick and
macOS `iconutil` for ICNS. Resvg applies the vector silhouette mask consistently;
the mask removes generative transparency fringe without changing the interior
materials. Do not regenerate the approved face for routine size exports.

Settings → Appearance & Language → App icon switches the in-app marks and the
running Dock icon. Native selection is an allowlisted enum saved in the shell's
configuration directory and restored at startup. Finder/Launchpad retain the
bundled default icon. Browser selection is local and also changes the favicon.
Mark URLs are versioned to avoid WebKit retaining an old face after an upgrade.

The existing splash video is preserved. Both root backgrounds are transparent;
only `#frame` paints the boot color. This prevents WebKit's body-background
propagation from filling the rounded corners. Video, fallback and errors share
the same clip, and the original fade timing remains unchanged.

## Verification

- `npm run lint --prefix web` and `npm test --prefix web`
- `cargo test --manifest-path desktop/src-tauri/Cargo.toml --lib`
- `node scripts/artwork_layout_smoke.cjs /path/to/playwright /path/to/evidence`
  checks actual WebKit screenshot alpha in video, error and fade states.
- Manual isolated native preview: run the existing `scripts.companion_smoke_app`
  fixture with temporary `ARSLAN_DATA_DIR` and `ARSLAN_STATIC_DIR=.../web/dist`,
  then set `ARSLAN_ART_PREVIEW_URL=http://127.0.0.1:<port>` and run
  `cargo run --manifest-path desktop/src-tauri/Cargo.toml --example artwork_preview`.
  The preview has its own application identifier and never starts the real sidecar.

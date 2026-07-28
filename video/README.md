# Arslan product demo video

The Arslan product demo, built with [Remotion](https://remotion.dev) — React
components rendered frame by frame to an MP4. Everything on screen is drawn in
code; there are no video assets to keep in sync.

The film is styled as the same set of blueprint plates the README figures use:
near-black ground, engineering grid, registration ticks, amber accent, mono
labels. Palette and type are lifted from `docs/index.html` and `web/src/theme`,
so the video and the product read as one thing.

**Output:** 1920×1080 · 30 fps · 1746 frames · 58.2 s

## Run it

```bash
cd video
npm install

npm run studio    # interactive editor at localhost:3000
npm run build     # renders out/arslan-demo.mp4
npm run still     # renders out/poster.png
npm run lint      # tsc --noEmit
```

`out/` is git-ignored. The committed render lives at
[`docs/assets/arslan-demo.mp4`](../docs/assets/arslan-demo.mp4); re-render and
copy it over when the film changes.

### Headless Linux

Remotion downloads its own Chrome Headless Shell on first render. Where that
download is blocked, point it at an existing one and pick a software GL backend:

```bash
npx remotion render ArslanDemo out/arslan-demo.mp4 \
  --browser-executable=/path/to/chrome-headless-shell \
  --gl=angle
```

## The plates

| # | Scene | Frames | Says |
| --- | --- | --- | --- |
| 00 | `ColdOpen` | 150 | The mark assembles: one host node fanning into three spawns. |
| 01 | `Thesis` | 195 | One host agent · spawns you raised · you press Promote. |
| 02 | `RequestPath` | 315 | A request routes, fans out, runs sandboxed, and comes back in one thread. |
| 03 | `Roster` | 240 | Six spawns with their tools, skill packs, and MCP servers. |
| 04 | `PromotionGate` | 315 | Rewrite → held-out exam → proposal card → you click Promote. |
| 05 | `SecondBrain` | 255 | The note graph grows, then scrubs back to an earlier instant. |
| 06 | `Safety` | 195 | Generated code is network-denied; the credential proxy is the only way out. |
| 07 | `Outro` | 165 | Download, repo, license. |

Scene order and duration live in one place — `SCENES` in `src/theme.ts`.
Re-timing an entry there shifts everything after it, and both the film and the
Studio's per-scene compositions pick the change up. Consecutive scenes overlap
by `SCENE_OVERLAP` frames for the cross-fade, so the film is shorter than the
sum of its plates.

Each plate is also registered as its own composition (`Scene-02-request-path`,
…) so a single scene can be re-timed without scrubbing the whole film.

## Layout

```
src/
  ArslanDemo.tsx      the film — walks SCENES and lays them out with cross-fades
  Root.tsx            composition registry (film + one per scene)
  theme.ts            palette, type, scene table  ← start here
  fonts.ts            vendored face registration
  fonts/              Inter + IBM Plex Mono woff2 (OFL, see fonts/README.md)
  lib/anim.ts         the shared easing / spring / typing / draw-on helpers
  lib/geom.ts         bezier wires, so packets can fly the same path a line draws
  components/         Plate chrome, the mark, and the shared primitives
  scenes/             one file per plate
```

### Fonts

Inter and IBM Plex Mono are vendored under `src/fonts` and inlined into the
bundle as data URIs by the webpack rule in `remotion.config.ts`. A render
therefore needs no network egress and does not care whether the render browser
trusts a proxy's TLS root.

`src/fonts.ts` deliberately does **not** wrap font loading in `delayRender()`.
Both `new FontFace().load()` and `document.fonts.load()` were observed never
settling on a freshly opened render page, which killed whole runs hundreds of
frames in; racing them against a timeout does not help either, because Remotion
replaces `setTimeout` in the render environment so a wall-clock budget never
fires. A data URI needs none of that — the bytes are already in the document,
so the face resolves during layout with `font-display: block` holding text back
until it does.

## Content

Copy and figures come from the repository, not from imagination — the masthead
claims in `README.md`, the promotion-gate and second-brain behaviour described
there, the security posture in `SECURITY.md`, and the client screens in
`docs/assets/screens.jpg`. The spawn roster mirrors the Spawns Ledger.

Numbers shown on the exam and proposal plates (scores, `n=38`, `214 past runs`)
are illustrative sample data, not measurements.

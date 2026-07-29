# Arslan product demo video

The Arslan product demo, built with [Remotion](https://remotion.dev) — React
components rendered frame by frame to an MP4. Everything on screen is drawn in
code; there are no video assets to keep in sync.

The film is styled as the same set of blueprint plates the README figures use:
near-black ground, engineering grid, registration ticks, amber accent, mono
labels. Palette and type are lifted from `docs/index.html` and `web/src/theme`,
so the video and the product read as one thing.

**Output:** 1920×1080 · 30 fps · 1746 frames · 58.2 s · 6.1 MB · no audio track

There is no narration or score, and `remotion.config.ts` sets `muted` so the
render carries no audio stream at all. Left on, Remotion writes a silent AAC
track at its default 320 kbps — 2.4 MB of encoded silence, 28% of the file.

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

## The light cut (`ArslanLight`) — direction proof, not finished

A second, lighter film built around the brand character. **19.6 s, two scenes.**
It is a proof of the direction, not a finished piece — see "What is missing".

The hinge is not decoration: the emblem glowing on the cat's chest **is** the
Arslan mark — one node with legs radiating out of it, the same figure as
`web/public/favicon.svg` and the same figure the request-path diagram draws. So
the cut runs character → chest → mark → architecture with nothing in between.
The creature is already wearing the product's architecture; the film only has
to point at it.

| Scene | Frames | Beat |
| --- | --- | --- |
| `Creature` | 300 | The character sits in negative space. Push into the chest emblem, hand off to the vector mark at the emblem's exact position and size. |
| `Architecture` | 300 | The mark's legs keep going until they reach the spawns. |

### Why it looks the way it does

- **The palette is the product's, not a new one.** `src/lightTheme.ts` copies
  the `:root` / `[data-palette="current"]` block from `web/src/theme/tokens.css`
  — the app's **default** theme. `--primary` (`#D9741A`) runs a hair warmer than
  the dark film's `#e6863c`, which happens to put the product's accent and the
  emblem on the cat's chest at effectively the same colour.
- **The footage sits under its native size** — a card ~1180px wide against
  1280px of source. 1280x720 stretched to full bleed on a 1920 frame is visibly
  soft; a plate floating in negative space is both sharper and closer to the
  language being borrowed.
- **The hand-off is measured, not eyeballed.** The emblem's centre came from the
  centroid of saturated-amber pixels in the lower-centre box of the clip's
  settled final frame — the eyes are the same hue, so the upper third is
  excluded — giving `(0.477, 0.582)` normalised. The mark is placed there and
  scaled by `1 / 0.594`, because its figure fills only the middle ~59% of its
  32-unit viewBox. Sizing the SVG box to the emblem span would have drawn a mark
  visibly smaller than the glow it replaces, and the hand-off would have read as
  a shrink instead of a morph.
- **No springs anywhere.** One long even curve for every move, and the type is
  off screen before the push starts so nothing competes with it.

### The character asset

`public/character/arslan-cat.mp4` is the light half (4.40s to 7.97s) of a
supplied 8-second character clip: head tilt, settle, wall lights up. The head of
the original is framed by dark server racks that fight the light treatment, so
it is cut. **The clip is generated brand imagery, not a screen recording of the
product,** and wherever it ships it should be captioned as such.

### What is missing

- **Sound.** Apple-style pacing leans on a score and there is none here. The
  source clip carries a quiet mechanical bed that could underlay the opening,
  but a real track has to be licensed and supplied. `remotion.config.ts`
  currently renders everything muted.
- **The rest of the story.** Only the request path is covered. The promotion
  gate, the second brain and the sandbox — plates 04 to 06 of the dark film —
  have no light equivalent yet.
- **A close.** The film ends on the diagram, with no wordmark or call to action.

## Layout

```
src/
  ArslanDemo.tsx      the dark film — walks SCENES and lays them out
  ArslanLight.tsx     the light cut — character clip into the architecture
  Root.tsx            composition registry (both films + one per scene)
  theme.ts            dark palette, type, scene table  ← start here
  lightTheme.ts       light palette (the product's own) + measured clip geometry
  fonts.ts            vendored face registration
  fonts/              Inter + IBM Plex Mono woff2 (OFL, see fonts/README.md)
  lib/anim.ts         the shared easing / spring / typing / draw-on helpers
  lib/geom.ts         bezier wires, so packets can fly the same path a line draws
  components/         Plate chrome, the mark, and the shared primitives
  scenes/             one file per plate of the dark film
  scenes/light/       the light cut's scenes
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

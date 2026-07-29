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

`public/character/arslan-cat-open.mp4` is a longer cut of the same source,
2.20s to 7.97s, for the cinematic film — whose opening pull-back needs close to
six seconds where this one needed three and a half. It is a second asset rather
than a re-cut of the first because the emblem hand-off in `scenes/light/Creature`
is measured against that clip's final frame, and moving its edges would silently
invalidate the measurement. Worth knowing when timing a move against it: the
clip contains its own slow push-in, which run against a camera pulling back
holds the cat at roughly constant size while the room opens out around it.

### What is missing

- **Sound.** Apple-style pacing leans on a score and there is none here. The
  source clip carries a quiet mechanical bed that could underlay the opening,
  but a real track has to be licensed and supplied. `remotion.config.ts`
  currently renders everything muted.
- **The rest of the story.** Only the request path is covered. The promotion
  gate, the second brain and the sandbox — plates 04 to 06 of the dark film —
  have no light equivalent yet.
- **A close.** The film ends on the diagram, with no wordmark or call to action.

## The cinematic cut — framings under review

A third treatment, built after the light cut was judged to read as slides
rather than shots. The diagnosis was that it had no camera: every scene was
flat elements fading in and out, so nothing persisted across a cut and there
was no space for a viewer to stay oriented in.

The first attempt at a fix built a room in CSS-3D — a floor plane, a laptop as
hinged planes, an orbiting camera (`Stage`, `MacBook`, `lib/camera3d`, still in
the tree and still driving `ArslanShort`). The camera work was right and the
machine was not: flat gradients and a drawn keyboard read as a diagram of a
laptop, which is a bad thing to be holding the product in a film whose whole
job is to make that product look finished.

So the machine is now a photograph. `components/Mockup` composites the app into
the screen of one of four supplied mock-ups — straight on, three-quarter,
near-profile, top-down — all shot on the same warm set.

### What photographs change, and what they don't

The room becomes baked in. There is no floor to orbit any more, because the
light, the shadow on the linen and the falloff on the back wall were decided
when the picture was made. The camera language is therefore cuts between fixed
angles with a push, a pull or a drift inside each — which is what a product
film mostly is anyway.

What does not change is that the screen is live DOM: real text and a real
`OffthreadVideo` transformed onto the glass rather than baked to a texture, so
it stays sharp under a push and stays editable in code.

### Getting the app onto angled glass

An angled screen in a photograph is a perspective-projected rectangle. That is
not a rotation, not a skew, and not anything `rotateY` can produce — a camera's
projection is projective and CSS's affine primitives are not. `lib/homography`
solves the 3x3 homography from the four corner correspondences and emits it as
`matrix3d`, which is a full projective transform and expresses it exactly.

The four corners are measured, and two earlier methods failed first:

1. Reading the extreme corners of a brightness mask clipped the three-quarter
   shot, whose bottom-right glass falls into shadow (169,141,117 against
   221,205,190 at centre) and drops out under any fixed threshold.
2. Fitting edges as "topmost lit pixel per column" assumed a roughly
   axis-aligned rectangle. The top-down shot is rotated about 25 degrees, where
   the leftmost pixel of a row belongs to a different edge depending on the row.

What holds for all four is that the glass is a convex quadrilateral. So: flood
fill it from its own bright centre (the fill stops dead at the near-black bezel
and at the set, which is bright but violently orange — r-b of 147 against under
60 anywhere on the glass), take the convex hull, find the largest inscribed
quadrilateral to locate the rounded corners, fit each edge by total least
squares over the hull run between them, and intersect neighbours. The corners
come out where the straight edges meet, which is the corner the glass would
have if it were not rounded — the point a homography wants.

### The set, past the edge of the picture

The mock-ups are 2048 square and the film is 16:9, so a wide frame runs off the
image — which is exactly where the last shot goes, since the copy needs empty
set to sit on. Each side is extended by clamping nine colours read down its
outermost pixel columns, then taken out to the picture's darkest corner within
half an image width. The clamp alone was not enough: `front`'s right margin
crosses lit linen, and a bright row extended a whole width became a pale slab
that read as a wall. The picture's own margins cross-fade into the clamp rather
than butting against it, because an interpolated gradient never reproduces an
edge column exactly and a straight join showed as a hairline the length of the
frame.

### Two rules the earlier passes broke

- **Product copy belongs on the screen, never on the machine.** A caption laid
  across the hardware makes the shot read as a laptop advert instead of an app
  demo. This is now structural — the app has nowhere else to go — and the only
  type in world space is the closing CTA, which the top-down mock-up earns by
  having empty amber around the machine for it to sit on.
- **Never two machines in frame.** A mock-up holds exactly one, so this is
  structural too.

### The shots

`ShotMock` renders one framing per frame, so any of them can be checked with
`npx remotion still ShotMock out/shot.png --frame=N` before committing to a
900-frame render.

| | Mock-up | Beat |
| --- | --- | --- |
| A | front | Character full bleed inside the glass. No bezel yet. |
| B | front | The same shot mid pull-back — clip still running, bezel arrives. |
| C | front | The same shot settled. It was a machine on a desk all along. |
| D | threequarter | Cut. The app has the screen: one thread, three spawns, one chart. |
| E | side | Cut. The promotion gate, pushed in so the exam reads. |
| F | top | Cut. Second brain. |
| G | top | The same shot as F, pulled back and drifting; CTA arrives beside it. |

A, B and C are one continuous move, and so are F and G. Only D, E and F are
cuts.

### Known rough edges

- `ArslanShort` is still wired to the CSS-3D stack and has not been rebuilt
  against `Mockup`. The framings above are the sign-off gate for doing that.
- The 30s and 60s cuts are meant to have different shot languages; only the 30s
  spine exists so far.

## Layout

```
src/
  ArslanDemo.tsx      the dark film — walks SCENES and lays them out
  ArslanLight.tsx     the light cut — character clip into the architecture
  ArslanShort.tsx     the cinematic cut (superseded — still on the 3D stack)
  ShotMock.tsx        one framing per frame, for stills review
  lib/homography.ts   rectangle -> photographed glass, as a CSS matrix3d
  components/Mockup.tsx     the photographed machine + its measured screen quad
  components/AppScreen.tsx  the client, laid out at the display's native size
  lib/camera3d.ts     orbiting camera over the CSS-3D world (superseded)
  components/MacBook.tsx  the machine, as hinged planes (superseded)
  components/Stage.tsx    the room: floor, light, environments (superseded)
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

### The mock-up assets

`public/mockups/*.jpg` are four supplied 2048-square renders of the same
machine on the same warm set. They are AI-generated product imagery, in the
style of a commercial mock-up pack — the placeholder artwork on their screens
carries a vendor wordmark, which the film replaces in full, since the app is
composited over every pixel inside the glass. Nothing of that branding survives
into a frame. They ship as JPEG rather than PNG because they are photographic
and the region that would suffer from compression is the region being
overwritten: 905 KB for all four, against 6.9 MB as PNG.

## Content

Copy and figures come from the repository, not from imagination — the masthead
claims in `README.md`, the promotion-gate and second-brain behaviour described
there, the security posture in `SECURITY.md`, and the client screens in
`docs/assets/screens.jpg`. The spawn roster mirrors the Spawns Ledger.

Numbers shown on the exam and proposal plates (scores, `n=38`, `214 past runs`)
are illustrative sample data, not measurements.

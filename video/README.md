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
npm run build     # renders out/arslan-demo.mp4   (the dark film, 58.2s)
npm run short     # renders out/arslan-30s.mp4    (the cinematic cut, 30s)
npm run film      # renders out/arslan-60s.mp4    (the cinematic cut, 60s)
npm run shots     # renders one framing, for review — pass --frame=N
npm run still     # renders out/poster.png
npm run lint      # tsc --noEmit

npm run f1        # the four 30s style cuts — Terminal / Press / System / Pulse
npm run f2
npm run f3
npm run f4
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

## The cinematic cut — `ArslanShort` (30s) and `ArslanFilm` (60s)

A third treatment, built after the light cut was judged to read as slides
rather than shots. The diagnosis was that it had no camera: every scene was
flat elements fading in and out, so nothing persisted across a cut and there
was no space for a viewer to stay oriented in.

The first attempt at a fix built a room in CSS-3D — a floor plane, a laptop as
hinged planes, an orbiting camera. The camera work was right and the machine was
not: flat gradients and a drawn keyboard read as a diagram of a laptop, which is
a bad thing to be holding the product in a film whose whole job is to make that
product look finished. That stack has been deleted.

The machine is now a photograph. `components/Mockup` composites the app into the
screen of one of four supplied mock-ups — straight on, three-quarter,
near-profile, top-down — all shot on the same warm set.

### What photographs change, and what they don't

The room becomes baked in. There is no floor to orbit any more, because the
light, the shadow on the linen and the falloff on the back wall were decided
when the picture was made. The camera language is therefore cuts between fixed
angles with a push, a pull or a drift inside each — which is what a product film
mostly is anyway.

What does not change is that the screen is live DOM: real text and a real
`OffthreadVideo` transformed onto the glass rather than baked to a texture, so it
stays sharp under a push and stays editable in code.

### Getting the app onto angled glass

An angled screen in a photograph is a perspective-projected rectangle. That is
not a rotation, not a skew, and not anything `rotateY` can produce — a camera's
projection is projective and CSS's affine primitives are not. `lib/homography`
solves the 3x3 homography from the four corner correspondences and emits it as
`matrix3d`, which is a full projective transform and expresses it exactly.

The corners are measured, and two earlier methods failed first:

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
quadrilateral to locate the rounded corners, fit each edge by total least squares
over the hull run between them, and intersect neighbours. The corners come out
where the straight edges meet, which is the corner the glass would have if it
were not rounded — the point a homography wants.

### Which layout goes on which plate

Not interchangeable, and the reason is worth stating because it looks like a
styling preference and is not. A tilted plate foreshortens the glass, so a line
that is horizontal in the layout climbs or falls across the frame. On the
three-quarter mock-up the glass drops 17% of its width from left to right.

- **Full-width bands stacked down the display** — the sandbox log, with its
  status cards above it — need a flat plate. At 17% the left edge of one band
  sits higher on screen than the band above it does on the right, and the two
  read as overlapping when they are not.
- **Tables** need a flat plate for the same reason, more acutely: a row of cells
  climbs the frame diagonally and stops reading as a row at all.
- **Side-by-side panels** — the promotion gate — are fine on a tilt, because the
  split runs with the foreshortening rather than across it.
- **A node graph** is the one thing that wants the top-down plate. It has no
  rows to misread, and the rotation makes the shot.

### The set, past the edge of the picture

The mock-ups are 2048 square and the film is 16:9, so a wide frame runs off the
image — which is exactly where the last shot goes, since the copy needs empty set
to sit on. Each side is extended by clamping nine colours read down its outermost
pixel columns, then taken out to the picture's darkest corner within half an
image width. The clamp alone was not enough: `front`'s right margin crosses lit
linen, and a bright row extended a whole width became a pale slab that read as a
wall. The picture's own margins cross-fade into the clamp rather than butting
against it, because an interpolated gradient never reproduces an edge column
exactly and a straight join showed as a hairline the length of the frame.

### Two rules the earlier passes broke

- **Product copy belongs on the screen, never on the machine.** A caption laid
  across the hardware makes the shot read as a laptop advert instead of an app
  demo. This is now structural — the app has nowhere else to go — and the only
  type in world space is the closing CTA, which the top-down mock-up earns by
  having empty amber around the machine for it to sit on.
- **Never two machines in frame.** A mock-up holds exactly one, so this is
  structural too.

### The two cuts

Both are lists of shots in `lib/shots`, which is why re-timing either is an edit
to two numbers rather than a rewrite. They share a spine on purpose: both open on
the character and pull back until it turns out to have been a screen, and both
close by pulling back off the machine into the download rather than cutting to
it. Neither ever comes to rest before a cut — `tail` spreads a shot's move over
more frames than the shot is on screen, so the camera is still travelling when
the film cuts away.

**`ArslanShort` — 900 frames, 30.0s.** Built out of arrivals. It has to win a
scroll, so shots start already moving, the app is pre-rolled to land each cut on
a screen mid-thought, and nothing is held.

| Shot | Frames | Mock-up | Beat |
| --- | --- | --- | --- |
| `open` | 0-108 | front | Character full bleed inside the glass. Barely creeping. |
| `reveal` | 108-200 | front | Same shot. Bezel, lid, deck, linen; the clip dissolves into the app under the move. |
| `thread` | 200-358 | threequarter | One thread, three spawns, one chart. |
| `promotion` | 358-526 | side | The held-out exam, and Promote. |
| `brain` | 526-682 | top | The note graph and its time axis. |
| `close` | 682-900 | top | Same shot, pulled back. The machine goes right and the download arrives. |

**`ArslanFilm` — 1800 frames, 60.0s.** Built out of holds, not the 30 stretched.
Shots start nearer their subject and travel less; views get long enough to finish
a thought and sit for a beat. Two views the short cut has no room for are here:
the spawns ledger, which turns "it has sub-agents" into a roster with
capabilities attached, and diagnostics, where the sandbox refuses a direct
connection and the credential proxy is the only way out. The host thread also
gets a second exchange — `ScreenThread`'s `extended` prop — because seven seconds
on a view that finishes building in four reads as a screenshot no matter what the
camera is doing.

| Shot | Frames | Mock-up | Beat |
| --- | --- | --- | --- |
| `open` | 0-168 | front | Nearly still for five seconds. A face, before any claim. |
| `reveal` | 168-300 | front | Same shot. The pull-back. |
| `settle` | 300-390 | front | Same shot. The clip hands over to the app; the film lets that be true. |
| `thread` | 390-606 | threequarter | One thread, three spawns, a chart, and a follow-up. |
| `spawns` | 606-798 | front | The roster, with tools, skill packs and egress. |
| `promotion` | 798-1056 | threequarter | The longest shot in either film. The exam lands, is read, then acted on. |
| `safety` | 1056-1272 | side | Generated code with no network; the proxy holds the key. |
| `brain` | 1272-1506 | top | The note graph. |
| `close` | 1506-1800 | top | Same shot, pulled back, into the download. |

### Reviewing framings

`ShotMock` renders one framing per frame, so any of them can be checked with
`npx remotion still ShotMock out/shot.png --frame=N` before committing to a
900- or 1800-frame render.

### Output and encoding

Renders come out at the config's `crf 17`, which is a master setting: the 30s cut
lands at 36 MB. Photographic frames with linen texture and a broad amber gradient
compress nothing like the dark film's flat vector plates, which is why that one
fits 58 seconds into 6 MB. Re-encode for delivery rather than shipping the
master — `crf 24` brings 30 seconds to 8.9 MB with the type still crisp and no
banding in the gradient:

```bash
ffmpeg -i out/arslan-30s.mp4 -c:v libx264 -crf 24 -preset slow \
  -pix_fmt yuv420p -movflags +faststart docs/assets/arslan-30s.mp4
```

## Four 30-second cuts, one per visual language

A separate exercise from the cinematic cut: four films that share a product and
nothing else. Each lives in `src/films/` and is self-contained — they import
fonts and no other common code. That is deliberate. Shared components are how
four films quietly become one film with four colour schemes, and the brief here
was maximum stylistic distance.

| | Composition | Ground | Argument | Ends on |
| --- | --- | --- | --- | --- |
| F1 | `F1-Terminal` | Near-black, monospace | Demonstration. A terminal and a TUI; no photography and no screenshot at all, on the argument that this product's interface *is* text. | `brew install` + macOS download |
| F2 | `F2-Press` | Paper, 12-column grid | Assertion. Type at a size you cannot look away from; almost no UI. | Colophon + macOS download |
| F3 | `F3-System` | Near-black, depth, glow | Structure. A host node, six spawns at six depths, light travelling between them. No interface at all. | Wordmark + macOS download |
| F4 | `F4-Pulse` | White and saturated amber | Impact. Built for a feed: cards thrown into a grid, a slammed number, an odometer, three shutter flashes. | Wordmark + macOS download |

```bash
npx remotion render F1-Terminal out/F1-Terminal.mp4 --gl=angle
```

### Shots are taken, not invented

The moves come from the video-shotcraft card library, and its parameters are
honoured where they are counter-intuitive — which is most of the places they
matter:

- **Typing is frame-quantised.** `substring(0, floor((f - start) / step))`, never
  an interpolation. Any easing applied to typing reads as a loading bar rather
  than as someone typing, and the block cursor is a square wave for the same
  reason: a cursor that fades belongs to a web page.
- **The deal cue curve collapses rather than decreasing evenly.**
  `30 + 4i − 0.16·i(i−1)`. Evenly spaced cards read as mechanical on sight, and
  the anticipation beat before the first card is section-level, not per-card —
  per-card anticipation flattens the acceleration it exists to set up.
- **A slam uses ease-IN.** Ease-out is a thing being set down; ease-in is a
  thing being dropped. The ring's expansion runs on out-cubic while its fade
  runs linear, because sharing one curve makes it vanish before it has finished
  opening.
- **The odometer overshoots half a row and snaps back**, and its digits stop
  left to right 7 frames apart. Without the overshoot it reads as sliding to a
  stop, which is not a mechanism; stopping together loses the "tk, tk, tk" the
  move exists for.
- **Beat-cut intervals halve** (16/12/8/6/4), and the flash crops run wide →
  panel → detail. Decrementing evenly does not read as acceleration, and any
  other crop order reads as a mis-cut.
- **Ambient freezes last.** In F3 the orb layer eases to a stop *after* the
  flylines have resolved, and the flyline heads are unmounted rather than faded
  to zero opacity, because an element at zero opacity is still animating and the
  shot never actually comes to rest.
- **`letter-spacing` is never animated.** F2's tracking-expand moves each
  character with `translateX` against a fixed final tracking; animating the
  property itself re-lays-out the line every frame and judders.

### One thing the cards taught that generalises

Several of the parameters in these files are two to twelve times larger than the
"obvious" value, and the library is explicit about why: they were tested at the
obvious value, found imperceptible at normal speed, and raised until they could
be seen. The overshoot on a rising word is 10% rather than 6%; the anticipation
on the card stack is tens of pixels rather than a few. The check is to watch at
speed and ask whether the beat is visible without stepping frames — if it is
not, it is not there.

## F5 Blueprint — the square one, for LinkedIn

A fifth cut, and the only one with a named destination. **1080×1080, 30s.**

Square is not a stylistic choice: a square post takes roughly half again the
vertical space of 16:9 in a LinkedIn feed. It also suits the content, since a
block diagram reads top-to-bottom and that is the axis a square gives you.

The register is an engineering drawing — sheet border, title block, revision
line, dimension leaders, mono annotation, one accent. Nothing moves that a pen
could not have drawn. That is deliberate: it goes out under the byline of
someone who is not an engineer, so the film should not imitate a screen
recording of the software it is explaining. A drawing is honest about being an
explanation.

| Sheet | Frames | Draws |
| --- | --- | --- |
| 1/4 · REQUEST PATH | 0–250 | You → host agent → a decision diamond that prefers *not* to route → back to one thread. |
| 2/4 · SANDBOX | 250–500 | The dashed kernel boundary, a crossed-out arrow to the internet, and the credential proxy as the only way out. |
| 3/4 · PROMOTION GATE | 500–790 | Run history → a new prompt → both arms replayed → the threshold → a FAIL branch drawn to a stub that goes nowhere, and a PASS branch to your inbox. |
| 4/4 · GENERAL ARRANGEMENT | 790–900 | The parts list, and the download. |

Every stroke uses `draw-svg-trace` properly: `pathLength={1}` with
`strokeDasharray="1"` and the offset run 1 → 0, so no path length is ever
measured, and each one carries a pen head — a second, thicker, short-dash copy
of the same path riding at the front. Without the head it is a border getting
longer; with it, someone is drawing. Each shape closes on a two-frame darken
that eases back over six, which is the full stop.

One failure worth recording: a sheet whose slot is shorter than its own last cue
simply never finishes, and sheets 2 and 4 overran a first split by 18 and 8
frames. Nothing in a still review shows that — the missing element is missing
from frames nobody chose to look at. The slot comments in `SHEETS` now carry
each sheet's last cue so the arithmetic is visible.

The accompanying post is in
[`docs/marketing/linkedin-post.md`](../docs/marketing/linkedin-post.md).

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

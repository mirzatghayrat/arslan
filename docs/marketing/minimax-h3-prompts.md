# MiniMax H3 (Hailuo 3.0) — prompt pack for Arslan

Prompts for generating Arslan brand footage with MiniMax H3, and the reasoning
for what is generated and what is deliberately not.

## What the model can actually do

Verified against vendor and integrator documentation, August 2026:

| | H3 / Hailuo 3.0 |
| --- | --- |
| Duration | 4–15 s, whole seconds |
| Frame rate | 24 fps |
| Resolution | up to 2K |
| Audio | **native stereo, generated with the picture** |
| Image-to-video | one image, **or a first + last frame pair** |
| Camera control | bracketed commands, up to 3 per shot |
| Text / UI / signage | improved over 2.x, and it honours explicit restrictions |

Syntax rules that matter:

- Camera commands go in square brackets, comma-separated, **no space between
  `]` and the prompt text**: `[Push in,Pedestal up]a cream-white robotic cat…`
- Three movements per shot maximum.
- Motion has to be stated explicitly. Left unsaid, the model defaults to a
  generic zoom.
- The formula that performs best is **subject → action → environment → camera →
  lighting → treatment → ending state**. The ending state is the part people
  skip and it is what makes a clip cuttable.

## The one decision that matters more than the prompts

**Do not ask H3 to generate the Arslan interface.** Not the composer, not the
Spawns Ledger, not a laptop with the app on it, not "a dashboard".

H3's text rendering is better than it was and that makes this worse, not
better: it will produce a confident, plausible, *fictional* Arslan. This repo
already shipped four finished films with invented facts in them, which is why
`video/src/facts.ts` exists and why every claim in every film now carries a
source comment. A generated interface is the same failure with no fix available
— you cannot correct a hallucinated screen with a constant.

There is also no need. `video/public/rec/` holds twelve 2560×1680 Retina
screenshots of the real client. Anything that has to show the product uses
those, in Remotion, where it is composited rather than imagined.

**What H3 is genuinely the right tool for is the character**, and that is a real
gap. `public/character/arslan-cat-open.mp4` is 5.79 seconds — the entire supply.
F7 has to use it twice because there is nothing else. Every prompt below extends
that one asset.

Two further reasons this is the right use:

- **Sound.** The video README's "What is missing" list opens with sound. H3
  generates stereo audio alongside the picture, so a mechanical room tone and a
  servo click arrive with the clip instead of needing to be licensed.
- **The push.** F7 pushes 3.4× into the chest emblem on 1280×720 source and
  spends the last of it at 4.5 px of blur to hide the upscale. Shot 3 below
  gives that move as real footage.

## Reusable blocks

Paste these verbatim into every shot so the creature and the room stay the same
between generations. Drift between clips is the main failure mode of a
multi-clip cut, and repeating the description is most of the fix; seeding from a
frame of the existing clip is the rest.

**CHARACTER** —
> a cream-white robotic cat with matte ceramic body panels, amber-orange inner
> ears, round glowing amber eyes, black articulated joints at the shoulders and
> hips, a segmented cream-and-black mechanical tail, and a small four-armed
> amber emblem glowing at the centre of its chest

**ROOM** —
> a pale off-white circuit-board wall, its etched traces glowing warm amber,
> soft diffuse studio light, shallow depth of field

**RESTRICTIONS** (append to every prompt) —
> No text, no captions, no subtitles, no user interface, no screens, no
> monitors, no laptop, no logos, no watermark, no human hands, no people. Do not
> change the cat's colour or markings.

**Seed frames** for image-to-video are in `video/out/seed/` — regenerate with:

```bash
cd video
for t in 0.2 2.6 5.6; do
  npx remotion ffmpeg -y -ss $t -i public/character/arslan-cat-open.mp4 \
    -frames:v 1 -vf scale=1280:-1 out/seed/seed-$t.png
done
```

`seed-5.6.png` is the settled pose with the wall fully lit — the best general
starting frame. `seed-0.2.png` is the wall unlit, for anything that has to
light up.

---

## A. One standalone clip

If you only want to generate one thing. 15 s, 16:9, text-to-video.

```
A cream-white robotic cat with matte ceramic body panels, amber-orange inner
ears, round glowing amber eyes, black articulated joints, a segmented
cream-and-black mechanical tail, and a small four-armed amber emblem glowing at
the centre of its chest sits upright and perfectly still in the centre of the
frame. Its eyes brighten, the chest emblem pulses once, and warm amber light
spreads outward from behind it along the etched traces of a pale off-white
circuit-board wall until the whole wall is lit. The cat tilts its head a few
degrees toward the lens and its tail curls slowly around its feet. [Push
in,Pedestal up]Soft diffuse studio light, shallow depth of field, matte ceramic
and warm amber, calm and expensive, commercial product-film finish, the cat
stays centred throughout. Audio: a low mechanical room tone and one soft servo
click as the head turns, no music, no voice. Ending state: the cat settled and
still, wall fully lit, chest emblem the brightest point in the frame.

No text, no captions, no subtitles, no user interface, no screens, no monitors,
no laptop, no logos, no watermark, no human hands, no people. Do not change the
cat's colour or markings.
```

---

## B. The shot pack

Six clips that cut together, and cut into the existing Remotion films. Generate
each separately; assemble in the edit.

### 1 · Wake — 6 s, i2v from `seed-0.2.png`

```
[Static shot]CHARACTER sits upright and motionless in the centre of the frame.
Its eyes brighten from dim to full amber, the chest emblem pulses on, and warm
amber light spreads outward from behind the cat along the etched traces of ROOM
until the whole wall is lit. Nothing else moves. Soft diffuse studio light,
matte ceramic and warm amber, calm, commercial product-film finish. Audio: a
low mechanical hum rising, one soft power-on click, no music. Ending state: the
cat still, the wall fully lit, the emblem glowing steadily.
```
*Locked camera on purpose — the light does the work. It is also the only shot
here that can open a film.*

### 2 · Regard — 6 s, i2v from `seed-5.6.png`

```
[Push in]CHARACTER sits upright in ROOM. It turns its head a few degrees toward
the lens, one ear flicks, and it holds the look. The tail sways once and
settles. The camera pushes in slowly and steadily to a chest-up framing. Soft
diffuse studio light, shallow depth of field, calm, commercial product-film
finish. Audio: low room tone and one soft servo click as the head turns, no
music. Ending state: the cat looking directly at the lens, still, chest emblem
centred and glowing.
```

### 3 · Emblem — 5 s, i2v from `seed-5.6.png`

```
[Push in]Extreme slow push onto the small four-armed amber emblem glowing at
the centre of CHARACTER's chest, until the emblem fills the frame and its glow
blooms softly past the edges. The cat does not move. Everything but the emblem
falls out of focus and into darkness. Macro lens, shallow depth of field, warm
amber against matte cream ceramic. Audio: low room tone and a rising electrical
hum, no music. Ending state: the emblem filling the frame, blown out at its
centre, the surroundings black.
```
*This is the shot worth generating most. F7 currently fakes it by pushing 3.4×
into 720p and hiding the last of it behind 4.5 px of blur. Its ending state —
one amber glow on black — cuts straight into F8's opening.*

### 4 · Many — 8 s, text-to-video

```
[Static shot]A single point of warm amber light floats in the centre of a black
void. It pulses once, then three smaller amber lights separate from it and
drift outward and downward on slow, even arcs, each settling into place and
holding steady while the original light stays where it is. Fine dust drifts
through the beams. Volumetric light, deep black background, warm amber only, no
other colour. Audio: a low sustained tone and three soft chimes as the lights
settle, no music. Ending state: one bright light above, three smaller lights
below it, all still.
```
*"One Becomes Many" as an image rather than a caption, and it is the shape of
the Arslan mark without asking the model to draw a logo. No product claim is
made, so nothing here can be wrong.*

### 5 · Room — 8 s, i2v from `seed-5.6.png`

```
[Truck left,Zoom out]CHARACTER sits lit in a shallow alcove in ROOM. The camera
trucks slowly left and pulls back to reveal a long row of identical alcoves
receding into the dark, each one empty and unlit. The cat stays lit and stays
still. Soft diffuse light on the cat only, deep falloff into black, shallow
depth of field. Audio: low room tone, a distant mechanical hum, no music.
Ending state: the cat small in frame at the right, one lit alcove among many
dark ones.
```
*Scale without a claim. Read it as "one host, room for as many as you raise".*

### 6 · Settle — 5 s, i2v from `seed-5.6.png`

```
[Static shot]CHARACTER sits in ROOM. It blinks slowly once, the tail curls in
around its feet, and the wall's amber traces dim smoothly to black from the
edges of the frame inward until only the chest emblem is still lit. Soft
diffuse light fading to a single warm point. Audio: room tone fading to silence,
one soft mechanical settle, no music. Ending state: a black frame with one small
amber glow at its centre.
```
*Built as a hand-off. Its last frame is F8's first frame.*

---

## Settings

| | |
| --- | --- |
| Aspect | 16:9 to cut with the film family; generate a 9:16 pass separately for social — do not crop |
| Resolution | 2K, downscale in the edit |
| Duration | as listed; the model bills by the second and shots 3 and 6 do not need more |
| Audio | keep it. If a licensed score arrives later, strip with `-an` at the mux |

## Two failure modes to expect

- **Drift between clips.** The creature will not be identical across
  generations. Seed every shot from a frame of the existing clip, repeat the
  CHARACTER block verbatim, and where two clips have to butt together, use the
  first + last frame pair rather than trusting the prompt.
- **The model inventing a screen anyway.** If a monitor, a laptop or a caption
  appears, it is not a prompt-weighting problem to solve by re-rolling — throw
  the take away. Anything that looks like Arslan's interface and is not a
  screenshot of Arslan's interface does not go in a film from this repo.

## Sources

- <https://www.marktechpost.com/2026/08/01/minimax-releases-minimax-h3-an-omni-modal-video-model-that-generates-15-second-2k-clips-with-native-stereo-audio/>
- <https://huggingface.co/blog/ResterChed/minimax-h3-hailuo-3-0>
- <https://kie.ai/minimax-h3>
- <https://www.minimax.io/news/01-director>
- <https://piapi.ai/docs/hailuo-api/hailuo-director-mode>
- <https://minimax-h3.app/prompt-guide>
- <https://blog.segmind.com/hailuo-minimax-ai-video-prompt-guide/>
- <https://curiousrefuge.com/blog/hailuo-minimax2-ai-video-generator-review>

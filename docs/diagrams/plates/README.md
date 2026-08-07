# README plates

The three raster images at the top of the READMEs are built from the sources in
this directory rather than drawn by hand:

| Output | Source | What it is |
| --- | --- | --- |
| `../../assets/banner.jpg` | `banner.html` | The masthead, over the same clay frame the project site opens on. |
| `../../assets/screens.jpg` | `screens.html` | Four screens of the shipped client in clay monitors. |
| `../../assets/demo.gif` | `gifframes.py` | The same four screens, dissolving. |

They are generated because all three bake type into pixels — the banner's spec
line (`macOS 11+ · Apple Silicon · signed & notarized · Apache-2.0 · pre-v1`),
the plate captions, the GIF's four beats. A raster is where a claim goes to
stop being greppable, so when one of those facts changes the picture has to be
re-renderable, not repainted.

The screenshots are the real client, read straight out of `../../assets/site/`,
so the README and the project site cannot drift apart. Nothing here invents a
UI: if a screen is not in that directory, it does not go in a plate.

## Rebuilding

```bash
sh build.sh                     # writes banner.jpg, screens.jpg, demo.gif here
FFMPEG=/path/to/ffmpeg sh build.sh
```

It needs a Chromium with `--screenshot` and an `ffmpeg`. The path to the
headless shell is the one line at the top of `build.sh` you may have to edit.

Copy the three results over `../../assets/` once they look right — the build
deliberately does not write there itself, so a half-finished plate never lands
in a README.

## The dissolve

`gifframes.py` writes the GIF's cross-fade as 24 discrete HTML frames because
the ffmpeg this repository renders with is built `--disable-filters`: no
`xfade`, no `fps`, no `overlay`. `scale`, `split`, `palettegen` and
`paletteuse` survive, and those are enough to turn a frame sequence into a GIF.

## Fonts

`fonts/` holds latin-subset `woff2` files of [Inter](https://github.com/rsms/inter)
and [IBM Plex Mono](https://github.com/IBM/plex), both under the SIL Open Font
License 1.1, which permits redistributing the files with this project. They are
vendored rather than linked so a build never depends on network egress, and so
the type in a plate is the same on every machine — these images ship as pixels,
and a missing font would silently reset them to whatever the render host had.

#!/bin/sh
# Rebuilds the three README plates from the sources in this directory.
#
# They are built here rather than by hand because all three bake type into a
# raster: the banner's spec line, the plate labels and the GIF captions all have
# to be re-renderable when a fact changes. Fonts are the vendored Inter + IBM
# Plex Mono the films use, so nothing depends on the reader's machine.
#
#   sh build.sh          # writes banner.jpg, screens.jpg, demo.gif here
#
# Copy the results into docs/assets/ once they look right.
set -e
cd "$(dirname "$0")"
SHELL_BIN=/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell
FFMPEG=${FFMPEG:-ffmpeg}

shot() { # shot <html> <png> <w> <h>
  "$SHELL_BIN" --no-sandbox --disable-gpu --hide-scrollbars \
    --screenshot="$2" --window-size="$3,$4" --virtual-time-budget=5000 "$1" >/dev/null 2>&1
}

# ---- banner + screens plate -------------------------------------------------
shot banner.html banner.png 2024 860
shot screens.html screens.png 2024 1580
"$FFMPEG" -loglevel error -y -i banner.png  -q:v 3 banner.jpg
"$FFMPEG" -loglevel error -y -i screens.png -q:v 3 screens.jpg

# ---- demo.gif: four real screens, dissolving --------------------------------
# The dissolve is rendered as discrete opacity steps in the browser because the
# vendored ffmpeg is built with --disable-filters: no xfade, no fps, no overlay.
# palettegen/paletteuse/scale/split are the ones that survive, and they are
# enough to turn a frame sequence into a GIF.
python3 gifframes.py
for f in f0*.html; do shot "$f" "${f%.html}.png" 1400 960; done
rm -rf seq && mkdir seq
python3 - <<'PY'
import shutil
k = 0
for i in range(24):                      # 4 slides, each followed by 5 dissolve steps
    reps = 17 if i % 6 == 0 else 1       # 12fps: ~1.4s hold, 5/12s dissolve
    for _ in range(reps):
        shutil.copy(f'f{i:03d}.png', f'seq/{k:04d}.png'); k += 1
PY
"$FFMPEG" -loglevel error -y -framerate 12 -i seq/%04d.png \
  -filter_complex "[0:v]scale=900:-2[v];[v]split[a][b];[a]palettegen=max_colors=200[p];[b][p]paletteuse=dither=bayer:bayer_scale=3" \
  -loop 0 demo.gif
rm -rf seq f0*.png f0*.html

ls -la banner.jpg screens.jpg demo.gif

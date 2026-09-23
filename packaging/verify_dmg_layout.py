"""Inspect the actual DMG before signing; always detach the verification mount."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile


def verify(volume: Path) -> None:
    from ds_store import DSStore
    from PIL import Image

    assert (volume / "Arslan.app/Contents/Info.plist").is_file(), "Application missing"
    assert os.readlink(volume / "Applications") == "/Applications", "Install target invalid"
    with DSStore.open(str(volume / ".DS_Store"), "r") as store:
        window = store["."]["bwsp"]
        view = store["."]["icvp"]
        assert window["WindowBounds"] == "{{180, 180}, {720, 440}}", "Window size drift"
        assert not any(window[k] for k in ("ShowToolbar", "ShowSidebar", "ShowStatusBar"))
        assert view["backgroundType"] == 2 and view["backgroundImageAlias"]
        assert view["arrangeBy"] == "none" and view["iconSize"] == 112
        assert store["Arslan.app"]["Iloc"] == (206, 227)
        assert store["Applications"]["Iloc"] == (514, 227)
    with Image.open(volume / ".background.tiff") as image:
        sizes = []
        for frame in range(image.n_frames):
            image.seek(frame)
            sizes.append(image.size)
        assert sizes == [(720, 440), (1440, 880)], f"Retina background missing: {sizes}"
    print("DMG layout: application, install target, background, Retina and Finder layout verified")


def main() -> None:
    dmg = Path(sys.argv[1]).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="arslan-dmg-check-") as folder:
        mount = Path(folder) / "volume"
        mount.mkdir()
        subprocess.run(["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(dmg)], check=True, stdout=subprocess.DEVNULL)
        try:
            verify(mount)
        finally:
            subprocess.run(["hdiutil", "detach", str(mount)], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()

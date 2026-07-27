"""Shell window configuration that the web layer silently depends on.

Both facts here are packaged-only: they hold in a dev browser no matter what
the shell does, so nothing but a pin like this can protect them.
"""
from __future__ import annotations

import pathlib

LIB = (pathlib.Path(__file__).resolve().parents[1]
       / "desktop" / "src-tauri" / "src" / "lib.rs").read_text()


def test_drag_drop_handler_is_disabled():
    """wry intercepts NSDragging on macOS and, once it reports the drop
    handled, never invokes the OS default — which is what delivers HTML5
    dragover/drop to the webview. With the handler on, every HTML drop target
    in the app is dead in the .dmg while working perfectly in dev."""
    assert "disable_drag_drop_handler()" in LIB, (
        "the webview must hand file drags to the page, or the second brain's "
        "drop zone (and every other HTML drop target) is inert when packaged"
    )


def test_overlay_title_bar_still_has_a_drag_source():
    """titleBarStyle Overlay leaves no native strip to grab, so the window can
    only be moved via data-tauri-drag-region in the SPA. Losing the capability
    grant would make the window immovable."""
    cap = (pathlib.Path(__file__).resolve().parents[1] / "desktop" / "src-tauri"
           / "capabilities" / "remote-ui-drag.json").read_text()
    assert "core:window:allow-start-dragging" in cap

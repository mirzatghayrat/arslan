"""Finder layout written by dmgbuild, without Finder/AppleScript automation."""
from pathlib import Path

application = Path(defines["app"]).resolve()  # noqa: F821 - injected by dmgbuild
if not application.is_dir() or application.suffix != ".app":
    raise ValueError("app must name an existing application bundle")

format = "UDZO"
files = [str(application)]
symlinks = {"Applications": "/Applications"}
icon = str(application / "Contents/Resources/icon.icns")
background = defines["background"]  # noqa: F821 - injected by dmgbuild
window_rect = ((180, 180), (720, 440))
icon_locations = {application.name: (206, 227), "Applications": (514, 227)}
icon_size = 112
text_size = 14
label_pos = "bottom"
arrange_by = None
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
default_view = "icon-view"
include_icon_view_settings = True
include_list_view_settings = False
show_icon_preview = False

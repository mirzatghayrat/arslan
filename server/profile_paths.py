"""Pure profile path resolution, safe before configuration/secret bootstrap."""
import os
from pathlib import Path
import sys


def default_data_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "Arslan"


def resolve_data_dir() -> Path:
    raw = os.environ.get("ARSLAN_DATA_DIR")
    directory = Path(raw) if raw else default_data_dir()
    return Path(os.path.expandvars(os.path.expanduser(str(directory)))).resolve()


def resolve_database() -> Path:
    return Path(os.environ.get("ARSLAN_DB_PATH", str(resolve_data_dir() / "arslan.db")))

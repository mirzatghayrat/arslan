"""Server configuration sourced from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Immutable server settings read once from the environment."""

    api_token: str
    secret_key: str
    db_path: str
    spawns_dir: Path
    static_dir: str = ""
    app_version: str = "0.1.0"
    attach_extract_char_limit: int = 12000

    @property
    def db_url(self) -> str:
        """Async SQLAlchemy URL for the SQLite database."""
        return f"sqlite+aiosqlite:///{self.db_path}"


def load_settings() -> Settings:
    """Build a Settings instance from current environment variables."""
    data_dir = Path(os.environ.get("ARSLAN_DATA_DIR", "data"))
    db_path = os.environ.get("ARSLAN_DB_PATH", str(data_dir / "arslan.db"))
    spawns_dir = Path(os.environ.get("ARSLAN_SPAWNS_DIR", str(data_dir / "spawns")))
    static_dir = os.environ.get("ARSLAN_STATIC_DIR", str(Path(__file__).parent / "static"))
    return Settings(
        api_token=os.environ.get("ARSLAN_API_TOKEN", ""),
        secret_key=os.environ.get("ARSLAN_SECRET_KEY", ""),
        db_path=db_path,
        spawns_dir=spawns_dir,
        static_dir=static_dir,
        attach_extract_char_limit=int(os.environ.get("ARSLAN_ATTACH_CHAR_LIMIT", "12000")),
    )


# Module-level singleton used by the app and dependencies.
settings = load_settings()

"""Server configuration sourced from environment variables."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _default_data_dir() -> Path:
    """Per-platform application-data directory used when ``ARSLAN_DATA_DIR`` is unset.

    The old default was the CWD-relative ``Path("data")``, so the SQLite "brain"
    resolved against whatever directory uvicorn was launched from. A stranger who
    packaged the app and launched it elsewhere silently got a fresh empty DB and
    thought their data was lost. Anchoring the default to a stable OS location keeps
    ONE brain regardless of the launch directory:

      • macOS   -> ``~/Library/Application Support/Arslan``
      • Windows -> ``%APPDATA%/Arslan`` (fallback ``~/AppData/Roaming/Arslan``)
      • Linux/* -> ``${XDG_DATA_HOME:-~/.local/share}/Arslan``

    Pure/side-effect-free: it only *computes* the path (no mkdir); the directory is
    created at boot in ``server.main`` like before.
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "Arslan"


def _resolve_data_dir() -> Path:
    """Resolve the root data dir from the environment — the SINGLE resolver.

    UNSET ``ARSLAN_DATA_DIR`` -> the stable per-platform app-data dir. SET (incl. the
    dev flow's ``"data"``) -> honored verbatim, only expanded (``~``/``$VAR``) and
    resolved to an absolute path. Both ``load_settings`` (the boot-time singleton) and
    the live :func:`data_dir` accessor call this, so there is never a divergent
    CWD-relative ``"data"`` default that could split the brain from the subsystems'
    files (skill_scripts / artifacts / sandbox_env / shell workspace).
    """
    raw = os.environ.get("ARSLAN_DATA_DIR")
    d = Path(raw) if raw else _default_data_dir()
    return Path(os.path.expandvars(os.path.expanduser(str(d)))).resolve()


def data_dir() -> Path:
    """Live-resolved root data dir for subsystems (skill_scripts, artifacts, …).

    Reads the environment at call time via the SAME resolver as the boot-time
    ``settings.data_dir`` (see :func:`_resolve_data_dir`). Subsystems call this instead
    of re-reading ``os.environ.get("ARSLAN_DATA_DIR", "data")`` so every one of them
    shares ONE root. In a real deployment (env fixed at boot) it is identical to
    ``settings.data_dir``; the live read keeps reload-free test env mutation valid.
    """
    return _resolve_data_dir()


@dataclass(frozen=True)
class Settings:
    """Immutable server settings read once from the environment."""

    api_token: str
    secret_key: str
    db_path: str
    spawns_dir: Path
    # Root data directory (ARSLAN_DATA_DIR). Holds the SQLite db, spawns, and the
    # bootstrapped access-token file (see server.token_bootstrap). Kept explicit so
    # the token bootstrap doesn't have to re-derive it from db_path.
    data_dir: Path = Path("data")
    static_dir: str = ""
    app_version: str = "0.1.0"
    attach_extract_char_limit: int = 12000
    # Deployment mode. Code default is "dev" so local zero-config still boots.
    # Release artifacts (Dockerfile / docker-compose) pin ARSLAN_ENV=prod, which
    # turns missing-secret from a warning into a boot-fatal refusal.
    env: str = "dev"
    # Advisory default bind host. The *true* bind is decided by the launcher's
    # `uvicorn --host`; this value only feeds launch scripts/docs and the
    # startup bind advisory — the app cannot force it.
    bind_host: str = "127.0.0.1"
    # Host/Origin trust policy (S1 OSS safety). `allowed_hosts` feeds Starlette's
    # TrustedHostMiddleware (rejects foreign `Host:` headers → DNS-rebinding);
    # `allowed_origins` feeds CORSMiddleware + the WS Origin check. Dev defaults are
    # localhost-only (+ test-harness hosts / the vite :5173 dev origin); prod reads
    # ARSLAN_ALLOWED_HOSTS / ARSLAN_ALLOWED_ORIGINS. See load_settings + server.security.
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")
    allowed_origins: tuple[str, ...] = ()

    @property
    def is_prod(self) -> bool:
        """True when running in production mode (ARSLAN_ENV=prod)."""
        return self.env == "prod"

    @property
    def db_url(self) -> str:
        """Async SQLAlchemy URL for the SQLite database."""
        return f"sqlite+aiosqlite:///{self.db_path}"


def load_settings() -> Settings:
    """Build a Settings instance from current environment variables."""
    # Root data dir. UNSET -> stable per-platform app-data dir (so a stranger keeps
    # ONE brain regardless of the launch directory). SET (incl. the dev flow's
    # "data") -> honored verbatim; only expanded (~/$VAR) and resolved to an
    # absolute path for stable file I/O + a meaningful boot log — never relocated.
    # Shares one resolver with the live ``data_dir()`` accessor the subsystems use.
    data_dir = _resolve_data_dir()
    db_path = os.environ.get("ARSLAN_DB_PATH", str(data_dir / "arslan.db"))
    spawns_dir = Path(os.environ.get("ARSLAN_SPAWNS_DIR", str(data_dir / "spawns")))
    static_dir = os.environ.get("ARSLAN_STATIC_DIR", str(Path(__file__).parent / "static"))
    env = os.environ.get("ARSLAN_ENV", "dev").lower()
    is_prod = env == "prod"

    # Trusted Host headers (Starlette matches on hostname only; ':port' forms are
    # normalised away in server.security). Prod reads ARSLAN_ALLOWED_HOSTS
    # (comma-separated) and otherwise fails closed to localhost-only — a packaged
    # localhost service keeps working while a foreign Host (DNS-rebinding) is
    # rejected. Dev/tests add the harness hosts: the Starlette TestClient uses
    # 'testserver'; the httpx ASGI suites use 'test' / 't'. None of these are
    # publicly registrable, so they add no DNS-rebinding surface.
    hosts_raw = os.environ.get("ARSLAN_ALLOWED_HOSTS", "").strip()
    if hosts_raw:
        allowed_hosts: tuple[str, ...] = tuple(h.strip() for h in hosts_raw.split(",") if h.strip())
    elif is_prod:
        allowed_hosts = ("localhost", "127.0.0.1")
    else:
        allowed_hosts = ("localhost", "127.0.0.1", "testserver", "test", "t")

    # Cross-origin allowlist for CORS + the WS Origin check. Prod reads
    # ARSLAN_ALLOWED_ORIGINS (comma-separated) and otherwise allows none (only
    # genuine same-origin gets through). Dev allows the vite dev server.
    origins_raw = os.environ.get("ARSLAN_ALLOWED_ORIGINS", "").strip()
    if origins_raw:
        allowed_origins: tuple[str, ...] = tuple(o.strip() for o in origins_raw.split(",") if o.strip())
    elif is_prod:
        allowed_origins = ()
    else:
        allowed_origins = ("http://localhost:5173", "http://127.0.0.1:5173")

    return Settings(
        api_token=os.environ.get("ARSLAN_API_TOKEN", ""),
        secret_key=os.environ.get("ARSLAN_SECRET_KEY", ""),
        db_path=db_path,
        spawns_dir=spawns_dir,
        data_dir=data_dir,
        static_dir=static_dir,
        attach_extract_char_limit=int(os.environ.get("ARSLAN_ATTACH_CHAR_LIMIT", "12000")),
        env=env,
        bind_host=os.environ.get("ARSLAN_BIND_HOST", "127.0.0.1"),
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


# Module-level singleton used by the app and dependencies.
settings = load_settings()

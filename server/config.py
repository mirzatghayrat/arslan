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
    data_dir = Path(os.environ.get("ARSLAN_DATA_DIR", "data"))
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
        static_dir=static_dir,
        attach_extract_char_limit=int(os.environ.get("ARSLAN_ATTACH_CHAR_LIMIT", "12000")),
        env=env,
        bind_host=os.environ.get("ARSLAN_BIND_HOST", "127.0.0.1"),
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


# Module-level singleton used by the app and dependencies.
settings = load_settings()

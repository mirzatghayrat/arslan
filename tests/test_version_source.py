"""C5b: the app has one version, desktop/src-tauri/tauri.conf.json. The backend, its OpenAPI page and
its health endpoint all say that one; the 0.1.0 / 0.0.0 in the packaging files is not it."""
import json
from pathlib import Path

from server import config

ROOT = Path(__file__).resolve().parent.parent


def _conf_version() -> str:
    return json.loads((ROOT / "desktop/src-tauri/tauri.conf.json").read_text())["version"]


def test_a_source_checkout_reports_the_desktop_version_with_dev(monkeypatch):
    monkeypatch.delenv("ARSLAN_APP_VERSION", raising=False)
    assert config._app_version() == _conf_version() + "-dev"


def test_the_packaged_app_reports_the_bundle_version(monkeypatch):
    monkeypatch.setenv("ARSLAN_APP_VERSION", "9.9.9")
    assert config._app_version() == "9.9.9"


async def test_openapi_and_health_say_the_same_version():
    from server.api.health import health
    from server.main import create_app
    app = create_app()
    assert app.version == config.settings.app_version
    assert app.openapi()["info"]["version"] == (await health())["version"]

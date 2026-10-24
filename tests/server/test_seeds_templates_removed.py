"""C7 (v0.1.63): the persona-seed browse API and the spawn-template listing are gone.

GET /seeds and GET /templates had no component caller (the web's api.getSeeds and
api.listTemplates were unused), and arslan/templates (library, matcher, official data) had no
other user. persona_seed_service.get_by_slugs stays: spawn detail resolves a spawn's composed
seeds with it (GET /spawns/{id} and the equipment reply), which C7 step 3 keeps until v0.1.64.
"""
import importlib.util
from pathlib import Path

from server.services import persona_seed_service

ROOT = Path(__file__).resolve().parents[2]
AUTH: dict[str, str] = {}


def _gone(module: str) -> bool:
    """A clean checkout has no such module. A local checkout may keep an untracked
    __pycache__/ after a pull, which Python reads as an empty namespace package: that is
    gone too, as long as no source file is left in it."""
    spec = importlib.util.find_spec(module)
    if spec is None:
        return True
    return spec.origin is None and not any(
        any(Path(loc).rglob("*.py")) for loc in (spec.submodule_search_locations or []))


def test_the_modules_and_functions_are_gone():
    for module in ("server.api.seeds", "server.api.templates", "arslan.templates"):
        assert _gone(module), module
    for name in ("search", "count", "list_seeds"):
        assert not hasattr(persona_seed_service, name), name
    assert hasattr(persona_seed_service, "get_by_slugs")


def test_the_packaged_self_test_no_longer_expects_the_official_templates():
    entry = (ROOT / "packaging" / "server_entry.py").read_text(encoding="utf-8")
    assert "arslan/templates" not in entry


async def test_the_routes_are_gone_and_spawn_detail_stays(client):
    # Positive control: the deferred live endpoint still answers.
    assert (await client.get("/api/v1/spawns", headers=AUTH)).status_code == 200
    for path in ("/api/v1/seeds", "/api/v1/templates"):
        assert (await client.get(path, headers=AUTH)).status_code == 404, path

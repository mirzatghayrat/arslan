"""C7 step 2 (v0.1.63): arslan/spawn, the evolution engine and the jinja2 dependency are gone.

C9 moved the live part of arslan/spawn (the SKILL.md format and the bundled skills) to
arslan/skills; the expert-create chain, the package's last importer, went in the PR before
this one. jinja2 was used only by arslan/spawn/manager.py.
"""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _gone(module: str) -> bool:
    """A clean checkout has no such module. A local checkout may keep an untracked
    __pycache__/ after a pull, which Python reads as an empty namespace package: that is
    gone too, as long as no source file is left in it."""
    spec = importlib.util.find_spec(module)
    if spec is None:
        return True
    return spec.origin is None and not any(
        any(Path(loc).rglob("*.py")) for loc in (spec.submodule_search_locations or []))


def test_the_package_and_the_engine_are_gone():
    for module in ("arslan.spawn", "arslan.core.evolution"):
        assert _gone(module), module


def test_jinja2_left_the_dependencies_and_the_lock():
    """Nothing else needs it transitively, so the lock drops it, and markupsafe, which only
    jinja2 pulled in."""
    assert "jinja2" not in (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    lock_names = set(re.findall(r'^name = "([^"]+)"', (ROOT / "uv.lock").read_text(encoding="utf-8"), re.M))
    assert "jinja2" not in lock_names and "markupsafe" not in lock_names


def test_no_server_or_arslan_source_names_jinja2():
    """Importing the app only proves no TOP-LEVEL import of jinja2 is left; one inside a
    function would pass that and fail at the first call. So read the sources."""
    word = re.compile(r"\bjinja2\b")
    hits = [str(path.relative_to(ROOT))
            for top in ("server", "arslan") for path in (ROOT / top).rglob("*.py")
            if word.search(path.read_text(encoding="utf-8"))]
    assert not hits, hits


def test_the_packaged_self_test_no_longer_expects_the_scaffold():
    """The packaged build's self-test checked arslan/spawn/scaffold was bundled; a self-test
    still naming it would fail every packaged build now that the directory is gone."""
    entry = (ROOT / "packaging" / "server_entry.py").read_text(encoding="utf-8")
    assert "arslan/spawn" not in entry and '"arslan.spawn"' not in entry

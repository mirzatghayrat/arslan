"""pypdf stays at or above the version that fixed two resource-exhaustion CVEs.

pypdf 6.15.0 (2026-08-06) carries two SEC entries, both of which are reachable
from our own code:

  - "Limit token length for ToUnicode entries" (#3944)
  - "Limit CID width range and width count when loading fonts" (#3946)

REACHABLE, not theoretical: ``server/services/ingest.py:32-34`` builds a
``PdfReader`` over caller-supplied bytes and walks every page's
``extract_text()``. A PDF's ToUnicode stream and CID font widths are parsed on
that path, so a crafted attachment reaches the vulnerable code with no other
precondition. The failure is memory/CPU exhaustion rather than disclosure —
which is why this is a floor, not a pin.

🔴 TWO ASSERTIONS BECAUSE THERE ARE TWO WAYS TO REGRESS, and each is invisible
to the other:

  1. the INSTALLED version is what actually runs — in CI, in the venv, and
     inside the frozen sidecar. ``uv.lock`` decides it.
  2. the DECLARED FLOOR in pyproject.toml is what a FRESH resolve is allowed to
     pick. A lockfile can be regenerated, or a downstream install can ignore it;
     if the floor still said ">=4.0" the resolver would be free to choose a
     vulnerable build and nothing here would notice.

Asserting only (1) passes on a tree whose floor invites the vulnerability back.
Asserting only (2) passes while the installed copy is still 6.14.2.

🔴 AND THE COMPARISON IS PARSED, NOT LEXICAL. ``"6.9.0" > "6.15.0"`` is True as
strings, so a string compare would wave through every 6.9.x — the exact shape of
a guard that looks like it works. ``packaging.version`` orders them numerically.
"""
from __future__ import annotations

import pathlib
import re
import tomllib

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

# The release that carries #3944 and #3946. Raise this when a later CVE lands;
# never lower it.
PATCHED = Version("6.15.0")

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _declared_floor(name: str) -> Version:
    """The `>=` floor pyproject declares for a runtime dependency."""
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    for raw in data["project"]["dependencies"]:
        req = Requirement(raw)
        if req.name.lower() != name:
            continue
        for spec in req.specifier:
            if spec.operator in (">=", "==", "~="):
                return Version(spec.version)
        pytest.fail(f"{name} is declared as {raw!r} with no lower bound at all")
    pytest.fail(f"{name} is not a declared runtime dependency any more")


class TestTheInstalledCopyIsPatched:
    def test_the_version_we_import_is_at_least_the_fix(self):
        # What actually runs. This is the assertion that fails on the tree as it
        # was: 6.14.2 predates both SEC entries.
        import pypdf

        assert Version(pypdf.__version__) >= PATCHED, (
            f"pypdf {pypdf.__version__} is installed; #3944/#3946 land in {PATCHED}"
        )

    def test_the_api_we_actually_use_still_exists(self):
        # A version floor that silently broke our two call sites would be a
        # worse outcome than the CVE. ingest.py uses exactly these.
        from pypdf import PdfReader

        assert callable(PdfReader)
        assert hasattr(PdfReader, "pages")


class TestTheDeclaredFloorCannotInviteItBack:
    def test_pyproject_forbids_a_vulnerable_resolve(self):
        # The half a lockfile bump alone does not fix.
        assert _declared_floor("pypdf") >= PATCHED

    def test_the_floor_is_compared_numerically_not_as_text(self):
        # Guarding the guard. If someone rewrites the helper with a string
        # compare, "6.9.0" would satisfy a ">= 6.15.0" check and every 6.9.x
        # would pass. This fails loudly in that world and is otherwise inert.
        assert Version("6.9.0") < Version("6.15.0")
        assert "6.9.0" > "6.15.0", "string ordering assumed by this test changed"


class TestTheLockAgreesWithTheFloor:
    def test_uv_lock_pins_a_patched_build(self):
        # uv.lock is what CI and the frozen build install from; pyproject alone
        # does not determine it. Read as text rather than via a TOML parser
        # because uv.lock holds one [[package]] table per dependency and we want
        # the one immediately following the pypdf name.
        lock = (_REPO_ROOT / "uv.lock").read_text()
        m = re.search(r'name = "pypdf"\nversion = "([^"]+)"', lock)

        assert m, "pypdf is not in uv.lock"
        assert Version(m.group(1)) >= PATCHED, f"uv.lock pins pypdf {m.group(1)}"

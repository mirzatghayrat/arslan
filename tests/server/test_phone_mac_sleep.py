"""IPB (v0.1.64): `status.snapshot.mac.sleep.kept_awake` (docs/plans/0164/IPB-frame-list.md §1): whether Arslan
holds the Mac awake right now. The desktop shell holds the sleep assertion; the backend sees both inputs of
the shell's rule, so it computes the same one, and a test pins the two copies together."""
from pathlib import Path

import pytest

from server.db.models import Setting
from server.services import desktop_status


@pytest.fixture(autouse=True)
def _clean():
    desktop_status._reset_for_tests()
    yield
    desktop_status._reset_for_tests()


@pytest.mark.parametrize("setting, working, kept", [
    (None, 0, False), (None, 1, True), (None, 2, True),            # on by default, held only while work runs
    ("false", 1, False), ("false", 0, False), ("true", 1, True),
])
async def test_kept_awake_is_the_shells_rule(client, setting, working, kept):
    if setting is not None:
        async with client.db_maker() as db:
            db.add(Setting(key="keep_awake_enabled", value=setting))
            await db.commit()
    from contextlib import ExitStack
    with ExitStack() as stack:
        for k in range(working):
            stack.enter_context(desktop_status.working(f"c{k}", title="t", kind="turn"))
        got = (await client.get("/api/v1/phone/status")).json()
    assert got["mac"] == {"sleep": {"kept_awake": kept}}, "the Bridge adds the rest of `mac`"


def test_the_rule_is_the_desktop_shells():
    source = (Path(__file__).resolve().parents[2] / "desktop/src-tauri/src/resident.rs").read_text()
    assert "status.keep_awake && status.working > 0" in source, "change both copies together"

"""Shared pytest fixtures for the Arslan test suite."""
import os

# Keep the dev secret auto-generation (server.secret_bootstrap) DISABLED suite-wide:
# set-but-empty ARSLAN_SECRET_KEY_FILE means "never read/write any secret file".
# Without this, any test that reloads server.config with ARSLAN_SECRET_KEY unset would
# mint a real key file in the developer's ~/.arslan. Must execute before any server.*
# import (the frozen settings singleton builds at first import); this root conftest
# loads before every test module and sub-conftest. Tests that exercise the feature
# opt back in by pointing ARSLAN_SECRET_KEY_FILE at a tmp path.
os.environ["ARSLAN_SECRET_KEY_FILE"] = ""

# 0.1.61 PR 4: no app lifespan in the suite starts the MCP supervisor (it would start every MCP
# server in the test's database). Supervisor tests drive their own Supervisor instances.
os.environ["ARSLAN_MCP_SUPERVISOR"] = "0"

import shutil

import pytest

from arslan.models import (
    DomainInfo,
    PersonaSpec,
    RuntimeSpec,
    SpawnRequirements,
    ToolSpec,
)
from tests import real_data_dir_guard

# No test may write into the user's real data dir (tests/real_data_dir_guard.py).
# Pinned here for the same reason as the secret file above: before any server.*
# import builds the settings singleton. The snapshot is taken now too, so writes
# made while test modules are collected are caught as well.
_SUITE_DATA_DIR = real_data_dir_guard.pin_suite_data_dir()
_REAL_DATA_DIR_AT_START = real_data_dir_guard.snapshot()


@pytest.fixture
def sample_domain() -> DomainInfo:
    return DomainInfo(category="content-creator", subcategory="xiaohongshu")


@pytest.fixture
def sample_persona() -> PersonaSpec:
    return PersonaSpec(
        role="资深美妆博主",
        tone="数据实测型",
        constraints=["不推荐未经验证的产品"],
    )


@pytest.fixture
def sample_tool() -> ToolSpec:
    return ToolSpec(
        name="web_search",
        description="Search the web for information",
        tags=["search", "web"],
        input_schema={"query": {"type": "string"}},
        output_schema={"results": {"type": "array"}},
    )


@pytest.fixture
def sample_requirements(sample_domain, sample_persona) -> SpawnRequirements:
    return SpawnRequirements(
        spawn_name="美妆助手",
        domain=sample_domain,
        capabilities=["content-generation", "info-gathering"],
        persona=sample_persona,
        runtime=RuntimeSpec(platform="web", trigger="user"),
        research_results={"trends": ["skincare", "makeup"]},
    )


@pytest.fixture(autouse=True)
def _default_workspace_in_tmp(tmp_path_factory):
    """0.1.48: Arslan's default folder is ~/Arslan; no test may create or write it.

    Its own MonkeyPatch, not the shared `monkeypatch` fixture: requesting that here
    (a root-level autouse fixture) would set it up before tests/server/conftest's
    `_restore_config_after_test` and so tear it down after it — and that teardown
    relies on running after monkeypatch has restored the test's patches."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("ARSLAN_DEFAULT_WORKSPACE", str(tmp_path_factory.mktemp("arslan-home") / "Arslan"))
        yield


@pytest.fixture(autouse=True)
def _no_judge_model_calls():
    """0.1.52: shadow judgments fire at every confirmation card. In tests the judge
    model is never reached (no network, no spend); a test of the judgment layer
    patches `_adapter` itself. Its own MonkeyPatch, for the reason given above."""
    from server.services import judgment

    async def disabled():
        raise RuntimeError("judge model disabled in tests")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(judgment, "_adapter", disabled)
        yield


@pytest.fixture(autouse=True)
def _no_real_mcp_spawn_or_download(request):
    """0.1.61 PR 4: a unit test never spawns an MCP server or downloads a runtime for real.

    The guard sits on the spawn itself (`mcp.client.stdio._create_platform_compatible_process`,
    which every stdio MCP client path reaches: the session manager, agent_browser,
    managed_browser) and on `capability_runtime._download`, so tests that fake `stdio_client` or
    `_download` keep working. A real-process test is marked `@pytest.mark.real_mcp`: the marker
    lifts this guard and nothing else — those tests run on CI and on the Mac like any other.

    Here at the root so no test directory is left out, and with its own MonkeyPatch, for the
    reason given above: a test's own `monkeypatch.undo()` (seven tests in tests/server call it)
    would otherwise put the real functions back."""
    if request.node.get_closest_marker("real_mcp") is not None:
        yield
        return
    import mcp.client.stdio as stdio_mod

    from server.services import capability_runtime

    async def refuse_spawn(*args, **kwargs):
        raise RuntimeError("real MCP spawn in a unit test: fake the session, or mark the test real_mcp")

    async def refuse_download(*args, **kwargs):
        raise RuntimeError("real runtime download in a unit test: fake capability_runtime._download")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(stdio_mod, "_create_platform_compatible_process", refuse_spawn)
        mp.setattr(capability_runtime, "_download", refuse_download)
        yield


@pytest.fixture(autouse=True)
def _data_dir_pin_survives():
    """Repair, then fail, a test that changed the pinned data-dir env and kept it.

    Server tests are repaired earlier, before config is healed, by
    tests/server/conftest.py's `_restore_config_after_test`; this covers the rest."""
    yield
    changed = real_data_dir_guard.restore_pin()
    if changed:
        pytest.fail(f"this test changed {changed} in os.environ and did not restore it "
                    "(repaired now); later tests would resolve the real data dir",
                    pytrace=False)


@pytest.fixture(autouse=True)
def _session_global_restored():
    """Repair, then fail, a test that replaced `db_session.AsyncSessionLocal` and kept it.

    Every later test then gets that test's engine. An in-memory one (StaticPool) shares a
    single connection, and fire-and-forget writes cancelled at teardown closed it twice and
    hung pytest for 120 s (2026-10-04, six fixtures). Use monkeypatch.setattr and dispose
    the engine."""
    from server.db import session as db_session
    before = db_session.AsyncSessionLocal
    yield
    if db_session.AsyncSessionLocal is not before:
        db_session.AsyncSessionLocal = before
        pytest.fail("this test replaced db_session.AsyncSessionLocal and did not restore it "
                    "(repaired now); use monkeypatch.setattr and dispose the engine", pytrace=False)


@pytest.fixture(scope="session", autouse=True)
def _real_data_dir_untouched():
    """Fail the run if the user's real data dir gained an entry while it ran.

    Reports and never deletes: what is there is the user's, and a false positive (the
    running app creating a new top-level folder mid-run) must not cost them data."""
    yield
    shutil.rmtree(_SUITE_DATA_DIR, ignore_errors=True)
    leaked = real_data_dir_guard.created(_REAL_DATA_DIR_AT_START, real_data_dir_guard.snapshot())
    if leaked:
        root = real_data_dir_guard.REAL_DATA_DIR
        pytest.fail(
            f"this test run created {len(leaked)} entr{'y' if len(leaked) == 1 else 'ies'} "
            f"in the real Arslan data dir {root}:\n"
            + "\n".join(f"  {root / rel}" for rel in leaked)
            + "\nA test resolved the platform data dir instead of a temp one. Run with "
            "HOME pointed at a temp dir to reproduce safely. Nothing was removed.",
            pytrace=False,
        )

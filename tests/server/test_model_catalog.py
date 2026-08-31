"""Provider-P2: dynamic model catalog — fetchers, cache TTL logic, /models API.

Fetchers are exercised through httpx.MockTransport (the repo idiom, see
tests/llm/test_gemini_provider.py). Cache-layer tests monkeypatch
model_catalog.fetch_models so no network shape leaks into TTL logic tests.
DB tests follow the in-memory engine idiom from tests/server/test_llm_factory.py.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base, ModelCatalogCache
from server.services import model_catalog, provider_config_service


# ---------------------------------------------------------------------------
# fetch_models — openai-compat family
# ---------------------------------------------------------------------------


async def test_openai_compat_parses_ids_and_sends_bearer():
    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("authorization")
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"data": [{"id": "m-1"}, {"id": "m-2"}]})

    models = await model_catalog.fetch_models(
        "deepseek", "https://api.deepseek.com", "sk-x",
        transport=httpx.MockTransport(handler))
    assert [m["id"] for m in models] == ["m-1", "m-2"]
    assert captured["auth"] == "Bearer sk-x"
    assert captured["url"] == "https://api.deepseek.com/models"
    assert all(m["source"] == "api" for m in models)
    assert all(m["capabilities"] == [] for m in models)  # no capability info exposed


async def test_openai_compat_omits_bearer_when_key_empty():
    captured = {}

    def handler(request):
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"data": [{"id": "local-model"}]})

    models = await model_catalog.fetch_models(
        "custom", "http://192.168.1.5:8080/v1", "",
        transport=httpx.MockTransport(handler))
    assert [m["id"] for m in models] == ["local-model"]
    assert "authorization" not in captured["headers"]


async def test_openai_com_filters_non_chat_models():
    ids = ["gpt-5.6-terra", "text-embedding-3-small", "tts-1", "whisper-1",
           "dall-e-3", "omni-moderation-latest", "gpt-audio", "gpt-realtime",
           "gpt-image-1", "gpt-4o-transcribe"]

    def handler(request):
        return httpx.Response(200, json={"data": [{"id": i} for i in ids]})

    models = await model_catalog.fetch_models(
        "openai", "https://api.openai.com/v1", "sk-x",
        transport=httpx.MockTransport(handler))
    assert [m["id"] for m in models] == ["gpt-5.6-terra"]


async def test_openrouter_rich_fields_map_presence_based():
    def handler(request):
        return httpx.Response(200, json={"data": [
            {"id": "anthropic/claude-sonnet-5", "context_length": 200000,
             "supported_parameters": ["tools", "temperature"]},
            {"id": "bare/model"},
        ]})

    models = await model_catalog.fetch_models(
        "openrouter", "https://openrouter.ai/api/v1", "sk-or",
        transport=httpx.MockTransport(handler))
    rich, bare = models
    assert rich["context_window"] == 200000
    assert "tools" in rich["capabilities"]
    assert bare["context_window"] is None
    assert bare["capabilities"] == []


# ---------------------------------------------------------------------------
# fetch_models — anthropic
# ---------------------------------------------------------------------------


async def test_anthropic_fetcher_headers_and_display_name():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["x-api-key"] = request.headers.get("x-api-key")
        captured["anthropic-version"] = request.headers.get("anthropic-version")
        return httpx.Response(200, json={"data": [
            {"id": "claude-sonnet-5", "display_name": "Claude Sonnet 5"},
        ]})

    models = await model_catalog.fetch_models(
        "anthropic", "", "sk-ant", transport=httpx.MockTransport(handler))
    assert captured["url"].startswith("https://api.anthropic.com/v1/models")
    assert captured["x-api-key"] == "sk-ant"
    assert captured["anthropic-version"] == "2023-06-01"
    (m,) = models
    assert m["id"] == "claude-sonnet-5"
    assert m["display_name"] == "Claude Sonnet 5"
    assert set(m["capabilities"]) == {"tools", "vision"}


async def test_anthropic_fetcher_honors_base_url_override():
    """Review FIX 1: a proxied native config (base_url set on the row) must send
    its key to the PROXY host, exactly like the chat path (AnthropicProvider uses
    ``base_url or DEFAULT_BASE_URL``) — never to the official host."""
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"data": [{"id": "claude-sonnet-5"}]})

    await model_catalog.fetch_models(
        "anthropic", "https://proxy.example/anthropic/v1", "sk-ant",
        transport=httpx.MockTransport(handler))
    assert captured["url"].startswith("https://proxy.example/anthropic/v1/models")


# ---------------------------------------------------------------------------
# fetch_models — gemini
# ---------------------------------------------------------------------------


async def test_gemini_fetcher_honors_base_url_override():
    """Review FIX 1: same as anthropic — catalog fetch and chat must hit the SAME
    host for the same config (GeminiProvider: ``base_url or DEFAULT_BASE_URL``)."""
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"models": []})

    await model_catalog.fetch_models(
        "gemini", "https://proxy.example/gemini/v1beta", "g-key",
        transport=httpx.MockTransport(handler))
    assert captured["url"].startswith("https://proxy.example/gemini/v1beta/models")


async def test_gemini_pagination_filter_and_prefix_strip():
    seen_tokens = []

    def handler(request):
        token = request.url.params.get("pageToken")
        seen_tokens.append(token)
        if token is None:
            return httpx.Response(200, json={
                "models": [
                    {"name": "models/gemini-3.5-flash",
                     "supportedGenerationMethods": ["generateContent"],
                     "inputTokenLimit": 1048576,
                     "thinking": True},
                    {"name": "models/embedding-001",
                     "supportedGenerationMethods": ["embedContent"]},
                ],
                "nextPageToken": "tok-2",
            })
        return httpx.Response(200, json={
            "models": [
                {"name": "models/gemini-2.5-pro",
                 "supportedGenerationMethods": ["generateContent"],
                 "inputTokenLimit": 2097152},
            ],
        })

    models = await model_catalog.fetch_models(
        "gemini", "", "g-key", transport=httpx.MockTransport(handler))
    assert seen_tokens == [None, "tok-2"]  # followed pagination
    assert [m["id"] for m in models] == ["gemini-3.5-flash", "gemini-2.5-pro"]
    flash, pro = models
    assert flash["context_window"] == 1048576
    assert "reasoning" in flash["capabilities"]
    assert "tools" in flash["capabilities"]
    assert pro["context_window"] == 2097152
    assert "reasoning" not in pro["capabilities"]


# ---------------------------------------------------------------------------
# fetch_models — ollama (native /api/tags + per-model /api/show)
# ---------------------------------------------------------------------------


async def test_ollama_tags_show_and_partial_show_failure():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        assert "/v1" not in request.url.path  # base_url /v1 suffix stripped
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [
                {"name": "llama3.1", "digest": "abc"},
                {"name": "broken", "digest": "def"},
            ]})
        assert request.url.path == "/api/show"
        body = json.loads(request.content)
        if body["model"] == "llama3.1":
            return httpx.Response(200, json={
                "capabilities": ["completion", "tools", "vision"],
                "model_info": {"llama.context_length": 131072},
            })
        return httpx.Response(500)  # one broken /api/show must not fail the batch

    models = await model_catalog.fetch_models(
        "ollama", "http://localhost:11434/v1", "",
        transport=httpx.MockTransport(handler))
    assert [m["id"] for m in models] == ["llama3.1", "broken"]
    good, bad = models
    assert set(good["capabilities"]) == {"tools", "vision"}
    assert good["context_window"] == 131072
    assert bad["capabilities"] == []
    assert bad["context_window"] is None
    assert paths.count("/api/tags") == 1
    assert paths.count("/api/show") == 2


async def test_ollama_blank_base_url_defaults_to_localhost():
    captured = {}

    def handler(request):
        captured["host"] = request.url.host
        captured["port"] = request.url.port
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(200, json={})

    models = await model_catalog.fetch_models(
        "ollama", "", "", transport=httpx.MockTransport(handler))
    assert models == []
    assert captured["host"] == "localhost"
    assert captured["port"] == 11434


# ---------------------------------------------------------------------------
# get_models — cache TTL / fingerprint / fallback logic
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_maker(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "unit-test")
    import server.config as config

    importlib.reload(config)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'mc.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield maker
    await engine.dispose()


async def _add_config(maker, *, provider="deepseek", model="deepseek-v4-flash",
                      base_url="", api_key="sk-x"):
    async with maker() as s:
        cfg = await provider_config_service.add_config(
            s, label="T", provider=provider, model=model,
            base_url=base_url, api_key=api_key)
    return cfg["id"]


def _fetcher_stub(monkeypatch, models=None, exc=None):
    calls = []

    async def _fake(provider, base_url, api_key, **kwargs):
        calls.append({"provider": provider, "base_url": base_url})
        if exc is not None:
            raise exc
        return models if models is not None else [
            {"id": "fetched-1", "display_name": None, "context_window": None,
             "capabilities": [], "source": "api"}]

    monkeypatch.setattr(model_catalog, "fetch_models", _fake)
    return calls


async def _seed_cache(maker, config_id, *, age_s, models, fingerprint):
    async with maker() as s:
        row = (await s.execute(select(ModelCatalogCache).where(
            ModelCatalogCache.provider_config_id == config_id))).scalar_one_or_none()
        if row is None:
            row = ModelCatalogCache(provider_config_id=config_id,
                                    fingerprint=fingerprint,
                                    fetched_at=datetime.utcnow() - timedelta(seconds=age_s),
                                    models=json.dumps(models))
            s.add(row)
        else:
            row.fingerprint = fingerprint
            row.fetched_at = datetime.utcnow() - timedelta(seconds=age_s)
            row.models = json.dumps(models)
        await s.commit()


def _fp_for(provider, stored_base_url, api_key):
    from arslan.llm.presets import expand_preset

    _, _, base_url = expand_preset(provider, "", stored_base_url)
    return model_catalog._fingerprint(provider, base_url, api_key)


_CACHED = [{"id": "cached-1", "display_name": None, "context_window": None,
            "capabilities": [], "source": "api"}]


async def test_fresh_cache_short_circuits_no_network(db_maker, monkeypatch):
    cid = await _add_config(db_maker)
    calls = _fetcher_stub(monkeypatch)
    await _seed_cache(db_maker, cid, age_s=60, models=_CACHED,
                      fingerprint=_fp_for("deepseek", "", "sk-x"))
    async with db_maker() as s:
        out = await model_catalog.get_models(s, cid)
    assert calls == []  # served from cache, fetcher never called
    assert [m["id"] for m in out["models"]] == ["cached-1"]
    assert out["stale"] is False
    assert out["error"] is None
    assert out["source"] == "api"


async def test_fingerprint_mismatch_forces_refetch(db_maker, monkeypatch):
    cid = await _add_config(db_maker)
    calls = _fetcher_stub(monkeypatch)
    await _seed_cache(db_maker, cid, age_s=60, models=_CACHED,
                      fingerprint="stale-fingerprint")
    async with db_maker() as s:
        out = await model_catalog.get_models(s, cid)
    assert len(calls) == 1
    assert [m["id"] for m in out["models"]] == ["fetched-1"]
    assert out["stale"] is False


async def test_fetch_failure_with_cache_serves_stale(db_maker, monkeypatch):
    cid = await _add_config(db_maker)
    _fetcher_stub(monkeypatch, exc=RuntimeError("boom"))
    # age > TTL_STALE_OK_S forces a fetch attempt; the failure falls back to cache
    await _seed_cache(db_maker, cid, age_s=model_catalog.TTL_STALE_OK_S + 60,
                      models=_CACHED, fingerprint=_fp_for("deepseek", "", "sk-x"))
    async with db_maker() as s:
        out = await model_catalog.get_models(s, cid)
    assert [m["id"] for m in out["models"]] == ["cached-1"]
    assert out["stale"] is True
    assert "boom" in out["error"]


async def test_fetch_failure_without_cache_serves_static_seed(db_maker, monkeypatch):
    from arslan.llm.catalog import models_for

    cid = await _add_config(db_maker)
    _fetcher_stub(monkeypatch, exc=RuntimeError("net down"))
    async with db_maker() as s:
        out = await model_catalog.get_models(s, cid)
    assert out["source"] == "static"
    assert out["stale"] is True
    assert "net down" in out["error"]
    assert out["fetched_at"] is None
    assert [m["id"] for m in out["models"]] == models_for("deepseek")
    assert all(m["source"] == "static" for m in out["models"])


async def test_refresh_true_forces_fetch_despite_fresh_cache(db_maker, monkeypatch):
    cid = await _add_config(db_maker)
    calls = _fetcher_stub(monkeypatch)
    await _seed_cache(db_maker, cid, age_s=10, models=_CACHED,
                      fingerprint=_fp_for("deepseek", "", "sk-x"))
    async with db_maker() as s:
        out = await model_catalog.get_models(s, cid, refresh=True)
    assert len(calls) == 1
    assert [m["id"] for m in out["models"]] == ["fetched-1"]


async def test_local_host_refetches_after_fresh_ttl_remote_does_not(db_maker, monkeypatch):
    age = model_catalog.TTL_FRESH_S + 300  # 10min: >5min fresh TTL, <24h stale TTL
    # local (ollama preset resolves to http://localhost:11434/v1) → eager refetch
    local_id = await _add_config(db_maker, provider="ollama", model="llama3.1",
                                 api_key="")
    calls = _fetcher_stub(monkeypatch)
    await _seed_cache(db_maker, local_id, age_s=age, models=_CACHED,
                      fingerprint=_fp_for("ollama", "", ""))
    async with db_maker() as s:
        out = await model_catalog.get_models(s, local_id)
    assert len(calls) == 1
    assert [m["id"] for m in out["models"]] == ["fetched-1"]

    # remote (deepseek) at the same age → serve cache, no refetch
    remote_id = await _add_config(db_maker)
    calls2 = _fetcher_stub(monkeypatch)
    await _seed_cache(db_maker, remote_id, age_s=age, models=_CACHED,
                      fingerprint=_fp_for("deepseek", "", "sk-x"))
    async with db_maker() as s:
        out2 = await model_catalog.get_models(s, remote_id)
    assert calls2 == []
    assert [m["id"] for m in out2["models"]] == ["cached-1"]


async def test_successful_fetch_upserts_cache(db_maker, monkeypatch):
    cid = await _add_config(db_maker)
    calls = _fetcher_stub(monkeypatch)
    async with db_maker() as s:
        out1 = await model_catalog.get_models(s, cid)  # no cache → fetch + upsert
    assert len(calls) == 1
    assert out1["fetched_at"] is not None
    async with db_maker() as s:
        out2 = await model_catalog.get_models(s, cid)  # now fresh → cache hit
    assert len(calls) == 1  # no second network call
    assert [m["id"] for m in out2["models"]] == ["fetched-1"]


async def test_get_models_unknown_config_raises_lookup_error(db_maker):
    async with db_maker() as s:
        with pytest.raises(LookupError):
            await model_catalog.get_models(s, 999999)


async def test_concurrent_uncached_calls_upsert_once_no_error(db_maker, monkeypatch):
    """Review FIX 2: two concurrent get_models on one UNCACHED config (React
    StrictMode double-mount) both pass the cache SELECT before either commits;
    the loser's INSERT used to raise IntegrityError on UNIQUE(provider_config_id)
    → uncaught 500. Both must succeed, leaving exactly one cache row."""
    cid = await _add_config(db_maker)
    release = asyncio.Event()
    in_flight = []

    async def _slow_fetch(provider, base_url, api_key, **kwargs):
        in_flight.append(1)
        await release.wait()  # hold BOTH callers past the cache SELECT
        return [{"id": "raced", "display_name": None, "context_window": None,
                 "capabilities": [], "source": "api"}]

    monkeypatch.setattr(model_catalog, "fetch_models", _slow_fetch)

    async def _call():
        async with db_maker() as s:
            return await model_catalog.get_models(s, cid)

    t1 = asyncio.create_task(_call())
    t2 = asyncio.create_task(_call())
    while len(in_flight) < 2:  # both sessions have SELECTed no-cache
        await asyncio.sleep(0.01)
    release.set()
    out1, out2 = await asyncio.gather(t1, t2)

    for out in (out1, out2):
        assert [m["id"] for m in out["models"]] == ["raced"]
        assert out["stale"] is False
    async with db_maker() as s:
        rows = (await s.execute(select(ModelCatalogCache).where(
            ModelCatalogCache.provider_config_id == cid))).scalars().all()
    assert len(rows) == 1


async def test_fetch_exceeding_total_budget_degrades_not_hangs(db_maker, monkeypatch):
    """Review FIX 3: httpx's timeout is PER-REQUEST (gemini worst case 10 pages,
    ollama N sequential /api/show) — get_models must cap the whole fetch with a
    wall-clock budget and land in the normal failure branch (static seed here)."""
    cid = await _add_config(db_maker)
    monkeypatch.setattr(model_catalog, "TOTAL_BUDGET_S", 0.05)

    async def _hang(provider, base_url, api_key, **kwargs):
        await asyncio.sleep(30)
        return []

    monkeypatch.setattr(model_catalog, "fetch_models", _hang)
    async with db_maker() as s:
        out = await asyncio.wait_for(model_catalog.get_models(s, cid), timeout=5)
    assert out["source"] == "static"
    assert out["stale"] is True
    assert out["error"]  # TimeoutError str() is empty — must still carry a name


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------


async def test_models_endpoint_404_for_unknown_config(client):
    r = await client.get("/api/v1/settings/provider-configs/999999/models")
    assert r.status_code == 404


async def test_models_endpoint_200_shape(client, monkeypatch):
    r = await client.post("/api/v1/settings/provider-configs", json={
        "label": "DS", "provider": "deepseek", "model": "deepseek-v4-flash",
        "base_url": "", "api_key": "sk-abc123456"})
    cid = r.json()["id"]

    async def _fake(provider, base_url, api_key, **kwargs):
        return [{"id": "m-x", "display_name": "Model X", "context_window": 64000,
                 "capabilities": ["tools"], "source": "api"}]

    monkeypatch.setattr(model_catalog, "fetch_models", _fake)
    r2 = await client.get(f"/api/v1/settings/provider-configs/{cid}/models")
    assert r2.status_code == 200
    body = r2.json()
    assert body["stale"] is False
    assert body["error"] is None
    assert body["source"] == "api"
    assert body["fetched_at"] is not None
    (m,) = body["models"]
    assert m == {"id": "m-x", "display_name": "Model X", "context_window": 64000,
                 "capabilities": ["tools"], "source": "api"}


async def test_models_endpoint_refresh_param_passthrough(client, monkeypatch):
    r = await client.post("/api/v1/settings/provider-configs", json={
        "label": "DS", "provider": "deepseek", "model": "deepseek-v4-flash",
        "base_url": "", "api_key": "sk-abc123456"})
    cid = r.json()["id"]

    seen_refresh = []
    real_get_models = model_catalog.get_models

    async def _spy(db, config_id, *, refresh=False):
        seen_refresh.append(refresh)
        return {"models": [], "fetched_at": None, "stale": True,
                "error": "n/a", "source": "static"}

    monkeypatch.setattr(model_catalog, "get_models", _spy)
    await client.get(f"/api/v1/settings/provider-configs/{cid}/models")
    await client.get(f"/api/v1/settings/provider-configs/{cid}/models?refresh=true")
    monkeypatch.setattr(model_catalog, "get_models", real_get_models)
    assert seen_refresh == [False, True]


# ---------------------------------------------------------------------------
# Structural: chat path must never import model_catalog (round iron rule)
# ---------------------------------------------------------------------------


def test_chat_path_never_imports_model_catalog():
    repo = Path(__file__).resolve().parents[2]
    # model_catalog is a Settings-only surface. The whole of server/ and arslan/
    # (the runtime chat path — ws, services, registry, mcp, orchestrator, …) is
    # scanned; only these two files may reference the module:
    #   • server/api/settings.py           — the /models endpoint (the model picker)
    #   • server/services/model_catalog.py — the module itself
    # provider_health.py used to be a third entry. It was deleted along with the
    # /models-based health probe: listing models answered the wrong question
    # (a public model list returns 200 with no key), so the connectivity verdict
    # now comes from the real chat test instead. model_catalog survives ONLY as
    # the model dropdown's data source.
    allowed = {
        repo / "server" / "api" / "settings.py",
        repo / "server" / "services" / "model_catalog.py",
    }
    # Match model_catalog as a whole word so incidental substrings — the
    # `model_catalog_cache` table (server/db/models.py) and the
    # `_0031_model_catalog` migration module (server/main.py) — are not
    # false positives; a real `import model_catalog` / `model_catalog.<x>`
    # reference always has word boundaries and is caught.
    ref = re.compile(r"\bmodel_catalog\b")
    offenders = []
    for tree in ("server", "arslan"):
        # Review FIX 4: rglob on a missing dir yields [] and the guard would pass
        # vacuously — a renamed tree must fail loudly, not silently disarm the rule.
        assert (repo / tree).is_dir(), f"chat-path tree missing: {tree}"
        for p in sorted((repo / tree).rglob("*.py")):
            if p in allowed:
                continue
            if ref.search(p.read_text(encoding="utf-8")):
                offenders.append(str(p.relative_to(repo)))
    assert not offenders, (
        f"model_catalog leaked into the chat/runtime path: {offenders} — it may "
        "only be referenced from server/api/settings.py, which serves the model "
        "picker (round iron rule)")


# ---------------------------------------------------------------------------
# Migration _0031
# ---------------------------------------------------------------------------

_OLD_PROVIDER_CONFIGS_DDL = (
    "CREATE TABLE provider_configs ("
    "id INTEGER PRIMARY KEY, label VARCHAR(80) NOT NULL, "
    "provider VARCHAR(40) NOT NULL, model VARCHAR(120) NOT NULL, "
    "base_url VARCHAR(255), api_key TEXT NOT NULL, "
    "is_primary BOOLEAN NOT NULL, created_at DATETIME)"
)


def test_migration_0031_adds_table_and_columns(tmp_path):
    from server.db.migrations.versions._0031_model_catalog import upgrade_sync

    engine = create_engine(f"sqlite:///{tmp_path/'m31.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql(_OLD_PROVIDER_CONFIGS_DDL)  # pre-0031 shape
        upgrade_sync(conn)
        upgrade_sync(conn)  # idempotent: second boot re-applies as a no-op
        tables = {r[0] for r in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "model_catalog_cache" in tables
        cache_cols = {r[1] for r in conn.exec_driver_sql(
            "PRAGMA table_info(model_catalog_cache)")}
        assert {"id", "provider_config_id", "fingerprint", "fetched_at",
                "models"} <= cache_cols
        pc_cols = {r[1] for r in conn.exec_driver_sql(
            "PRAGMA table_info(provider_configs)")}
        assert {"last_health", "last_health_at"} <= pc_cols
    engine.dispose()

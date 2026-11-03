"""MODEL1 (v0.1.64): Add model fetches the provider's live model list with the key just typed, before anything is
saved (card docs/plans/0164/MODEL1-add-model-key-first.md).

The key is used transiently: it goes only to that provider's own models endpoint, in a header, once per request;
nothing is written to the database (no provider config, no catalog cache, no setting); and it appears in no log line
or error. A failed fetch answers with the built-in list, marked source="static", and the reason.
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy import func, select

from arslan.llm import catalog
from server.db.models import Base
from server.services import model_catalog

KEY = "sk-ant-model1-typed-key-0123456789"
PREVIEW = "/api/v1/settings/provider-models/preview"


async def _row_counts(db_maker) -> dict[str, int]:
    async with db_maker() as s:
        return {t.name: (await s.execute(select(func.count()).select_from(t))).scalar_one()
                for t in Base.metadata.tables.values()}


async def test_the_typed_key_goes_once_to_the_providers_models_endpoint_in_a_header():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": "claude-sonnet-5-5", "display_name": "Claude Sonnet 5.5"}]})

    out = await model_catalog.preview_models("anthropic", "", KEY, transport=httpx.MockTransport(handler))
    (request,) = seen
    assert (request.url.host, request.url.path) == ("api.anthropic.com", "/v1/models")
    assert request.headers["x-api-key"] == KEY
    assert KEY not in str(request.url)
    assert out["source"] == "api" and out["error"] is None
    assert [m["id"] for m in out["models"]] == ["claude-sonnet-5-5"]


async def test_a_preset_previews_its_own_base_url():
    seen = []

    def handler(request: httpx.Request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"data": [{"id": "deepseek-v4-pro"}]})

    await model_catalog.preview_models("deepseek", "", KEY, transport=httpx.MockTransport(handler))
    assert seen == ["https://api.deepseek.com/models"]


async def test_the_endpoint_shows_the_live_list_and_stores_nothing(client, monkeypatch):
    calls = []

    async def _fetch(provider, base_url, api_key, **kwargs):
        calls.append((provider, base_url, api_key))
        return [{"id": "claude-opus-5-5", "display_name": None, "context_window": None,
                 "capabilities": [], "source": "api"}]

    monkeypatch.setattr(model_catalog, "fetch_models", _fetch)
    before = await _row_counts(client.db_maker)
    r = await client.post(PREVIEW, json={"provider": "anthropic", "base_url": "", "api_key": KEY})
    assert r.status_code == 200
    body = r.json()
    assert (body["source"], body["error"]) == ("api", None)
    assert [m["id"] for m in body["models"]] == ["claude-opus-5-5"]
    assert calls == [("anthropic", "", KEY)]
    assert await _row_counts(client.db_maker) == before


async def test_a_failed_fetch_shows_the_marked_built_in_list_with_no_key_anywhere(client, monkeypatch, caplog):
    async def _refuse(provider, base_url, api_key, **kwargs):
        request = httpx.Request("GET", "https://api.anthropic.com/v1/models")
        # A provider (or a proxy) that echoes the key back must not get it onto the screen or into a log.
        raise httpx.HTTPStatusError(f"401 invalid x-api-key {api_key}", request=request,
                                    response=httpx.Response(401, request=request, text=f"bad key {api_key}"))

    monkeypatch.setattr(model_catalog, "fetch_models", _refuse)
    caplog.set_level(logging.DEBUG)
    before = await _row_counts(client.db_maker)
    r = await client.post(PREVIEW, json={"provider": "anthropic", "base_url": "", "api_key": KEY})
    body = r.json()
    assert r.status_code == 200 and body["source"] == "static"
    assert [m["id"] for m in body["models"]] == catalog.models_for("anthropic")
    assert body["error"] and KEY not in body["error"]
    assert KEY not in caplog.text
    assert await _row_counts(client.db_maker) == before


async def test_an_empty_live_list_falls_back_too(client, monkeypatch):
    async def _empty(provider, base_url, api_key, **kwargs):
        return []

    monkeypatch.setattr(model_catalog, "fetch_models", _empty)
    body = (await client.post(PREVIEW, json={"provider": "openai", "base_url": "", "api_key": KEY})).json()
    assert body["source"] == "static" and body["error"]
    assert [m["id"] for m in body["models"]] == catalog.models_for("openai")


async def test_a_masked_key_is_never_sent(client, monkeypatch):
    async def _fetch(*a, **k):
        raise AssertionError("a masked key must not reach the provider")

    monkeypatch.setattr(model_catalog, "fetch_models", _fetch)
    r = await client.post(PREVIEW, json={"provider": "anthropic", "base_url": "", "api_key": "sk-...6789"})
    assert r.status_code == 422


async def test_the_key_is_not_in_the_request_path_or_query(client):
    """The key travels in the POST body only: a GET with it in the query string would land in access logs."""
    assert (await client.get(PREVIEW, params={"provider": "anthropic", "api_key": KEY})).status_code == 405


async def test_an_unrecognised_error_that_echoes_the_key_is_shown_without_it(client, monkeypatch):
    """No provider wording matches this one, so the raw text is what the form shows: the key must be out of it."""
    async def _boom(provider, base_url, api_key, **kwargs):
        raise RuntimeError(f"proxy said: unexpected credential {api_key} for this route")

    monkeypatch.setattr(model_catalog, "fetch_models", _boom)
    body = (await client.post(PREVIEW, json={"provider": "deepseek", "base_url": "", "api_key": KEY})).json()
    assert body["source"] == "static"
    assert KEY not in body["error"] and "[redacted]" in body["error"]

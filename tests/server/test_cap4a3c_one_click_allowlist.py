"""CAP4a-3c (v0.1.64, the user's list D, 2026-10-31): which MCP Registry entries get a one-click card.

Packages from any verified domain, or from a listed GitHub organization while its numeric id is still the listed
one; remote servers only from a listed vendor domain, on a host under it; everything else is added by hand. The
list is the user's, stored server side and edited through its own API. No network: GitHub's answer is a fake.
"""
import json

import httpx
import pytest

from server import auth
from server.services import capability_allowlist as al
from server.services import capability_flow, capability_search, permission_store

ALLOW = al.validate(al.DEFAULT)


def _cand(name, runtime="uv", url=None, source="registry", kind="mcp"):
    return {"id": f"registry:{name}@1.0.0", "kind": kind, "name": name.rsplit("/", 1)[-1], "summary": "",
            "source": source, "source_url": None, "repo": None, "version": "1.0.0", "runtime": runtime,
            "remote": {"type": "streamable-http", "url": url} if url else None, "not_here": None,
            "package": None if runtime == "remote" else {"registry_type": "pypi", "identifier": "x", "version": "1.0.0",
                                                         "arguments": []},
            "needs": {"keys": [], "network": None}, "license": {"spdx": "MIT", "read_from": "LICENSE", "verdict": "usable"}}


@pytest.mark.parametrize("cand, expected", [
    (_cand("com.example/notes"), None),                                            # any verified domain: a package
    (_cand("com.example/notes", runtime="node"), None),
    (_cand("com.example/notes", runtime="mcpb"), None),
    (_cand("io.github.someone/notes"), al.PUBLISHER_NOT_LISTED),                   # a GitHub account not listed
    (_cand("io.github.getsentry/sentry"), None),                                   # a listed organization (id later)
    (_cand("io.github.GetSentry/sentry"), None),                                   # logins match in any case
    (_cand("com.stripe/mcp", "remote", "https://mcp.stripe.com/mcp"), None),       # a vendor's remote on its host
    (_cand("com.stripe/mcp", "remote", "https://stripe.com/mcp"), None),
    (_cand("com.microsoft.azure/x", "remote", "https://mcp.azure.microsoft.com/"), None),   # a vendor's subdomain
    (_cand("com.microsoft/agent", "remote", "https://agent365.svc.cloud.microsoft/x"), None),  # a listed extra host
    (_cand("com.stripe/mcp", "remote", "https://stripe.com.evil.example/mcp"), al.REMOTE_HOST_NOT_THE_PUBLISHERS),
    (_cand("com.stripe/mcp", "remote", "https://evilstripe.com/mcp"), al.REMOTE_HOST_NOT_THE_PUBLISHERS),
    (_cand("com.stripe/mcp", "remote", "https://mcp.cloudflare.com/"), al.REMOTE_HOST_NOT_THE_PUBLISHERS),
    (_cand("com.stripe/mcp", "remote", "not a url"), al.REMOTE_HOST_NOT_THE_PUBLISHERS),
    (_cand("com.stripe/mcp", "remote", "https://mcp.stripe.com@evil.example/mcp"), al.REMOTE_HOST_NOT_THE_PUBLISHERS),
    (_cand("com.stripe/mcp", "remote", "https://mcp.stripe.com:443@evil.example/mcp"), al.REMOTE_HOST_NOT_THE_PUBLISHERS),
    (_cand("com.stripe/mcp", "remote", "https://evil.example#@mcp.stripe.com/"), al.REMOTE_HOST_NOT_THE_PUBLISHERS),
    (_cand("com.stripe/mcp", "remote", "https://evil.example\uff0f.stripe.com/"), al.REMOTE_HOST_NOT_THE_PUBLISHERS),
    (_cand("com.stripe/mcp", "remote", "https://[mcp.stripe.com/"), al.REMOTE_HOST_NOT_THE_PUBLISHERS),
    (_cand("com.stripe/mcp", "remote", "http://mcp.stripe.com/mcp"), al.REMOTE_NOT_HTTPS),
    (_cand("com.stripe/mcp", "remote", "ftp://mcp.stripe.com/mcp"), al.REMOTE_NOT_HTTPS),
    (_cand("com.stripe/mcp", "remote", "//mcp.stripe.com/mcp"), al.REMOTE_NOT_HTTPS),
    (_cand("com.stripe/mcp", "remote", "https://MCP.Stripe.COM./mcp"), None),             # case and a trailing dot
    (_cand("com.example/notes", "remote", "https://mcp.example.com/"), al.PUBLISHER_NOT_LISTED),  # remote: vendors only
    (_cand("io.github.github/mcp", "remote", "https://api.github.com/mcp"), al.REMOTE_FROM_AN_ACCOUNT),   # Q2
    (_cand("Bad Namespace/notes"), al.PUBLISHER_UNKNOWN),
    (_cand("acme/notes", source="github"), None),                                  # not a Registry entry: not held
    (_cand("io.github.someone/skill", kind="skill"), None),                        # skills are not held to the list
], ids=lambda v: v["id"] if isinstance(v, dict) else str(v))
def test_the_default_list_decides_one_click(cand, expected):
    assert al.verdict(cand, ALLOW) == expected


def test_with_packages_from_any_domain_off_only_vendors_are_one_click():
    narrow = {**ALLOW, "packages_from_any_domain": False}
    assert al.verdict(_cand("com.example/notes"), narrow) == al.PUBLISHER_NOT_LISTED
    assert al.verdict(_cand("com.evilstripe/notes"), narrow) == al.PUBLISHER_NOT_LISTED     # a lookalike
    assert al.verdict(_cand("com.stripe/notes"), narrow) is None
    assert al.verdict(_cand("com.microsoft.azure/notes"), narrow) is None


def test_the_default_list_is_valid_and_names_organizations_by_id():
    assert ALLOW["packages_from_any_domain"] is True
    assert ALLOW["accounts"]["github"] == 9919 and all(type(i) is int and i > 0 for i in ALLOW["accounts"].values())
    assert "stripe.com" in ALLOW["domains"] and ALLOW["hosts"] == {"microsoft.com": ["cloud.microsoft"]}


@pytest.mark.parametrize("bad, code", [
    ("not a dict", "not_a_list"),
    ({**al.DEFAULT, "packages_from_any_domain": "yes"}, "packages_from_any_domain"),
    ({**al.DEFAULT, "domains": ["Stripe.com"]}, "domains"),
    ({**al.DEFAULT, "domains": ["stripe.com/evil"]}, "domains"),
    ({**al.DEFAULT, "domains": ["localhost"]}, "domains"),
    ({**al.DEFAULT, "hosts": {"unlisted.example": ["x.example"]}}, "hosts"),
    ({**al.DEFAULT, "hosts": {"microsoft.com": ["*.microsoft"]}}, "hosts"),
    ({**al.DEFAULT, "accounts": {"github": "9919"}}, "accounts"),
    ({**al.DEFAULT, "accounts": {"github": -1}}, "accounts"),
    ({**al.DEFAULT, "accounts": {"github": True}}, "accounts"),
    ({**al.DEFAULT, "accounts": {"bad login!": 1}}, "accounts"),
])
def test_a_bad_list_is_refused_whole(bad, code):
    with pytest.raises(al.AllowlistError) as err:
        al.validate(bad)
    assert err.value.code == code


# ── the user's list, stored ──────────────────────────────────────────────────

@pytest.fixture
async def api(execution_db, monkeypatch):
    from fastapi import FastAPI
    from server.api.capabilities import router
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-allowlist-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 headers={"Authorization": "Bearer synthetic-allowlist-token"}) as client:
        yield client


async def test_the_list_is_read_saved_refused_and_reset_through_its_api(api):
    got = (await api.get("/api/v1/capability-allowlist")).json()
    assert got["list"] == ALLOW and got["default"] == ALLOW
    mine = {**ALLOW, "domains": ["example.com"], "hosts": {}, "packages_from_any_domain": False}
    assert (await api.put("/api/v1/capability-allowlist", json=mine)).json()["list"]["domains"] == ["example.com"]
    assert (await al.current())["domains"] == ["example.com"]
    assert al.verdict(_cand("com.stripe/notes"), await al.current()) == al.PUBLISHER_NOT_LISTED
    refused = await api.put("/api/v1/capability-allowlist", json={**mine, "domains": ["Not A Domain"]})
    assert refused.status_code == 422 and refused.json()["detail"] == {"code": "domains"}
    assert (await al.current())["domains"] == ["example.com"]                    # nothing half saved
    assert (await api.delete("/api/v1/capability-allowlist")).json()["list"] == ALLOW
    assert await al.current() == ALLOW


async def test_the_list_needs_the_users_token(api):
    r = await api.get("/api/v1/capability-allowlist", headers={"Authorization": "Bearer wrong"})
    assert r.status_code in (401, 403)


async def test_the_general_settings_write_cannot_change_the_list(execution_db):
    from server.services import settings_service
    async with execution_db() as db:
        await settings_service.update_settings(db, {al.SETTING_KEY: json.dumps(
            {**ALLOW, "domains": ["evil.example"], "hosts": {}})})          # a list that would validate
    assert await al.current() == ALLOW


async def test_an_unreadable_stored_list_is_closed_never_the_default(execution_db):
    """#584 review 1: the default can be wider than what the user saved."""
    from server.services import settings_service
    async with execution_db() as db:
        await settings_service._set_raw(db, al.SETTING_KEY, "{not json")
        await db.commit()
    assert await al.current() == al.CLOSED
    async with execution_db() as db:
        await settings_service._set_raw(db, al.SETTING_KEY, json.dumps({**ALLOW, "domains": ["Not Valid"]}))
        await db.commit()
    assert await al.current() == al.CLOSED
    assert al.verdict(_cand("com.example/notes"), al.CLOSED) == al.PUBLISHER_NOT_LISTED
    assert al.verdict(_cand("io.github.getsentry/sentry"), al.CLOSED) == al.PUBLISHER_NOT_LISTED


async def test_any_other_failed_read_is_closed(execution_db, monkeypatch):
    from server.services import settings_service

    async def fails(db, key):
        raise RuntimeError("the session could not be opened")
    monkeypatch.setattr(settings_service, "_get_raw", fails)
    assert await al.current() == al.CLOSED


@pytest.mark.parametrize("message, closed", [("database is locked", True), ("disk I/O error", True),
                                             ("no such table: settings", False)])
async def test_a_failed_read_is_closed_and_only_a_missing_table_is_the_default(execution_db, monkeypatch, message,
                                                                                closed):
    from sqlalchemy.exc import OperationalError
    from server.services import settings_service

    async def fails(db, key):
        raise OperationalError("SELECT", {}, Exception(message))
    monkeypatch.setattr(settings_service, "_get_raw", fails)
    assert await al.current() == (al.CLOSED if closed else ALLOW)


async def test_a_failed_read_gives_no_card_for_what_the_users_list_left_out(card_world, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from server.services import settings_service
    await al.save({**ALLOW, "packages_from_any_domain": False, "domains": ["stripe.com"], "hosts": {}})

    async def fails(db, key):
        raise OperationalError("SELECT", {}, Exception("database is locked"))
    monkeypatch.setattr(settings_service, "_get_raw", fails)
    out, cards = await _propose(monkeypatch, _cand("com.example/notes"))
    assert out["by_hand"] == al.PUBLISHER_NOT_LISTED and cards == [] and card_world == []


# ── search shows, the card refuses ───────────────────────────────────────────

async def test_search_marks_what_is_added_by_hand_and_the_model_sees_why(execution_db):
    cands = [capability_search.from_registry({"server": {"name": n, "version": "1.0.0", "packages": [
        {"registryType": "pypi", "identifier": "x", "version": "1.0.0"}]}}) for n in
        ("com.example/notes", "io.github.someone/notes")]
    await capability_search.mark_by_hand(cands)
    assert [(c.not_here, c.by_hand) for c in cands] == [(None, None), ("add_by_hand", al.PUBLISHER_NOT_LISTED)]
    seen = capability_search.for_model({"words": [], "notes": [], "candidates": [c.view() for c in cands]})
    assert [(c["not_here"], c["by_hand"]) for c in seen["candidates"]] == [(None, None),
                                                                          ("add_by_hand", al.PUBLISHER_NOT_LISTED)]


async def test_a_cached_result_is_marked_again_by_the_list_as_it_is_now(execution_db):
    """#584 review 5: search results are cached for hours; a widened list reaches them."""
    cand = capability_search.from_registry({"server": {"name": "io.github.someone/notes", "version": "1.0.0",
                                                       "packages": [{"registryType": "pypi", "identifier": "x"}]}})
    await capability_search.mark_by_hand([cand])
    assert cand.not_here == "add_by_hand"
    await al.save({**ALLOW, "accounts": {**ALLOW["accounts"], "someone": 12345}})
    await capability_search.mark_by_hand([cand])
    assert (cand.not_here, cand.by_hand) == (None, None)


async def test_search_keeps_another_reason_it_cannot_run(execution_db):
    cand = capability_search.from_registry({"server": {"name": "io.github.someone/x", "version": "1",
                                                       "packages": [{"registryType": "nuget", "identifier": "x"}]}})
    await capability_search.mark_by_hand([cand])
    assert (cand.not_here, cand.by_hand) == ("needs_dotnet", None)


@pytest.fixture
def card_world(execution_db, monkeypatch):
    """propose up to the card: the candidate the model was shown, a prepare that records it was reached."""
    permission_store._reset_for_tests()
    reached = []

    async def prepare(c):
        reached.append(c["id"])
        return {"runtime": c.get("runtime"), "license": ("MIT", "LICENSE"), "staging": None,
                "lock": {"file": "requirements.lock", "sha256": "0" * 64, "packages": []}}
    monkeypatch.setattr(capability_flow.capability_install, "prepare", prepare)
    return reached


async def _propose(monkeypatch, cand):
    cards = []

    async def ask(card):
        cards.append(card)
        return {"approved": False, "call_id": "c", "keys": {}, "folders": []}
    monkeypatch.setattr(capability_search, "seen", lambda conversation_id, candidate_id: dict(cand))
    out = await capability_flow.propose({"candidate_id": cand["id"], "why": "notes"}, conversation_id="c1", ask=ask,
                                        emit=lambda frame: None)
    return out, cards


def _github(monkeypatch, answers: dict):
    """api.github.com/users/<login> answers from `answers` (an id, a status code, or an exception)."""
    calls = []
    al._IDS.clear()

    class Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            login = url.rsplit("/", 1)[-1]
            calls.append(login)
            answer = answers[login]
            if isinstance(answer, Exception):
                raise answer
            request = httpx.Request("GET", url)
            if isinstance(answer, int) and 400 <= answer < 600:         # a status, not an id
                return httpx.Response(answer, json={"message": "x"}, request=request)
            return httpx.Response(200, json={"id": answer, "login": login}, request=request)
    monkeypatch.setattr(al.httpx, "AsyncClient", Client)
    return calls


async def test_an_entry_off_the_list_gets_no_card_and_nothing_is_prepared(card_world, monkeypatch):
    out, cards = await _propose(monkeypatch, _cand("io.github.someone/notes"))
    assert out["ok"] is False and out["by_hand"] == al.PUBLISHER_NOT_LISTED and "by hand" in out["note"]
    assert cards == [] and card_world == []


async def test_a_list_narrowed_after_the_search_is_what_the_card_follows(card_world, monkeypatch):
    await al.save({**ALLOW, "packages_from_any_domain": False})
    out, cards = await _propose(monkeypatch, _cand("com.example/notes"))
    assert out["by_hand"] == al.PUBLISHER_NOT_LISTED and cards == [] and card_world == []


async def test_a_domain_package_gets_its_card(card_world, monkeypatch):
    out, cards = await _propose(monkeypatch, _cand("com.example/notes"))
    assert len(cards) == 1 and card_world == ["registry:com.example/notes@1.0.0"] and out.get("declined")


async def test_a_listed_organization_gets_its_card_while_its_id_is_the_listed_one(card_world, monkeypatch):
    calls = _github(monkeypatch, {"getsentry": 1396951})
    out, cards = await _propose(monkeypatch, _cand("io.github.getsentry/sentry"))
    assert len(cards) == 1 and calls == ["getsentry"]
    await _propose(monkeypatch, _cand("io.github.getsentry/sentry"))
    assert calls == ["getsentry"]                                                  # cached for a day


@pytest.mark.parametrize("answer, reason", [
    (99999999, al.ACCOUNT_CHANGED_HANDS),                      # the login now belongs to another account
    (404, al.ACCOUNT_CHANGED_HANDS),                           # no such account any more
    (403, al.ACCOUNT_NOT_CHECKED),                             # a rate limit is no answer
    (httpx.ConnectError("down"), al.ACCOUNT_NOT_CHECKED),
])
async def test_a_listed_login_that_is_not_the_listed_organization_is_added_by_hand(card_world, monkeypatch, answer,
                                                                                    reason):
    calls = _github(monkeypatch, {"getsentry": answer})
    out, cards = await _propose(monkeypatch, _cand("io.github.getsentry/sentry"))
    assert out["by_hand"] == reason and cards == [] and card_world == []
    if reason == al.ACCOUNT_NOT_CHECKED:                      # not cached: the next card asks again
        await _propose(monkeypatch, _cand("io.github.getsentry/sentry"))
        assert calls == ["getsentry", "getsentry"]


async def test_a_github_answer_that_is_not_an_object_is_no_answer(card_world, monkeypatch):
    """#584 review 7: not checked, and not cached (the next card asks again)."""
    calls = []

    class ListAnswer:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            calls.append(url)
            return httpx.Response(200, json=[1396951], request=httpx.Request("GET", url))
    al._IDS.clear()
    monkeypatch.setattr(al.httpx, "AsyncClient", ListAnswer)
    sentry = _cand("io.github.getsentry/sentry")
    assert await al.confirm_account(sentry, ALLOW) == al.ACCOUNT_NOT_CHECKED
    assert await al.confirm_account(sentry, ALLOW) == al.ACCOUNT_NOT_CHECKED and len(calls) == 2


async def test_github_is_asked_again_after_a_day(card_world, monkeypatch):
    """#584 review 8: the id cache expires; a login that changed hands since is caught the next day."""
    answers = {"getsentry": 1396951}
    calls = _github(monkeypatch, answers)
    now = [1_000_000.0]
    monkeypatch.setattr(al.time, "time", lambda: now[0])
    sentry = _cand("io.github.getsentry/sentry")
    assert await al.confirm_account(sentry, ALLOW) is None and calls == ["getsentry"]
    answers["getsentry"] = 99
    now[0] += al.ACCOUNT_CACHE_S - 1
    assert await al.confirm_account(sentry, ALLOW) is None and len(calls) == 1
    now[0] += 2
    assert await al.confirm_account(sentry, ALLOW) == al.ACCOUNT_CHANGED_HANDS and len(calls) == 2


async def test_an_update_from_a_listed_organization_is_checked_by_its_id(card_world, monkeypatch):
    """#584 review 2: whoever took over a renamed organization's login could publish a newer version."""
    from server.db.models import CapabilitySource
    from server.services import capability_dossier
    async with __import__("server.db.session", fromlist=["x"]).AsyncSessionLocal() as db:
        db.add(CapabilitySource(id="src1", kind="mcp", name="sentry", candidate_id="c", runtime="uv", needs={},
                                grants={}, state="installed", created_at=__import__("datetime").datetime.utcnow()))
        await db.commit()
    newer = {**_cand("io.github.getsentry/sentry"), "id": "registry:io.github.getsentry/sentry@2.0.0"}

    async def check_update(source_id):
        return {"newer": True, "candidate": dict(newer)}
    monkeypatch.setattr(capability_dossier, "check_update", check_update)

    async def usable(cand):
        return {"spdx": "MIT", "read_from": "LICENSE", "verdict": "usable"}
    monkeypatch.setattr(capability_dossier, "check_candidate_license", usable)
    installed = []

    async def install_mcp(cand, **kw):
        installed.append(cand["id"])
        return {"state": "on"}
    monkeypatch.setattr(capability_flow, "install_mcp", install_mcp)
    monkeypatch.setattr(capability_dossier.capability_install, "remove", lambda source_id: _done())
    _github(monkeypatch, {"getsentry": 99999999})
    with pytest.raises(capability_dossier.DossierError) as refused:
        await capability_dossier.update("src1")
    assert refused.value.code == al.ACCOUNT_CHANGED_HANDS and installed == []
    for down in (httpx.ConnectError("down"), 503):                       # #584 re-check: GitHub not answering
        _github(monkeypatch, {"getsentry": down})
        with pytest.raises(capability_dossier.DossierError) as refused:
            await capability_dossier.update("src1")
        assert refused.value.code == al.ACCOUNT_NOT_CHECKED and installed == []
    _github(monkeypatch, {"getsentry": 1396951})
    await capability_dossier.update("src1")
    assert installed == ["registry:io.github.getsentry/sentry@2.0.0"]
    newer.update(id="registry:io.github.someone/notes@2.0.0")                 # not listed: the list stays out
    calls = _github(monkeypatch, {})
    await capability_dossier.update("src1")
    assert installed[-1] == "registry:io.github.someone/notes@2.0.0" and calls == []


async def _done():
    return None


async def test_nobody_to_ask_asks_github_nothing(card_world, monkeypatch):
    calls = _github(monkeypatch, {"getsentry": 1396951})
    monkeypatch.setattr(capability_search, "seen", lambda conversation_id, candidate_id: _cand("io.github.getsentry/s"))
    out = await capability_flow.propose({"candidate_id": "x", "why": "w"}, conversation_id="c1", ask=None,
                                        emit=lambda frame: None)
    assert out.get("not_added") and calls == []

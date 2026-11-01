"""CAP9 (v0.1.64, docs/plans/0164/CAP-capabilities.md CAP9): known vulnerabilities on the install card. Between the
lock and the card, every locked package is asked about in one OSV.dev batch query; the card shows what OSV knows,
and "not checked" when it could not ask, never "none known". No network: OSV is a fake behind httpx, shaped as
api.osv.dev answered on 2026-11-02 (jinja2 2.4.1 on PyPI, express 4.17.1 on npm)."""
import asyncio
import json

import httpx
import pytest

from server.services import osv_check

_CLIENT = httpx.AsyncClient                     # the real client, before a test patches httpx's own

PYPI = {"kind": "mcp", "runtime": "uv",
        "package": {"registry_type": "pypi", "identifier": "notes-mcp", "version": "1.2.0"}}
NPM = {"kind": "mcp", "runtime": "node",
       "package": {"registry_type": "npm", "identifier": "@acme/notes-js", "version": "2.0.1"}}


def _locked(runtime, *packages):
    return {"runtime": runtime, "lock": {"file": "x", "sha256": "0" * 64,
                                         "packages": [{"name": n, "version": v} for n, v in packages]}}


def _record(vid, *, name, ecosystem="PyPI", severity=None, summary=None, aliases=(), fixed=()):
    rec = {"id": vid, "modified": "2026-09-10T03:50:18Z", "aliases": list(aliases),
           "affected": [{"package": {"name": name, "ecosystem": ecosystem},
                         "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": f}]}]}
                        for f in fixed] or [{"package": {"name": name, "ecosystem": ecosystem}}]}
    if summary is not None:
        rec["summary"] = summary
    if severity is not None:
        rec["database_specific"] = {"severity": severity, "github_reviewed": True}
    return rec


class _Osv:
    """api.osv.dev as a fake: `hits` is the batch's answer per query (ids), `records` the vulns by id."""

    def __init__(self, monkeypatch):
        self.hits, self.records, self.requests = [], {}, []
        self.batch = None                                   # a raw answer for the batch, when set
        self.vuln = {}                                      # a raw answer for one record, by id

        async def handler(request):
            self.requests.append(request)
            path = request.url.path
            if path == "/v1/querybatch":
                if self.batch is not None:
                    return self.batch if isinstance(self.batch, httpx.Response) else httpx.Response(200, json=self.batch)
                return httpx.Response(200, json={"results": [{"vulns": [{"id": i, "modified": "x"} for i in ids]}
                                                             if ids else {} for ids in self.hits]})
            vid = path.removeprefix("/v1/vulns/")
            if vid in self.vuln:
                return self.vuln[vid]
            if vid in self.records:
                return httpx.Response(200, json=self.records[vid])
            return httpx.Response(404, json={"code": 5, "message": "Bug not found."})
        monkeypatch.setattr(osv_check.httpx, "AsyncClient",
                            lambda **kw: _CLIENT(transport=httpx.MockTransport(handler), **kw))

    def batch_sent(self):
        return json.loads(self.requests[0].content)


@pytest.fixture
def osv(monkeypatch):
    return _Osv(monkeypatch)


async def test_only_each_locked_packages_name_ecosystem_and_version_is_sent(osv):
    osv.hits = [[], []]
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0"), ("httpx", "0.27.0")))
    [batch] = osv.requests
    assert batch.method == "POST" and str(batch.url) == "https://api.osv.dev/v1/querybatch"
    assert osv.batch_sent() == {"queries": [
        {"package": {"name": "notes-mcp", "ecosystem": "PyPI"}, "version": "1.2.0"},
        {"package": {"name": "httpx", "ecosystem": "PyPI"}, "version": "0.27.0"}]}
    assert out == {"state": "checked", "source": "OSV.dev", "packages": 2, "complete": True, "count": 0,
                   "highest": None, "own": [], "deps": []}


async def test_an_npm_lock_is_asked_as_npm(osv):
    osv.hits = [[], []]
    await osv_check.check(NPM, _locked("node", ("@acme/notes-js", "2.0.1"), ("zod", "3.23.8")))
    assert [q["package"]["ecosystem"] for q in osv.batch_sent()["queries"]] == ["npm", "npm"]


async def test_a_vulnerability_in_the_package_itself_leads(osv):
    osv.hits = [["GHSA-qw6h-vgh9-j6wx"], []]
    osv.records["GHSA-qw6h-vgh9-j6wx"] = _record("GHSA-qw6h-vgh9-j6wx", name="notes-mcp", severity="HIGH",
                                                 summary="notes-mcp reads outside its folder", fixed=["1.2.1"])
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0"), ("httpx", "0.27.0")))
    assert out["own"] == [{"id": "GHSA-qw6h-vgh9-j6wx", "ids": ["GHSA-qw6h-vgh9-j6wx"], "severity": "HIGH",
                           "summary": "notes-mcp reads outside its folder", "fixed": ["1.2.1"]}]
    assert out["deps"] == [] and out["count"] == 1 and out["highest"] == "HIGH"


async def test_a_vulnerability_only_in_a_dependency_is_listed_under_it(osv):
    osv.hits = [[], ["GHSA-aaaa-bbbb-cccc"]]
    osv.records["GHSA-aaaa-bbbb-cccc"] = _record("GHSA-aaaa-bbbb-cccc", name="httpx", severity="MODERATE",
                                                 fixed=["0.28.0"])
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0"), ("httpx", "0.27.0")))
    assert out["own"] == [] and out["highest"] == "MODERATE"
    assert out["deps"] == [{"name": "httpx", "alias": None, "version": "0.27.0", "more": 0, "advisories": [
        {"id": "GHSA-aaaa-bbbb-cccc", "ids": ["GHSA-aaaa-bbbb-cccc"], "severity": "MODERATE", "summary": None,
         "fixed": ["0.28.0"]}]}]


async def test_the_same_advisory_under_two_ids_counts_once_with_githubs_severity(osv):
    """jinja2 2.4.1, as OSV answers it: PYSEC-2019-217 has no severity and aliases GHSA-462w-v97r-4m45."""
    osv.hits = [["PYSEC-2019-217", "GHSA-462w-v97r-4m45"]]
    osv.records["PYSEC-2019-217"] = _record("PYSEC-2019-217", name="jinja2", fixed=["2.10.1"],
                                            aliases=["CVE-2019-10906", "GHSA-462w-v97r-4m45"])
    osv.records["GHSA-462w-v97r-4m45"] = _record("GHSA-462w-v97r-4m45", name="jinja2", severity="HIGH",
                                                 summary="Jinja2 sandbox escape", fixed=["2.10.1"],
                                                 aliases=["CVE-2019-10906"])
    cand = {**PYPI, "package": {**PYPI["package"], "identifier": "jinja2"}}
    out = await osv_check.check(cand, _locked("uv", ("jinja2", "2.4.1")))
    assert out["count"] == 1 and out["own"] == [{
        "id": "GHSA-462w-v97r-4m45", "ids": ["GHSA-462w-v97r-4m45", "PYSEC-2019-217"], "severity": "HIGH",
        "summary": "Jinja2 sandbox escape", "fixed": ["2.10.1"]}]


async def test_fixed_versions_are_only_the_packages_own(osv):
    osv.hits = [["GHSA-xxxx-yyyy-zzzz"]]
    rec = _record("GHSA-xxxx-yyyy-zzzz", name="notes-mcp", severity="LOW", fixed=["1.3.0", "1.2.5", "1.3.0"])
    rec["affected"].append({"package": {"name": "other", "ecosystem": "PyPI"},
                            "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "9.9.9"}]}]})
    rec["affected"].append({"package": {"name": "notes-mcp", "ecosystem": "npm"},
                            "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "8.8.8"}]}]})
    osv.records["GHSA-xxxx-yyyy-zzzz"] = rec
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    assert out["own"][0]["fixed"] == ["1.2.5", "1.3.0"]


@pytest.mark.parametrize("written", ["Notes_MCP", "notes.mcp", "NOTES-mcp"])
async def test_a_pypi_name_is_the_package_itself_however_it_is_written(osv, written):
    osv.hits = [["GHSA-qw6h-vgh9-j6wx"]]
    osv.records["GHSA-qw6h-vgh9-j6wx"] = _record("GHSA-qw6h-vgh9-j6wx", name="notes-mcp", severity="LOW")
    cand = {**PYPI, "package": {**PYPI["package"], "identifier": written}}
    out = await osv_check.check(cand, _locked("uv", ("notes-mcp", "1.2.0")))
    assert len(out["own"]) == 1 and out["deps"] == []


async def test_an_npm_name_is_matched_as_written(osv):
    osv.hits = [["GHSA-qw6h-vgh9-j6wx"]]
    osv.records["GHSA-qw6h-vgh9-j6wx"] = _record("GHSA-qw6h-vgh9-j6wx", name="@acme/notes-js", ecosystem="npm",
                                                 severity="LOW")
    cand = {**NPM, "package": {**NPM["package"], "identifier": "@Acme/notes-js"}}
    out = await osv_check.check(cand, _locked("node", ("@acme/notes-js", "2.0.1")))
    assert out["own"] == [] and len(out["deps"]) == 1          # npm names are case-sensitive


@pytest.mark.parametrize("severity, shown", [("CRITICAL", "CRITICAL"), ("moderate", "MODERATE"), ("SEVERE", "UNKNOWN"),
                                             (None, "UNKNOWN"), (7, "UNKNOWN")])
async def test_severity_is_githubs_word_or_unknown(osv, severity, shown):
    osv.hits = [["GHSA-qw6h-vgh9-j6wx"]]
    rec = _record("GHSA-qw6h-vgh9-j6wx", name="notes-mcp")
    rec["database_specific"] = {"severity": severity}
    osv.records["GHSA-qw6h-vgh9-j6wx"] = rec
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    assert out["own"][0]["severity"] == shown and out["highest"] == shown


async def test_highest_is_the_worst_known_severity(osv):
    osv.hits = [["GHSA-aaaa-aaaa-aaaa"], ["GHSA-bbbb-bbbb-bbbb", "GHSA-cccc-cccc-cccc"]]
    osv.records["GHSA-aaaa-aaaa-aaaa"] = _record("GHSA-aaaa-aaaa-aaaa", name="notes-mcp", severity="LOW")
    osv.records["GHSA-bbbb-bbbb-bbbb"] = _record("GHSA-bbbb-bbbb-bbbb", name="httpx", severity="CRITICAL")
    osv.records["GHSA-cccc-cccc-cccc"] = _record("GHSA-cccc-cccc-cccc", name="httpx")
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0"), ("httpx", "0.27.0")))
    assert out["highest"] == "CRITICAL" and out["count"] == 3


async def test_a_record_that_does_not_answer_still_counts_with_unknown_severity(osv):
    osv.hits = [["GHSA-qw6h-vgh9-j6wx", "GHSA-rv95-896h-c2vc"]]
    osv.records["GHSA-qw6h-vgh9-j6wx"] = _record("GHSA-qw6h-vgh9-j6wx", name="notes-mcp", severity="LOW")
    osv.vuln["GHSA-rv95-896h-c2vc"] = httpx.Response(503)
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    assert out["state"] == "checked" and out["count"] == 2
    assert [a["severity"] for a in out["own"]] == ["LOW", "UNKNOWN"]


async def test_records_past_the_lookup_limit_are_counted_but_not_fetched(osv, monkeypatch):
    monkeypatch.setattr(osv_check, "LOOKUPS_MAX", 2)
    osv.hits = [[f"GHSA-aaaa-aaaa-aaa{i}" for i in range(4)]]
    for i in range(4):
        osv.records[f"GHSA-aaaa-aaaa-aaa{i}"] = _record(f"GHSA-aaaa-aaaa-aaa{i}", name="notes-mcp", severity="HIGH")
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    assert len(osv.requests) == 1 + 2 and out["complete"] is False and out["count"] == 4
    assert [a["severity"] for a in out["own"]] == ["HIGH", "HIGH", "UNKNOWN", "UNKNOWN"]


async def test_the_package_itself_is_looked_up_before_its_dependencies(osv, monkeypatch):
    monkeypatch.setattr(osv_check, "LOOKUPS_MAX", 1)
    osv.hits = [["GHSA-dddd-dddd-dddd"], ["GHSA-oooo-oooo-oooo"]]
    osv.records["GHSA-dddd-dddd-dddd"] = _record("GHSA-dddd-dddd-dddd", name="httpx", severity="LOW")
    osv.records["GHSA-oooo-oooo-oooo"] = _record("GHSA-oooo-oooo-oooo", name="notes-mcp", severity="HIGH")
    out = await osv_check.check(PYPI, _locked("uv", ("httpx", "0.27.0"), ("notes-mcp", "1.2.0")))
    assert out["own"][0]["severity"] == "HIGH" and out["deps"][0]["advisories"][0]["severity"] == "UNKNOWN"


async def test_what_the_card_lists_is_capped(osv, monkeypatch):
    monkeypatch.setattr(osv_check, "SHOWN_MAX", 2)
    osv.hits = [[], *[[f"GHSA-dep{i}-aaaa-aaaa", f"GHSA-dep{i}-bbbb-bbbb", f"GHSA-dep{i}-cccc-cccc"]
                      for i in range(3)]]
    lock = _locked("uv", ("notes-mcp", "1.2.0"), *[(f"dep{i}", "1.0") for i in range(3)])
    out = await osv_check.check(PYPI, lock)
    assert out["count"] == 9 and len(out["deps"]) == 2
    assert all(len(d["advisories"]) == 2 and d["more"] == 1 for d in out["deps"])


async def test_osvs_words_are_cleaned_as_a_card_name_is(osv):
    """OSV's summary and versions are outside text on the card: no bidi override or zero-width character."""
    osv.hits = [["GHSA-qw6h-vgh9-j6wx"]]
    osv.records["GHSA-qw6h-vgh9-j6wx"] = _record(
        "GHSA-qw6h-vgh9-j6wx", name="notes-mcp", severity="HIGH",
        summary="safe" + chr(0x202E) + " upgrade" + chr(0x200B) + "\nnow " + "x" * 400, fixed=["1.2" + chr(0x2066) + ".1"])
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    [adv] = out["own"]
    assert adv["summary"].startswith("safe upgrade now x") and len(adv["summary"]) == osv_check.SUMMARY_MAX
    assert adv["fixed"] == ["1.2.1"]


@pytest.mark.parametrize("bad", ["../../v1/query", "GHSA qw6h", "", "x" * 65, 7, None])
async def test_an_id_not_shaped_like_one_is_no_answer(osv, bad):
    osv.batch = {"results": [{"vulns": [{"id": bad, "modified": "x"}]}]}
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    assert out == {"state": "not_checked", "why": "osv_did_not_answer"} and len(osv.requests) == 1


@pytest.mark.parametrize("answer", [
    httpx.Response(503), httpx.Response(429), httpx.Response(302, headers={"location": "https://evil.example/x"}),
    httpx.Response(200, content=b"not json"), httpx.Response(200, json=[]), httpx.Response(200, json={}),
    httpx.Response(200, json={"results": "no"}), httpx.Response(200, json={"results": [{}, {}]}),
    httpx.Response(200, json={"results": [{"vulns": {}}]}), httpx.Response(200, json={"results": ["x"]}),
], ids=["503", "429", "redirect", "not json", "a list", "no results", "results not a list", "too many results",
        "vulns not a list", "a result not an object"])
async def test_osv_not_answering_is_not_checked_never_none_known(osv, answer):
    osv.batch = answer
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    assert out == {"state": "not_checked", "why": "osv_did_not_answer"}


async def test_an_answer_past_its_size_cap_is_not_checked(osv, monkeypatch):
    monkeypatch.setattr(osv_check, "MAX_BYTES", {"batch": 64, "vuln": 64})
    osv.batch = {"results": [{"vulns": [{"id": "GHSA-qw6h-vgh9-j6wx", "modified": "x" * 100}]}]}
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    assert out["state"] == "not_checked"


async def test_a_record_past_its_size_cap_counts_with_unknown_severity(osv, monkeypatch):
    monkeypatch.setattr(osv_check, "MAX_BYTES", {"batch": 1 << 20, "vuln": 64})
    osv.hits = [["GHSA-qw6h-vgh9-j6wx"]]
    osv.records["GHSA-qw6h-vgh9-j6wx"] = _record("GHSA-qw6h-vgh9-j6wx", name="notes-mcp", severity="LOW",
                                                 summary="x" * 200)
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    assert out["state"] == "checked" and out["own"][0]["severity"] == "UNKNOWN"


async def test_a_slow_osv_past_the_deadline_is_not_checked(monkeypatch):
    monkeypatch.setattr(osv_check, "DEADLINE_S", 0.05)

    async def handler(request):
        await asyncio.sleep(5)
        return httpx.Response(200, json={"results": [{}]})
    monkeypatch.setattr(osv_check.httpx, "AsyncClient",
                        lambda **kw: _CLIENT(transport=httpx.MockTransport(handler), **kw))
    out = await asyncio.wait_for(osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0"))), 2)
    assert out == {"state": "not_checked", "why": "osv_did_not_answer"}


async def test_a_lock_past_osvs_batch_limit_is_asked_in_part(osv, monkeypatch):
    monkeypatch.setattr(osv_check, "QUERIES_MAX", 2)
    osv.hits = [[], []]
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0"), ("a", "1"), ("b", "1")))
    assert len(osv.batch_sent()["queries"]) == 2 and out["packages"] == 3 and out["complete"] is False


@pytest.mark.parametrize("cand, prepared, why", [
    ({**PYPI, "runtime": "remote", "package": None}, {"runtime": "remote", "lock": None}, "remote"),
    ({**PYPI, "runtime": "mcpb"}, _locked("mcpb", ("notes", "1.2.0")), "bundle"),
    (PYPI, {"runtime": "uv", "lock": None}, "no_lock"),
    (PYPI, None, "no_lock"),
    ({"kind": "skill"}, None, "skill"),                    # a skill names no packages to look up
])
async def test_what_has_no_lock_osv_knows_is_skipped(osv, cand, prepared, why):
    assert await osv_check.check(cand, prepared) == {"state": "skipped", "why": why}
    assert osv.requests == []


async def test_a_stop_while_osv_is_asked_is_not_swallowed(monkeypatch):
    started = asyncio.Event()

    async def handler(request):
        started.set()
        await asyncio.sleep(5)
        return httpx.Response(200, json={"results": [{}]})
    monkeypatch.setattr(osv_check.httpx, "AsyncClient",
                        lambda **kw: _CLIENT(transport=httpx.MockTransport(handler), **kw))
    task = asyncio.ensure_future(osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0"))))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ── on the card: between the lock and the card, facts only (the user's question 5 is open) ──

CAND = {"id": "registry:com.example/excel-mcp-server@1.1.2", "kind": "mcp", "name": "excel-mcp-server",
        "summary": "Reads and writes .xlsx", "source": "registry", "source_url": "https://github.com/acme/excel-mcp",
        "repo": "acme/excel-mcp", "version": "1.1.2", "runtime": "uv",
        "package": {"registry_type": "pypi", "identifier": "excel-mcp-server", "version": "1.1.2", "arguments": []},
        "remote": None, "not_here": None, "path": None, "stars": 1, "pushed_days": 1,
        "needs": {"keys": [], "network": None}, "license": {"spdx": "MIT", "read_from": "LICENSE", "verdict": "usable"}}


async def _card(monkeypatch, cand=CAND):
    from server.services import capability_flow, capability_search, permission_store
    permission_store._reset_for_tests()
    cards = []

    async def ask(card):
        cards.append(card)
        return {"approved": False, "call_id": "c", "keys": {}, "folders": []}
    monkeypatch.setattr(capability_search, "seen", lambda conversation_id, candidate_id: dict(cand))
    out = await capability_flow.propose({"candidate_id": cand["id"], "why": "sheets"}, conversation_id="c1", ask=ask,
                                        emit=lambda frame: None)
    return out, cards


async def test_the_card_carries_what_osv_said_of_that_lock(execution_db, monkeypatch, fake_capability_prepare):
    asked = []

    async def check(cand, prepared):
        asked.append((cand["id"], prepared["lock"]["packages"]))
        return {"state": "checked", "marker": True}
    monkeypatch.setattr(osv_check, "check", check)
    _, [card] = await _card(monkeypatch)
    assert asked == [(CAND["id"], [{"name": "excel-mcp-server", "version": "1.1.2"}])]
    assert card["vulns"] == {"state": "checked", "marker": True}


async def test_a_known_vulnerability_in_the_package_is_on_the_card_and_nothing_is_refused(
        execution_db, monkeypatch, fake_capability_prepare):
    """Until the user's question 5 is answered, a hit changes no button: the card is still asked."""
    monkeypatch.setattr(osv_check, "check", _REAL_CHECK)
    fake = _Osv(monkeypatch)
    fake.hits = [["GHSA-qw6h-vgh9-j6wx"]]
    fake.records["GHSA-qw6h-vgh9-j6wx"] = _record("GHSA-qw6h-vgh9-j6wx", name="excel-mcp-server", severity="CRITICAL")
    out, [card] = await _card(monkeypatch)
    assert card["vulns"]["highest"] == "CRITICAL" and card["vulns"]["own"][0]["id"] == "GHSA-qw6h-vgh9-j6wx"
    assert out.get("declined") is True                     # the card was shown and answered; nothing refused it


async def test_osv_down_still_shows_the_card_as_not_checked(execution_db, monkeypatch, fake_capability_prepare):
    monkeypatch.setattr(osv_check, "check", _REAL_CHECK)
    _Osv(monkeypatch).batch = httpx.Response(503)
    _, [card] = await _card(monkeypatch)
    assert card["vulns"] == {"state": "not_checked", "why": "osv_did_not_answer"}


async def test_a_stop_while_osv_is_asked_discards_the_staged_lock(execution_db, monkeypatch, fake_capability_prepare):
    from server.services import capability_install
    discarded = []

    async def stopped(cand, prepared):
        raise asyncio.CancelledError
    monkeypatch.setattr(osv_check, "check", stopped)
    monkeypatch.setattr(capability_install, "discard", lambda locked: discarded.append(locked["lock"]["sha256"]))
    with pytest.raises(asyncio.CancelledError):
        await _card(monkeypatch)
    assert discarded == ["0" * 64]


async def test_a_skills_card_is_not_checked(execution_db, monkeypatch):
    from server.services import capability_flow
    asked = []

    async def check(cand, prepared):
        asked.append(cand)
    monkeypatch.setattr(osv_check, "check", check)

    async def prepared(c):
        return ({"commit": "0" * 40, "files": {"SKILL.md": "f" * 64}, "sizes": {"SKILL.md": 1}, "skipped": [],
                 "info": {"body": "x"}, "skill_md": "x", "scripts": {}, "references": {}},
                {"level": "clean", "findings": []})
    monkeypatch.setattr(capability_flow, "prepare_skill", prepared)
    skill = {**CAND, "id": "library:anthropics/skills:skills/csv/SKILL.md", "kind": "skill", "runtime": "skill",
             "package": None, "path": "skills/csv/SKILL.md", "repo": "anthropics/skills", "version": "a" * 40}
    _, [card] = await _card(monkeypatch, skill)
    assert asked == [] and "vulns" not in card


_REAL_CHECK = osv_check.check


async def test_a_redirect_is_not_followed_even_to_a_host_that_would_answer(monkeypatch):
    """OSV is asked at api.osv.dev only: a redirect elsewhere is no answer, though the other host answers well."""
    hosts = []

    async def handler(request):
        hosts.append(request.url.host)
        if request.url.host == "api.osv.dev":
            return httpx.Response(307, headers={"location": "https://osv-mirror.example/v1/querybatch"})
        return httpx.Response(200, json={"results": [{}]})
    monkeypatch.setattr(osv_check.httpx, "AsyncClient",
                        lambda **kw: _CLIENT(transport=httpx.MockTransport(handler), **kw))
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    assert out == {"state": "not_checked", "why": "osv_did_not_answer"} and hosts == ["api.osv.dev"]


async def test_a_record_for_another_id_is_not_that_advisorys(osv):
    osv.hits = [["GHSA-qw6h-vgh9-j6wx"]]
    osv.records["GHSA-qw6h-vgh9-j6wx"] = _record("GHSA-rv95-896h-c2vc", name="notes-mcp", severity="CRITICAL",
                                                 summary="another advisory")
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    assert out["own"] == [{"id": "GHSA-qw6h-vgh9-j6wx", "ids": ["GHSA-qw6h-vgh9-j6wx"], "severity": "UNKNOWN",
                           "summary": None, "fixed": []}]


@pytest.mark.parametrize("odd", [
    {"database_specific": ["HIGH"]}, {"database_specific": "HIGH"}, {"aliases": [{"id": "x"}]}, {"aliases": "GHSA"},
    {"affected": 5}, {"affected": [5]}, {"affected": [{"package": "notes-mcp"}]},
    {"affected": [{"package": {"name": "notes-mcp", "ecosystem": "PyPI"}, "ranges": {"events": []}}]},
    {"affected": [{"package": {"name": "notes-mcp", "ecosystem": "PyPI"}, "ranges": [{"events": 5}]}]},
    {"affected": [{"package": {"name": "notes-mcp", "ecosystem": "PyPI"}, "ranges": [{"events": [5, {"fixed": 7}]}]}]},
    {"summary": ["x"]},
], ids=["severity a list", "severity a string", "an alias an object", "aliases a string", "affected a number",
        "an affected entry a number", "a package a string", "ranges an object", "events a number",
        "an event a number", "summary a list"])
async def test_a_record_of_an_odd_shape_counts_as_unknown_and_never_breaks_the_card(osv, odd):
    """OSV's records are outside data: a shape the parser does not expect only makes that record unknown."""
    osv.hits = [["GHSA-qw6h-vgh9-j6wx"]]
    osv.records["GHSA-qw6h-vgh9-j6wx"] = {**_record("GHSA-qw6h-vgh9-j6wx", name="notes-mcp"), **odd}
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    assert out["state"] == "checked" and out["count"] == 1
    assert out["own"][0]["severity"] == "UNKNOWN" and out["own"][0]["fixed"] == []


# ── #661 review (effort=max, 1fb00df6) ──

async def test_an_npm_alias_is_asked_by_its_real_name(osv):
    """F1: npm keeps an alias's real name in its lock entry (`"innocent-name": "npm:event-stream@3.3.6"`); asking by
    the folder looked up a package nobody installed, and read as nothing known."""
    osv.hits = [[], ["GHSA-mh6f-8j2x-4483"]]
    osv.records["GHSA-mh6f-8j2x-4483"] = _record("GHSA-mh6f-8j2x-4483", name="event-stream", ecosystem="npm",
                                                 severity="CRITICAL", fixed=["4.0.0"])
    lock = _locked("node", ("@acme/notes-js", "2.0.1"), ("innocent-name", "3.3.6"))
    lock["lock"]["packages"][1]["registry_name"] = "event-stream"
    out = await osv_check.check(NPM, lock)
    assert [q["package"]["name"] for q in osv.batch_sent()["queries"]] == ["@acme/notes-js", "event-stream"]
    assert out["deps"][0]["name"] == "event-stream" and out["deps"][0]["alias"] == "innocent-name"
    assert out["deps"][0]["advisories"][0]["fixed"] == ["4.0.0"] and out["highest"] == "CRITICAL"


async def test_the_npm_lock_keeps_an_aliass_real_name(monkeypatch, tmp_path):
    """F1, where the name comes from: `lock_npm` reads each entry's own `name` when npm wrote one."""
    from server.services import capability_install, capability_runtime
    reg = "https://registry.npmjs.org/"

    async def ensure(name):
        return tmp_path / "rt" / name / "bin" / name

    async def run(argv, *, cwd, env):
        (cwd / "package-lock.json").write_text(json.dumps({"packages": {
            "": {"name": "arslan-capability"},
            "node_modules/@acme/notes-js": {"version": "2.0.1", "resolved": reg + "@acme/notes-js/-/notes-js-2.0.1.tgz",
                                            "integrity": "sha512-" + "A" * 86 + "=="},
            "node_modules/innocent-name": {"name": "event-stream", "version": "3.3.6",
                                           "resolved": reg + "event-stream/-/event-stream-3.3.6.tgz",
                                           "integrity": "sha512-" + "B" * 86 + "=="}}}))
        return ""
    monkeypatch.setattr(capability_runtime, "ensure", ensure)
    monkeypatch.setattr(capability_install, "_run", run)
    lock = await capability_install.lock_npm(tmp_path, "@acme/notes-js", "2.0.1")
    assert lock["packages"] == [{"name": "@acme/notes-js", "version": "2.0.1", "registry_name": "@acme/notes-js"},
                                {"name": "innocent-name", "version": "3.3.6", "registry_name": "event-stream"}]
    assert capability_install.lock_summary({"lock": lock})["packages"] == [
        {"name": "@acme/notes-js", "version": "2.0.1"}, {"name": "innocent-name", "version": "3.3.6"}]


async def test_json_nested_too_deep_for_the_parser_is_not_checked(osv):
    """F2: `[[[…]]]` under the size cap raised RecursionError, which is not a ValueError, and broke the card."""
    deep = b"[" * 100_000 + b"]" * 100_000
    osv.batch = httpx.Response(200, content=deep)
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    assert out == {"state": "not_checked", "why": "osv_did_not_answer"}


async def test_a_record_nested_too_deep_counts_as_unknown(osv):
    osv.hits = [["GHSA-qw6h-vgh9-j6wx"]]
    osv.vuln["GHSA-qw6h-vgh9-j6wx"] = httpx.Response(200, content=b"[" * 100_000 + b"]" * 100_000)
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    assert out["state"] == "checked" and out["own"][0]["severity"] == "UNKNOWN"


async def test_a_lock_with_no_packages_is_not_checked(osv):
    """F3: an empty lock read as "checked, nothing known"; nothing was asked, so nothing is known."""
    out = await osv_check.check(PYPI, _locked("uv"))
    assert out == {"state": "not_checked", "why": "empty_lock"} and osv.requests == []


@pytest.mark.parametrize("odd", ["1.0" + chr(0xB2), chr(0x661) + "." + chr(0x662), "v" + chr(0x2460)])
async def test_one_odd_fixed_version_drops_nothing(osv, odd):
    """Nit: a superscript or another script's digit made the version sort raise, which dropped every hit."""
    osv.hits = [["GHSA-qw6h-vgh9-j6wx"]]
    osv.records["GHSA-qw6h-vgh9-j6wx"] = _record("GHSA-qw6h-vgh9-j6wx", name="notes-mcp", severity="HIGH",
                                                 fixed=["1.10.0", odd, "1.9.0"])
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    assert out["state"] == "checked" and out["own"][0]["severity"] == "HIGH"
    fixed = out["own"][0]["fixed"]
    assert [v for v in fixed if v.isascii()] == ["1.9.0", "1.10.0"] and len(fixed) == 3


async def test_the_fixed_versions_listed_are_capped(osv):
    osv.hits = [["GHSA-qw6h-vgh9-j6wx"]]
    osv.records["GHSA-qw6h-vgh9-j6wx"] = _record("GHSA-qw6h-vgh9-j6wx", name="notes-mcp", severity="LOW",
                                                 fixed=[f"1.{i}.0" for i in range(3000)])
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    assert out["own"][0]["fixed"] == [f"1.{i}.0" for i in range(osv_check.FIXED_MAX)]


async def test_a_result_with_another_page_is_counted_incomplete(osv):
    """Nit: `next_page_token` is not followed (a package with more than a page of advisories); it says so."""
    osv.batch = {"results": [{"vulns": [{"id": "GHSA-qw6h-vgh9-j6wx", "modified": "x"}], "next_page_token": "abc"}]}
    osv.records["GHSA-qw6h-vgh9-j6wx"] = _record("GHSA-qw6h-vgh9-j6wx", name="notes-mcp", severity="LOW")
    out = await osv_check.check(PYPI, _locked("uv", ("notes-mcp", "1.2.0")))
    assert out["complete"] is False and out["count"] == 1 and len(osv.requests) == 2

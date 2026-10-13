"""0.1.61 §C4: the license step is the server's — an import the person has not decided answers
409 with the text to read — and every import a person makes is one ledger row (§A8)."""
from __future__ import annotations

import asyncio
import errno
import inspect
import json
import logging
import pathlib
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from server.db.models import ApprovalEvent, SkillPack
from server.services import capability_flow, github_eval, permission_store, permissions, skill_files, skill_import
from tests.server.skill_archives import COMMIT, tarball

MD = "---\nname: handoff\ndescription: Hand work over.\n---\n\n# Handoff\nSteps.\n"
GPL = "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n"
REF = "example-org/example-skills"
IMPORT = "/api/v1/discovery/skills/import"
REAL_FETCH_REPO = github_eval.fetch_repo          # before the `github` fixture replaces it


@pytest.fixture
def github(monkeypatch, tmp_path):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(skill_files, "_trash", lambda path: None)
    permission_store._reset_for_tests()

    async def fetch_repo(owner, repo):
        return {"full_name": f"{owner}/{repo}", "html_url": "", "stars": 3, "forks": 0, "license": "GPL-3.0",
                "pushed_days": 1, "description": "", "topics": []}

    async def fetch_archive(owner, repo, ref):
        return tarball({"SKILL.md": MD, "LICENSE": GPL, "scripts/run.py": ("exec", "print(1)\n")})
    monkeypatch.setattr(skill_import.github_eval, "fetch_repo", fetch_repo)
    monkeypatch.setattr(skill_import, "_fetch_archive", fetch_archive)
    skill_import._archive_cache.clear()


def serves(monkeypatch, files: dict) -> None:
    """What GitHub serves next, instead of the fixture's one skill."""
    async def fetch_archive(owner, repo, ref):
        return tarball(files)
    monkeypatch.setattr(skill_import, "_fetch_archive", fetch_archive)
    skill_import._archive_cache.clear()


def importer_raises(monkeypatch, exc: BaseException) -> None:
    async def raises(ref, path, **kwargs):
        raise exc
    monkeypatch.setattr(skill_import, "import_skill", raises)


async def test_an_undecided_license_is_a_409_with_the_text_then_the_decision_imports(client, github):
    body = {"ref": "example-org/example-skills", "path": "SKILL.md"}
    first = await client.post("/api/v1/discovery/skills/import", json=body)
    assert first.status_code == 409
    detail = first.json()["detail"]
    assert detail["code"] == "license_step" and detail["key"] == "handoff"
    assert detail["license"]["text"] == GPL and detail["license"]["recognised"] is False
    async with client.db_maker() as db:
        assert await db.get(SkillPack, "handoff") is None
        assert (await db.execute(select(ApprovalEvent))).scalars().all() == []
    done = await client.post("/api/v1/discovery/skills/import",
                             json={**body, "license_ok": detail["license"]["sha256"]})
    assert done.status_code == 200 and done.json()["local_only"] is True
    async with client.db_maker() as db:
        [event] = (await db.execute(select(ApprovalEvent))).scalars().all()
    assert (event.kind, event.target, event.decided_by, event.decision, event.scope, event.mode) == (
        "capability", "skill:handoff", "user", "allow", "once", "standard")
    assert event.extra["local_only"] is True and event.conversation_id is None


async def test_a_skill_decision_row_is_shaped_like_the_ones_pr2_writes(client, github):
    """Ruling F, against PR 2 as built (a36cce63): kind `capability` (a kind `permissions` knows,
    once-only), decided by the user, a yes is scope once and a no has none (as `permissions._ask`
    records it), `extra` is cut to 1 KB and never carries PR 2's reserved "always" key — so the row
    is never one the Inbox lists or "Always allow" could be given for."""
    from server.services import skill_ledger
    assert skill_ledger.KIND in permissions.KINDS
    assert permissions.options_for(permissions.Request(           # once-only: never a grant or a rule
        kind=skill_ledger.KIND, target="skill:x", title="t", always_label="x")) == ["once"]
    await skill_ledger.record(target="skill:a", detail="d", allowed=True, extra={
        "local_only": True, permissions.ALWAYS_KEY: [["app", "com.example.app", "Example"]]})
    await skill_ledger.record(target="skill:b", detail="d", allowed=False, conversation_id="conv-1",
                              extra={"note": "n" * 3000})
    async with client.db_maker() as db:
        yes, no = (await db.execute(select(ApprovalEvent).order_by(ApprovalEvent.id))).scalars().all()
        assert (yes.kind, yes.decided_by, yes.decision, yes.scope) == ("capability", "user", "allow", "once")
        assert (no.decided_by, no.decision, no.scope, no.conversation_id) == ("user", "deny", None, "conv-1")
        assert yes.extra == {"local_only": True}                  # the reserved key is dropped
        assert list(no.extra) == ["truncated"]                    # cut to 1 KB, as permissions._extra cuts it
        assert permissions.always_from(yes.extra) == []
        assert not permission_store.could_not_ask(yes) and not permission_store.could_not_ask(no)
        assert await permission_store.refused_since(db, datetime.utcnow() - timedelta(hours=1)) == []
    assert (await client.get("/api/v1/approvals/refused")).json() == []          # the Inbox lists none
    refused = await client.post("/api/v1/permissions/rules", json={"refused_id": yes.id})
    assert refused.status_code == 409 and refused.json()["detail"] == {"code": "not_a_refusal"}


async def test_a_bad_path_is_a_400(client, github):
    bad = await client.post("/api/v1/discovery/skills/import",
                            json={"ref": "example-org/example-skills", "path": "../SKILL.md"})
    assert bad.status_code == 400


async def test_a_wrong_or_stale_answer_is_the_license_step_again_with_the_text_that_is_there_now(client, github,
                                                                                                monkeypatch):
    """0.1.61 §C4 (the plan: "without a matching license_ok answers 409"): the person reads what is actually
    there. The body is the current step plus `stale: true`; nothing is imported on a mismatch. No answer at all
    (absent, or "") is the step without `stale`."""
    sha = skill_import.license_sha256(GPL)
    wrong = ["0" * 64, sha[:63], sha[:8], sha + "0", sha[1:], "é" * 64, "İ" * 64, sha[:10] + "\x00" + sha[11:]]
    for answer in wrong:
        r = await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md", "license_ok": answer})
        assert r.status_code == 409, answer
        detail = r.json()["detail"]
        assert detail["stale"] is True and detail["code"] == "license_step" and detail["key"] == "handoff"
        assert detail["license"]["text"] == GPL and detail["license"]["sha256"] == sha
    for no_answer in ({}, {"license_ok": ""}, {"license_ok": None}):
        r = await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md", **no_answer})
        assert r.status_code == 409 and "stale" not in r.json()["detail"], no_answer
    # the realistic one: the person read the text that was served, and it changed before they said yes
    amended = GPL + "\nAdditional terms: none.\n"
    serves(monkeypatch, {"SKILL.md": MD, "LICENSE": amended})
    r = await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md", "license_ok": sha})
    detail = r.json()["detail"]
    assert r.status_code == 409 and detail["stale"] is True
    assert detail["license"]["text"] == amended and detail["license"]["sha256"] == skill_import.license_sha256(amended)
    async with client.db_maker() as db:
        assert await db.get(SkillPack, "handoff") is None
        assert (await db.execute(select(ApprovalEvent))).scalars().all() == []


async def test_a_license_too_long_to_show_stays_a_400_and_a_non_string_answer_is_a_422(client, github, monkeypatch):
    """There is no text to show for the first, and the second is not an answer."""
    serves(monkeypatch, {"SKILL.md": MD, "LICENSE": "x" * (skill_import.MAX_LICENSE_BYTES + 1)})
    for answer in (None, "", skill_import.license_sha256(""), "0" * 64):
        r = await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md", "license_ok": answer})
        assert r.status_code == 400 and "too long" in r.json()["detail"], answer
    for answer in (123, 1.5, True, ["x"], {"sha": "x"}):
        assert (await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md", "license_ok": answer})
                ).status_code == 422, answer


async def test_the_scan_returns_the_commit_and_the_text_to_read(client, github):
    r = await client.post("/api/v1/discovery/skills/scan", json={"ref": "example-org/example-skills"})
    assert r.status_code == 200
    [skill] = r.json()["skills"]
    assert r.json()["commit"] and skill["license"]["text"] == GPL and skill["has_scripts"] is True


async def test_a_ledger_that_cannot_be_written_never_undoes_the_import(client, github, monkeypatch):
    from server.services import skill_ledger

    async def broken(db, **fields):
        raise RuntimeError("disk full")
    monkeypatch.setattr(permission_store, "record", broken)
    await skill_ledger.record(target="skill:x", detail="d", allowed=True)        # logged, no raise
    r = await client.post("/api/v1/discovery/skills/import",
                          json={"ref": "example-org/example-skills", "path": "SKILL.md",
                                "license_ok": skill_import.license_sha256(GPL)})
    assert r.status_code == 200


# ── one ledger row per decision, and only for a decision that was made ───────

async def test_a_recognised_license_imports_without_a_step_and_is_one_row(client, github, monkeypatch):
    serves(monkeypatch, {"SKILL.md": MD, "LICENSE": "MIT License\n\nPermission is hereby granted, free of charge, "
                                                     "to any person obtaining a copy\n"})
    r = await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md"})
    assert r.status_code == 200 and r.json()["local_only"] is False
    async with client.db_maker() as db:
        [event] = (await db.execute(select(ApprovalEvent))).scalars().all()
    assert (event.target, event.decision, event.extra["local_only"]) == ("skill:handoff", "allow", False)
    assert event.detail == f"{REF}@{COMMIT[:12]} SKILL.md" and event.extra["commit"] == COMMIT[:12]


async def test_a_refused_import_writes_no_ledger_row(client, github):
    for body in ({"ref": REF, "path": "SKILL.md"},                                   # 409: nothing was decided
                 {"ref": REF, "path": "SKILL.md", "license_ok": "0" * 64},           # 400: a stale answer
                 {"ref": REF, "path": "../SKILL.md"}):                               # 400: a bad path
        assert (await client.post(IMPORT, json=body)).status_code in (400, 409)
    async with client.db_maker() as db:
        assert (await db.execute(select(ApprovalEvent))).scalars().all() == []


# ── carry: the 409 is the whole license, never `text_omitted` ────────────────

TWO_SKILLS = {"LICENSE": GPL,
              "skills/a/SKILL.md": "---\nname: alpha\ndescription: First.\n---\n# Alpha\n",
              "skills/b/SKILL.md": "---\nname: beta\ndescription: Second.\n---\n# Beta\n"}


async def test_the_409_carries_the_full_text_even_where_the_scan_left_it_out(client, github, monkeypatch):
    serves(monkeypatch, TWO_SKILLS)
    scanned = (await client.post("/api/v1/discovery/skills/scan", json={"ref": REF})).json()["skills"]
    [sent] = [s for s in scanned if "text" in s["license"]]
    [left_out] = [s for s in scanned if s["license"].get("text_omitted")]
    assert "text" not in left_out["license"] and left_out["license"]["sha256"] == sent["license"]["sha256"]
    r = await client.post(IMPORT, json={"ref": REF, "path": left_out["path"]})
    assert r.status_code == 409
    assert r.json()["detail"]["key"] == "beta" and r.json()["detail"]["name"] == "beta"        # which skill asks
    shown = r.json()["detail"]["license"]
    assert shown["text"] == GPL and "text_omitted" not in shown
    assert shown["sha256"] == left_out["license"]["sha256"]          # the sha the scan named is the one asked about


# ── carry: the license text is data ──────────────────────────────────────────

HOSTILE = "<script>alert(1)</script>‮ gnp.exe\x1b[31m\x00 </pre><img src=x onerror=alert(2)>\n"


async def test_the_license_text_travels_as_a_json_string_and_is_in_no_log_or_message(client, github, monkeypatch,
                                                                                    caplog):
    serves(monkeypatch, {"SKILL.md": MD, "LICENSE": HOSTILE})
    with caplog.at_level(logging.DEBUG):
        r = await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md"})
        stale = await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md", "license_ok": "0" * 64})
    assert r.status_code == 409 and r.headers["content-type"].startswith("application/json")
    assert r.json()["detail"]["license"]["text"] == HOSTILE                       # as it is: escaped by the reader (Task 12)
    assert stale.status_code == 409 and stale.json()["detail"]["stale"] is True       # the text is its body, as data
    for record in caplog.records:                                                   # no log line quotes the text
        assert "alert(" not in record.getMessage() and "gnp.exe" not in record.getMessage()


# ── carry: every error the importer can raise has an answer ──────────────────

@pytest.mark.parametrize("exc, status, why", [
    (httpx.ReadTimeout("the download stopped: no new bytes for 30 seconds"), 502,
     "the download stopped: no new bytes for 30 seconds"),
    (httpx.ConnectError("[Errno 8] nodename nor servname provided"), 502, "the connection failed"),
    (httpx.HTTPStatusError("Server error '503' for url 'https://x'\nFor more information check: https://y",
                           request=httpx.Request("GET", "https://x"),
                           response=httpx.Response(503, request=httpx.Request("GET", "https://x"))), 502,
     "it answered 503"),
    (TimeoutError("the proxy gave up"), 502, "the request timed out"),     # an OSError, but not the disk's
])
async def test_a_failure_to_reach_github_is_a_502_with_a_neutral_reason(client, github, monkeypatch, exc, status, why):
    importer_raises(monkeypatch, exc)
    r = await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md"})
    assert r.status_code == status
    assert r.json()["detail"] == f"GitHub did not answer: {why}"
    async with client.db_maker() as db:
        assert (await db.execute(select(ApprovalEvent))).scalars().all() == []


async def test_a_refusal_is_a_400_with_its_message(client, github, monkeypatch):
    importer_raises(monkeypatch, ValueError("a skill named 'handoff' already exists"))
    r = await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md"})
    assert (r.status_code, r.json()["detail"]) == (400, "a skill named 'handoff' already exists")


async def test_a_disk_that_cannot_be_written_is_a_500_with_the_code_disk_and_a_plain_message(client, github, monkeypatch):
    """500, not 507: the OSError may be a full disk, a folder it may not write, a read-only volume or a
    failing drive; only the first is "insufficient storage". The code says it is the disk, the message
    is the system's own words for it."""
    def full(archive, folder):
        raise OSError(errno.ENOSPC, "No space left on device", "/Users/x/Library/Application Support/Arslan/skills/handoff")
    monkeypatch.setattr(skill_files, "stage", full)
    r = await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md", "license_ok": skill_import.license_sha256(GPL)})
    assert r.status_code == 500
    assert r.json()["detail"] == {"code": "disk", "message": "could not write the skill's folder: No space left on device"}
    assert "/Users/" not in r.text                                                  # no path in the message
    async with client.db_maker() as db:
        assert await db.get(SkillPack, "handoff") is None
        assert (await db.execute(select(ApprovalEvent))).scalars().all() == []


async def test_an_oserror_with_no_text_is_still_a_disk_answer(client, github, monkeypatch):
    importer_raises(monkeypatch, PermissionError())
    r = await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md"})
    assert r.status_code == 500 and r.json()["detail"] == {
        "code": "disk", "message": "could not write the skill's folder: PermissionError"}


async def test_the_real_downloads_failures_reach_the_api_as_502_not_a_crash(client, github, monkeypatch):
    """The importer's own network failures, raised by its own `_download` over a transport: an HTTP
    error status, a stalled body (its own deadline: an httpx.ReadTimeout) and a transport's own
    TimeoutError."""
    import asyncio
    transports = {}

    async def fetch_archive(owner, repo, ref):
        return await skill_import._download(owner, repo, ref, transport=transports["now"])
    monkeypatch.setattr(skill_import, "_fetch_archive", fetch_archive)
    monkeypatch.setattr(skill_import, "_ARCHIVE_STALL_S", 0.1)

    class Stalled(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(5)
            yield b"x"

    def timing_out(request):
        raise TimeoutError("the proxy gave up")
    answers = {
        "status": (lambda request: httpx.Response(503), "GitHub did not answer: it answered 503"),
        "stall": (lambda request: httpx.Response(200, stream=Stalled()),
                  "GitHub did not answer: the download stopped: no new bytes for 0.1 seconds"),
        "timeout": (timing_out, "GitHub did not answer: the request timed out"),
    }
    for handler, detail in answers.values():
        transports["now"] = httpx.MockTransport(handler)
        skill_import._archive_cache.clear()
        r = await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md"})
        assert (r.status_code, r.json()["detail"]) == (502, detail)


async def test_an_archive_that_is_not_one_is_a_400(client, github, monkeypatch):
    async def garbage(owner, repo, ref):
        return b"this is not a tar.gz at all"
    monkeypatch.setattr(skill_import, "_fetch_archive", garbage)
    r = await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md"})
    assert r.status_code == 400 and "not a readable archive" in r.json()["detail"]


# ── carry: license_ok comes from a person, and from no one else ──────────────

def test_install_skill_takes_a_license_ok_as_a_keyword_only_default_none():
    ok = inspect.signature(capability_flow.install_skill).parameters["license_ok"]
    assert ok.kind is inspect.Parameter.KEYWORD_ONLY and ok.default is None


async def test_install_skill_hands_a_persons_license_ok_to_the_importer_and_nothing_else_does(monkeypatch):
    seen = []

    async def importer(ref, path, **kwargs):
        seen.append(kwargs)
        raise ValueError("stop here")
    monkeypatch.setattr(skill_import, "import_skill", importer)
    cand = {"id": "library:example-org/example-skills:SKILL.md", "kind": "skill", "name": "handoff", "source": "library",
            "repo": REF, "path": "SKILL.md", "version": COMMIT[:12]}
    await capability_flow.install_skill(cand, license_ok="a" * 64)
    await capability_flow.install_skill(cand)
    assert seen[0] == {"license_ok": "a" * 64} and not seen[1].get("license_ok")


async def test_the_api_hands_the_bodys_license_ok_to_the_importer(client, github, monkeypatch):
    seen = []

    async def importer(ref, path, **kwargs):
        seen.append((ref, path, kwargs))
        raise ValueError("stop here")
    monkeypatch.setattr(skill_import, "import_skill", importer)
    await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md", "license_ok": "b" * 64})
    await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md"})
    assert seen == [(REF, "SKILL.md", {"license_ok": "b" * 64}), (REF, "SKILL.md", {"license_ok": None})]


def _candidate(**over):
    return {"id": "library:example-org/example-skills:SKILL.md", "kind": "skill", "name": "handoff", "summary": "Hand",
            "source": "library", "source_url": "https://github.com/example-org/example-skills", "repo": REF,
            "version": COMMIT[:12], "runtime": "skill", "package": None, "remote": None, "not_here": None,
            "path": "SKILL.md", "stars": None, "pushed_days": None, "needs": {"keys": [], "network": None},
            "license": {"spdx": "MIT", "read_from": "LICENSE", "verdict": "usable"}, **over}


async def test_neither_the_card_nor_the_dossier_install_offers_the_importer_a_license_ok(client, github, monkeypatch):
    """The model's arguments, the search result's own fields (a repository's data) and the install
    request's keys all carry a `license_ok` here: none of them reaches the importer."""
    from server.services import capability_dossier, capability_search
    seen = []

    async def importer(ref, path, **kwargs):
        seen.append(kwargs)
        raise ValueError("stop here")
    monkeypatch.setattr(skill_import, "import_skill", importer)
    cand = _candidate(license_ok="c" * 64, license_sha256="c" * 64)
    capability_search.remember("conv-card", {"candidates": [cand]})
    capability_search.remember(capability_dossier.PAGE, {"candidates": [cand]})

    async def ask(card):
        return {"approved": True, "call_id": "cap-1", "keys": {"license_ok": "d" * 64}, "folders": [],
                "license_ok": "d" * 64}
    await capability_flow.propose({"candidate_id": cand["id"], "why": "x", "license_ok": "e" * 64},
                                  conversation_id="conv-card", ask=ask, emit=lambda frame: None)
    await capability_dossier.install(cand["id"], folders=[], keys={"license_ok": "f" * 64})
    assert len(seen) == 2 and all(not kw.get("license_ok") for kw in seen)


async def test_a_license_ok_in_what_the_model_sends_does_not_install_an_unrecognised_license(client, github):
    """The fixture's repository is under a license Arslan does not recognise, and the card is approved.
    The model's tool arguments carry the right sha256 (and under several spellings): the skill is still
    not added, because only a person's click on the license step passes `license_ok`."""
    from server.services import capability_search
    cand = _candidate()
    capability_search.remember("conv-model", {"candidates": [cand]})
    sha = skill_import.license_sha256(GPL)

    async def ask(card):
        return {"approved": True, "call_id": "cap-1", "keys": {}, "folders": []}
    out = await capability_flow.propose(
        {"candidate_id": cand["id"], "why": "x", "license_ok": sha, "licenseOk": sha, "accept_license": sha,
         "license": {"ok": sha}}, conversation_id="conv-model", ask=ask, emit=lambda frame: None)
    assert out["ok"] is False and "license" in out["error"]
    async with client.db_maker() as db:
        assert await db.get(SkillPack, "handoff") is None
        assert (await db.execute(select(ApprovalEvent))).scalars().all() == []


def test_no_tool_the_model_is_given_offers_a_license_ok():
    from server.orchestrator import tool_loop
    from server.registry import seed_catalog
    from server.registry.executors import EXECUTORS
    tools = [{"key": key, "description": ""} for key in sorted(set(EXECUTORS) | set(tool_loop._NATIVE_PARAM_SCHEMAS))]
    schemas = tool_loop._native_tool_schemas(tools, allow_escalation=True)
    assert len(schemas) > 30 and "propose_capability" in {s["function"]["name"] for s in schemas}
    wire = json.dumps([schemas, tool_loop._NATIVE_PARAM_SCHEMAS, tool_loop._ESCALATE_SCHEMA, seed_catalog.TOOLSETS],
                      default=str).lower().replace("-", "_")
    assert "license_ok" not in wire and "licenseok" not in wire.replace("_", "")
    root = pathlib.Path(inspect.getfile(tool_loop)).parents[1]               # server/
    for folder in ("registry", "orchestrator"):                              # nor is a tool's code a way to it
        for source in sorted((root / folder).rglob("*.py")):
            assert "license_ok" not in source.read_text(), f"{source.relative_to(root)} names license_ok"


# ═══ fix round 1 (review of 96623fd7) ════════════════════════════════════════

DECLINE = IMPORT + "/decline"
SHA = skill_import.license_sha256(GPL)


# m1 — the scan answers a transport's own TimeoutError as the import does: 502, not an unhandled 500.
async def test_the_scan_maps_a_transports_timeout_as_the_import_does(client, github, monkeypatch):
    def timing_out(request):
        raise TimeoutError("the proxy gave up")

    async def fetch_archive(owner, repo, ref):
        return await skill_import._download(owner, repo, ref, transport=httpx.MockTransport(timing_out))
    monkeypatch.setattr(skill_import, "_fetch_archive", fetch_archive)
    r = await client.post("/api/v1/discovery/skills/scan", json={"ref": REF})
    assert (r.status_code, r.json()["detail"]) == (502, "GitHub did not answer: the request timed out")


# m2 — the 409 names the skill's key and its name, each in its place.
async def test_the_409_carries_the_key_and_the_name_each_in_its_place(client, github, monkeypatch):
    serves(monkeypatch, {"SKILL.md": "---\nname: Hand Off Work\ndescription: Hand work over.\n---\n# Handoff\nSteps.\n",
                         "LICENSE": GPL})
    r = await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md"})
    assert r.status_code == 409
    assert (r.json()["detail"]["key"], r.json()["detail"]["name"]) == ("hand-off-work", "Hand Off Work")


# m3 — "No" on the license step is a decision too (§A8): one deny row, nothing imported.
async def test_declining_the_license_step_writes_one_deny_row_and_imports_nothing(client, github, monkeypatch):
    calls = []

    async def spy(*args, **kwargs):
        calls.append(args)
        raise AssertionError("a decline reads nothing from GitHub")
    for name in ("import_skill", "scan_skills", "_fetch_archive"):
        monkeypatch.setattr(skill_import, name, spy)
    monkeypatch.setattr(skill_import.github_eval, "fetch_repo", spy)
    r = await client.post(DECLINE, json={"ref": f"{REF}@{COMMIT}", "path": "SKILL.md", "license_sha256": SHA.upper()})
    assert r.status_code == 200 and r.json() == {"declined": True} and calls == []
    async with client.db_maker() as db:
        [event] = (await db.execute(select(ApprovalEvent))).scalars().all()
        assert await db.get(SkillPack, "handoff") is None
        assert not permission_store.could_not_ask(event)                       # a person's no, not a refusal for want of a surface
    assert (event.kind, event.decided_by, event.decision, event.scope, event.mode, event.conversation_id) == (
        "capability", "user", "deny", None, "standard", None)
    assert event.target == "skill:example-org/example-skills/SKILL.md"
    assert event.detail == f"example-org/example-skills@{COMMIT[:12]} SKILL.md"
    assert event.extra == {"license_sha256": SHA}                                # the text that was read, lower-cased
    assert (await client.get("/api/v1/approvals/refused")).json() == []


async def test_a_decline_that_is_not_one_writes_no_row(client, github):
    bodies = [
        ({"ref": REF, "path": "SKILL.md"}, 422),                                           # no sha
        ({"ref": REF, "path": "SKILL.md", "license_sha256": "abc"}, 422),
        ({"ref": REF, "path": "SKILL.md", "license_sha256": "g" * 64}, 422),
        ({"ref": REF, "path": "SKILL.md", "license_sha256": SHA + "0"}, 422),
        ({"ref": REF, "path": "SKILL.md", "license_sha256": 5}, 422),
        ({"ref": REF, "license_sha256": SHA}, 422),                                         # no path
        ({"path": "SKILL.md", "license_sha256": SHA}, 422),                                 # no ref
        ({"ref": "not a repository", "path": "SKILL.md", "license_sha256": SHA}, 400),
        ({"ref": REF, "path": "../SKILL.md", "license_sha256": SHA}, 400),
        ({"ref": REF, "path": "README.md", "license_sha256": SHA}, 400),
    ]
    for body, status in bodies:
        r = await client.post(DECLINE, json=body)
        assert r.status_code == status, (body, r.status_code, r.text)
    async with client.db_maker() as db:
        assert (await db.execute(select(ApprovalEvent))).scalars().all() == []


# m5 — once the import is done, its row is written even if the request is cancelled meanwhile.
async def test_a_cancel_after_the_import_still_writes_its_row(client, github, monkeypatch):
    from server.api import discovery
    from server.services import skill_ledger
    real, gate, started = skill_ledger.record, asyncio.Event(), asyncio.Event()

    async def held(**kw):
        started.set()
        await gate.wait()
        await real(**kw)
    monkeypatch.setattr(skill_ledger, "record", held)
    task = asyncio.ensure_future(discovery.import_skill(discovery.SkillImportBody(ref=REF, path="SKILL.md",
                                                                                  license_ok=SHA)))
    await asyncio.wait_for(started.wait(), 10)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    gate.set()
    for _ in range(50):
        await asyncio.sleep(0.02)
        async with client.db_maker() as db:
            rows = (await db.execute(select(ApprovalEvent))).scalars().all()
        if rows:
            break
    async with client.db_maker() as db:
        assert await db.get(SkillPack, "handoff") is not None
    assert [(e.target, e.decision) for e in rows] == [("skill:handoff", "allow")]


# m6 — GitHub's metadata that is not a JSON object is a refusal, not an unhandled 500.
async def test_repository_metadata_that_is_not_an_object_is_a_400(client, github, monkeypatch):
    async def no_token():
        return ""
    monkeypatch.setattr(github_eval, "_token", no_token)
    monkeypatch.setattr(skill_import.github_eval, "fetch_repo", REAL_FETCH_REPO)
    for payload in (["not", "an", "object"], "MIT", None, {"full_name": "a/b", "license": "MIT"},
                    {"full_name": "a/b", "license": ["MIT"]}):
        async def odd(client_, url, headers, payload=payload):
            return httpx.Response(200, content=json.dumps(payload).encode(), request=httpx.Request("GET", url))
        monkeypatch.setattr(github_eval, "_get_following_on_api", odd)
        r = await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md"})
        if isinstance(payload, dict):                       # a repository whose license is no object has no license
            assert r.status_code == 409, (payload, r.status_code)
        else:
            assert r.status_code == 400 and "not a repository" in r.json()["detail"], (payload, r.status_code)


# m7 — the ledger row names the source as it is, never as typed, and keeps the text that was accepted.
async def test_the_ledger_row_names_the_canonical_source_and_the_accepted_text(client, github, monkeypatch):
    ref = "https://github.com/example-org/example-skills?token=ghp_not_a_real_token#frag"
    r = await client.post(IMPORT, json={"ref": ref, "path": "/SKILL.md", "license_ok": SHA})
    assert r.status_code == 200 and r.json()["license_sha256"] == SHA
    again = await client.post(IMPORT, json={"ref": f"{REF}@{COMMIT}", "path": "SKILL.md"})          # an update: accepted before
    assert again.status_code == 200 and again.json()["update"] is True
    async with client.db_maker() as db:
        first, second = (await db.execute(select(ApprovalEvent).order_by(ApprovalEvent.id))).scalars().all()
    assert first.detail == f"example-org/example-skills@{COMMIT[:12]} SKILL.md"
    assert second.detail == first.detail
    assert "ghp_" not in first.detail and "token" not in repr(first.extra) and "?" not in first.detail
    assert first.extra["license_sha256"] == SHA and second.extra["license_sha256"] == SHA
    assert (first.extra["local_only"], first.extra["update"], second.extra["update"]) == (True, False, True)


async def test_a_recognised_license_leaves_no_accepted_text_in_the_row(client, github, monkeypatch):
    serves(monkeypatch, {"SKILL.md": MD, "LICENSE": "MIT License\n\nPermission is hereby granted, free of charge, "
                                                     "to any person obtaining a copy\n"})
    r = await client.post(IMPORT, json={"ref": REF, "path": "SKILL.md"})
    assert r.status_code == 200 and r.json()["license_sha256"] is None
    async with client.db_maker() as db:
        [event] = (await db.execute(select(ApprovalEvent))).scalars().all()
    assert "license_sha256" not in event.extra


# m8 — a license over the limit says so in its view, so the scan can tell it from an unrecognised one.
def test_a_license_over_the_limit_says_so_in_its_view():
    over = skill_import.SkillLicense(None, False, "LICENSE", "", skill_import.license_sha256(""), too_long=True)
    assert over.view(with_text=True)["too_long"] is True and over.view(with_text=False)["too_long"] is True
    plain = skill_import.SkillLicense(None, False, "LICENSE", GPL, SHA)
    assert "too_long" not in plain.view(with_text=True) and "too_long" not in plain.view(with_text=False)


async def test_the_scan_says_a_license_is_too_long_to_show(client, github, monkeypatch):
    serves(monkeypatch, {"SKILL.md": MD, "LICENSE": "x" * (skill_import.MAX_LICENSE_BYTES + 1)})
    [skill] = (await client.post("/api/v1/discovery/skills/scan", json={"ref": REF})).json()["skills"]
    assert skill["license"]["too_long"] is True and skill["license"]["recognised"] is False
    assert skill["license"]["text"] == ""


# N3 — the card's disk message is the system's words for it, never an error's own text (which can be a path).
async def test_the_cards_disk_message_never_carries_a_path(monkeypatch):
    cand = _candidate()
    importer_raises(monkeypatch, OSError(errno.ENOSPC, "No space left on device", "/Users/x/Arslan/skills/handoff"))
    out = await capability_flow.install_skill(cand)
    assert out["code"] == "disk" and out["detail"] == "could not write the skill's folder: No space left on device"
    importer_raises(monkeypatch, OSError("cannot write /Users/x/Arslan/skills/handoff"))
    out = await capability_flow.install_skill(cand)
    assert out["code"] == "disk" and out["detail"] == "could not write the skill's folder: OSError"


# m4 on the card path — a stale answer is still the user's step, and it says why.
async def test_a_stale_answer_through_install_skill_says_the_text_changed(monkeypatch):
    lic = skill_import.SkillLicense(None, False, "LICENSE", GPL, SHA)
    cand = _candidate()
    importer_raises(monkeypatch, skill_import.LicenseStepNeeded(lic, key="handoff", name="handoff", stale=True))
    stale = await capability_flow.install_skill(cand, license_ok="0" * 64)
    importer_raises(monkeypatch, skill_import.LicenseStepNeeded(lic, key="handoff", name="handoff"))
    undecided = await capability_flow.install_skill(cand)
    assert stale["code"] == undecided["code"] == "license_step"
    assert "changed" in stale["detail"] and "changed" not in undecided["detail"]
    assert "not one Arslan recognises" in undecided["detail"]

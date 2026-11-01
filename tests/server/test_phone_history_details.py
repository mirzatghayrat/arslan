"""IPB (v0.1.64): `chat.history.result.details` for iPhone 1.0's part B (docs/plans/0164/IPB-frame-list.md §3):
one conversation as the Mac runs it. The Mac sums what changed over every run (the phone sees at most 40
steps of a run and 200 messages), prices what it spent, and keeps `details` inside the one envelope."""
from datetime import datetime

import pytest

from server.db.models import ArslanMessage, Run, RunStep, UsageLedger
from server.services import phone_details, phone_reads, tool_review

PRICED = "claude-sonnet-5-5"            # $2 per million in, $10 per million out (arslan/llm/prices.py)
CID = "chat-details"

_ids = iter(range(1, 100_000))


def run(conversation=CID, *, kind="live", tokens=(None, None), estimated=False) -> Run:
    tin, tout = tokens
    now = datetime.utcnow()
    return Run(id=next(_ids), conversation_id=conversation, user_message="x", started_at=now, created_at=now,
               status="recorded", kind=kind, model=PRICED, tokens_in=tin, tokens_out=tout, tokens_estimated=estimated,
               task_tokens=(tin or 0) + (tout or 0) or 10)


def step(run_row: Run, seq: int, tool: str, review: dict | None, ok=True) -> RunStep:
    return RunStep(run_id=run_row.id, seq=seq, kind="tool_call", ref={"tool": tool, "ok": ok},
                   detail={"review": review} if review else {})


def edit(path: str, old: str, new: str) -> dict:
    return {"kind": "edit", "path": path, "old": old, "new": new}


async def _add(client, rows):
    async with client.db_maker() as db:
        for row in rows:
            db.add(row)
            await db.flush()
        await db.commit()


async def _details(client, conversation=CID) -> dict:
    async with client.db_maker() as db:
        return await phone_details.details(db, conversation)


# ------------------------------------------------------------------ what changed

async def test_changes_are_summed_over_every_run_of_the_conversation(client):
    first, second, other, replay = run(), run(), run("chat-other"), run(kind="replay")
    rows = [first, second, other, replay]
    # 45 edits in one run: more than the 40 steps a run.result carries.
    rows += [step(first, k, "edit_file", edit("a.py", f"x = {k}", f"x = {k}\ny = {k}")) for k in range(45)]
    rows += [step(second, 0, "edit_file", edit("b.py", "one\ntwo\nthree", "one")),            # 2 removed
             step(second, 1, "write_file", {"kind": "write", "path": "c.md", "lines": 120, "head": "# C\n…"}),
             step(second, 2, "write_file", {"kind": "write", "path": "d.md", "head": "1\n2\n3"}),  # recorded before `lines`
             step(second, 3, "edit_file", edit("e.py", "a", "b"), ok=False),                  # failed: nothing changed
             step(second, 4, "run_command", {"kind": "command", "command": "sed -i s/a/b/ f.py"}),  # a shell change: not counted
             step(other, 0, "edit_file", edit("z.py", "", "1\n2")),
             step(replay, 0, "edit_file", edit("r.py", "", "1\n2"))]
    await _add(client, rows)
    changes = (await _details(client))["changes"]
    assert changes == {"files": 4, "added": 45 + 120 + 3, "removed": 2, "last_run_id": second.id}


async def test_a_conversation_that_changed_nothing_has_no_changes(client):
    quiet = run()
    await _add(client, [quiet, step(quiet, 0, "read_file", {"kind": "read", "path": "a.py"})])
    assert "changes" not in await _details(client)


def test_a_written_file_records_how_many_lines_it_has():
    content = "".join(f"line {k}\n" for k in range(500))          # far past the recorded head
    review = tool_review.capture("write_file", {"path": "big.txt", "content": content}, {"ok": True, "path": "big.txt"})
    assert review["lines"] == 500
    assert tool_review.capture("write_file", {"path": "n.txt", "content": "a\nb"}, {"ok": True})["lines"] == 2
    assert tool_review.capture("write_file", {"path": "e.txt", "content": ""}, {"ok": True})["lines"] == 0


# ------------------------------------------------------------------ what it spent

async def test_the_conversation_cost_is_its_runs_and_its_ledger_rows(client):
    rows = [run(tokens=(1_000_000, 0)), run(tokens=(0, 100_000)), run("chat-other", tokens=(1_000_000, 0)),
            UsageLedger(scope="titler", conversation_id=CID, model=PRICED, tokens_in=250_000, tokens_out=0,
                        tokens_total=250_000)]
    await _add(client, rows)
    assert (await _details(client))["spent_usd"] == 3.5


async def test_nothing_priced_means_no_spent_usd(client):
    await _add(client, [run(tokens=(10, 10), estimated=True)])
    assert "spent_usd" not in await _details(client)


# ------------------------------------------------------------------ in the one envelope

def test_the_trim_counts_details_first_and_fits_messages_into_what_is_left():
    messages = [{"id": str(k), "role": "user", "text": "x" * 1000, "ts": "2026-10-03T00:00:00Z", "attachments": []}
                for k in range(600)]
    details = {"connectors": [{"name": "n" * 900, "kind": "mcp", "on": True}] * 30}
    plain, _ = phone_reads.fit_history(CID, messages)
    fitted, truncated = phone_reads.fit_history(CID, messages, details)
    assert truncated and len(fitted) < len(plain)
    body = {"conversation_id": CID, "messages": fitted, "details": details}
    assert phone_reads._json_size(body) <= phone_reads.HISTORY_BUDGET
    assert phone_reads._json_size({**body, "messages": messages[-len(fitted) - 1:]}) > phone_reads.HISTORY_BUDGET


async def test_the_history_result_carries_details(client):
    changed = run(tokens=(1_000_000, 0))
    await _add(client, [changed, step(changed, 0, "edit_file", edit("a.py", "", "1")),
                        ArslanMessage(conversation_id=CID, role="user", content="hi")])
    got = (await client.get(f"/api/v1/phone/conversations/{CID}/history")).json()
    assert got["details"]["changes"]["files"] == 1 and got["details"]["spent_usd"] == 2.0
    assert isinstance(got["details"]["connectors"], list), "required by the phone's decoder, [] when none"


@pytest.mark.parametrize("cid", ["chat-unknown"])
async def test_an_empty_conversation_still_has_the_required_connectors(client, cid):
    assert (await _details(client, cid))["connectors"] is not None


# ------------------------------------------------------------------ where it runs: the folder, the model, the mode

def test_the_folder_shows_the_home_part_as_a_tilde(tmp_path):
    home = tmp_path / "Home"
    (home / "Projects" / "Trip").mkdir(parents=True)
    (tmp_path / "alias").symlink_to(home)
    outside = tmp_path / "Volume" / "work"
    outside.mkdir(parents=True)
    shown = phone_details.shown_folder
    assert shown(home / "Projects" / "Trip", home) == "~/Projects/Trip"
    assert shown(tmp_path / "alias" / "Projects" / "Trip", home) == "~/Projects/Trip", "a home reached by a link"
    assert shown(home / "Projects" / "Trip", tmp_path / "alias") == "~/Projects/Trip", "a home that is a link"
    swapped = str(home).swapcase() + "/Projects/Trip"                 # the same folder on a case-insensitive volume
    assert shown(swapped, home) == "~/Projects/Trip"
    assert shown(home, home) == "~"
    assert shown(outside, home) == "work", "outside the home, only its last part (the user, 2026-11-01)"
    assert shown(tmp_path / "Home2", home) == "Home2", "a sibling is not inside the home"


async def test_the_details_never_carry_the_absolute_home_path(client, tmp_path, monkeypatch):
    home = tmp_path / "Home"
    (home / "Arslan").mkdir(parents=True)
    (home / "Code" / "trip").mkdir(parents=True)
    monkeypatch.setattr(phone_details, "_home", lambda: home)
    from server.db.companion_models import ConversationContext, Project
    from server.db.models import Setting
    await _add(client, [Setting(key="workspace_dir", value=str(home / "Arslan")),
                        Project(id="p1", name="Trip", workspace_ref=str(home / "Code" / "trip")),
                        ConversationContext(id="in-project", project_id="p1")])
    import json
    plain, in_project = await _details(client), await _details(client, "in-project")
    assert (plain["folder"], in_project["folder"]) == ("~/Arslan", "~/Code/trip")
    for got in (plain, in_project):
        assert str(home) not in json.dumps(got) and str(home.resolve()) not in json.dumps(got)


async def test_the_model_is_the_conversations_choice_else_the_primary_configs(client):
    from server.db.models import ConversationModel, ProviderConfig
    await _add(client, [ProviderConfig(id=1, label="Work", provider="anthropic", model="claude-opus-5-5", api_key="x"),
                        ProviderConfig(id=2, label="Home", provider="anthropic", model="claude-sonnet-5-5", api_key="x",
                                       is_primary=True),
                        ConversationModel(conversation_id="picked", config_id=1, model="claude-haiku-5-5")])
    assert (await _details(client, "picked"))["model"] == "claude-haiku-5-5"
    assert (await _details(client))["model"] == "claude-sonnet-5-5", "no choice: the primary config's model"
    await _add(client, [ConversationModel(conversation_id="orphan", config_id=99, model="gone-model")])
    assert (await _details(client, "orphan"))["model"] == "claude-sonnet-5-5", "a choice whose config is gone is the default"


async def test_no_model_configured_means_no_model(client):
    assert "model" not in await _details(client)


@pytest.mark.parametrize("policy, mode", [(None, "careful"), ("ask_all", "careful"), ("ask_risky", "standard")])
async def test_the_mode_is_the_approval_mode_in_effect(client, policy, mode):
    from server.db.models import Setting
    if policy:
        await _add(client, [Setting(key="shell_confirm_policy", value=policy)])
    assert (await _details(client))["mode"] == mode


# ------------------------------------------------------------------ its connectors

@pytest.fixture
def mcp_ready(monkeypatch):
    ready: set[int] = set()
    from server.mcp import supervisor
    monkeypatch.setattr(supervisor, "ready_now", lambda server_id, state: server_id in ready and state == "ready")
    return ready


def mcp(server_id: int, label: str, *, allowed=True, state="ready", url=None, args=()):
    from server.db.models import MCPServer
    return MCPServer(id=server_id, label=label, transport="http" if url else "stdio", command="" if url else "npx",
                     args=list(args), url=url, host_allowed=allowed, state=state)


async def test_connectors_are_named_by_display_name_only_and_on_for_this_conversations_turns(client, mcp_ready, monkeypatch):
    from server.registry import hands_tools
    from server.services import hands_client
    monkeypatch.setattr(hands_client, "available", lambda: True)
    monkeypatch.setattr(hands_tools, "desktop_available", lambda: True)
    mcp_ready.update({1, 2})
    await _add(client, [mcp(1, "Calendar", url="https://mcp.example.dev/sse?token=urltokenaaaa"),
                        mcp(2, "Files", args=["-y", "files-server", "--token=argtokenaaaa"]),
                        mcp(3, "Mail", state="starting"),                       # switched on, not connected
                        mcp(4, "Notes", allowed=False, state="off")])            # switched off
    import json
    connectors = (await _details(client))["connectors"]
    assert connectors[0] == {"name": "Hands", "kind": "hands", "on": True}, "Hands first"
    by = {c["name"]: c for c in connectors if c["kind"] == "mcp"}
    assert {name: c["on"] for name, c in by.items()} == {"Calendar": True, "Files": True, "Mail": False, "Notes": False}
    text = json.dumps(connectors)
    for secret in ("urltokenaaaa", "argtokenaaaa", "mcp.example.dev", "files-server", "npx"):
        assert secret not in text
    ons = [c["on"] for c in connectors]
    assert ons == sorted(ons, reverse=True), "the ones that are on before the ones that are off"
    assert len(connectors) <= phone_details.CONNECTORS_MAX == 30
    assert {c["kind"] for c in connectors} == {"hands", "mcp", "skill"}


async def test_at_most_thirty_connectors_hands_first_then_the_ones_that_are_on(client, mcp_ready, monkeypatch):
    from server.registry import hands_tools
    from server.services import hands_client
    monkeypatch.setattr(hands_client, "available", lambda: True)
    monkeypatch.setattr(hands_tools, "desktop_available", lambda: False)        # installed, switched off
    mcp_ready.update(range(1, 41))
    await _add(client, [mcp(k, f"Server {k:02d}", state="ready" if k <= 40 else "off") for k in range(1, 46)])
    connectors = (await _details(client))["connectors"]
    assert len(connectors) == 30
    assert connectors[0] == {"name": "Hands", "kind": "hands", "on": False}, "Hands first, even when off"
    assert all(c["on"] for c in connectors[1:]), "29 that are on fill the rest"


async def test_without_hands_on_this_mac_it_is_not_listed(client, monkeypatch):
    from server.services import hands_client
    monkeypatch.setattr(hands_client, "available", lambda: False)
    assert all(c["kind"] != "hands" for c in (await _details(client))["connectors"])


async def test_a_quick_question_has_no_connector_on(client, mcp_ready, monkeypatch):
    from server.registry import hands_tools
    from server.services import hands_client
    monkeypatch.setattr(hands_client, "available", lambda: True)
    monkeypatch.setattr(hands_tools, "desktop_available", lambda: True)
    mcp_ready.add(1)
    from server.db.companion_models import ConversationContext
    await _add(client, [mcp(1, "Calendar"), ConversationContext(id="quick-1", kind="quick")])
    connectors = (await _details(client, "quick-1"))["connectors"]
    assert connectors and not any(c["on"] for c in connectors), "a quick question gets four read-only tools only"


# ------------------------------------------------------------------ the shared vectors

def _vector_details() -> list[dict]:
    import json
    from pathlib import Path
    examples = json.loads((Path(__file__).resolve().parents[2] / "spec/mobile-bridge/vectors/messages.json").read_text())["examples"]
    return [e["envelope"]["body"]["details"] for e in examples
            if e["envelope"]["type"] == "chat.history.result" and "details" in e["envelope"]["body"]]


async def test_the_details_have_the_vectors_shape(client, mcp_ready, monkeypatch):
    from server.db.models import ProviderConfig
    from server.services import hands_client
    monkeypatch.setattr(hands_client, "available", lambda: True)
    changed = run(tokens=(1_000_000, 0))
    await _add(client, [changed, step(changed, 0, "edit_file", edit("a.py", "", "1")), mcp(1, "Calendar"),
                        ProviderConfig(label="Home", provider="anthropic", model=PRICED, api_key="x", is_primary=True)])
    got, full = await _details(client), _vector_details()[0]
    assert set(got) == set(full), "every field the Mac knows, context left out in v1"
    assert "context" not in got
    assert set(got["changes"]) == set(full["changes"])
    assert {tuple(sorted(c)) for c in got["connectors"]} == {tuple(sorted(c)) for c in full["connectors"]} == {("kind", "name", "on")}
    assert {c["kind"] for c in got["connectors"]} <= {"mcp", "skill", "hands"}


# ------------------------------------------------------------------ #650's effort=max review

import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import unicodedata  # noqa: E402

mac_only = pytest.mark.skipif(sys.platform != "darwin" or not os.path.isdir("/System/Volumes/Data"),
                              reason="APFS firmlinks and normalization-insensitive names")


@mac_only
def test_a_home_reached_through_the_data_volume_firmlink_is_a_tilde(tmp_path):
    home = (tmp_path / "Home").resolve()
    (home / "Code").mkdir(parents=True)
    assert phone_details.shown_folder("/System/Volumes/Data" + str(home / "Code"), home) == "~/Code"


@mac_only
def test_a_home_written_in_another_unicode_form_is_a_tilde(tmp_path):
    nfc = unicodedata.normalize("NFC", "Jos" + chr(0xE9))
    (tmp_path / nfc / "Code").mkdir(parents=True)
    folder = tmp_path / unicodedata.normalize("NFD", nfc) / "Code"
    assert phone_details.shown_folder(folder, tmp_path / nfc) == "~/Code"


async def test_a_model_id_that_is_a_path_is_sent_as_its_file_name(client, tmp_path, monkeypatch):
    from server.db.models import ConversationModel, ProviderConfig
    home = tmp_path / "Home"
    monkeypatch.setattr(phone_details, "_home", lambda: home)
    gguf = str(home / "models" / "qwen3-8b.Q4_K_M.gguf")           # llama.cpp without --alias names a model by its file
    await _add(client, [ProviderConfig(id=1, label="Local", provider="custom", model="local", api_key="x", is_primary=True),
                        ConversationModel(conversation_id="local", config_id=1, model=gguf),
                        ConversationModel(conversation_id="tilde", config_id=1, model="~/models/a.gguf"),
                        ConversationModel(conversation_id="huge", config_id=1, model="m" * 600_000)])
    got = await _details(client, "local")
    assert got["model"] == "qwen3-8b.Q4_K_M.gguf" and str(home) not in json.dumps(got)
    assert (await _details(client, "tilde"))["model"] == "a.gguf"
    huge = await _details(client, "huge")
    assert len(huge["model"]) <= 200, "an unbounded id would make every history too large to send"
    fitted, _ = phone_reads.fit_history("huge", [{"id": "1", "role": "user", "text": "hi", "ts": "t", "attachments": []}], huge)
    assert fitted


async def test_a_connector_name_is_its_label_with_secrets_and_the_home_path_masked(client, mcp_ready, monkeypatch, tmp_path):
    from server import crypto
    monkeypatch.setenv("ARSLAN_ALLOW_INSECURE_SECRETS", "1")
    home = "/Users/probeuser"
    monkeypatch.setattr(phone_details, "_home", lambda: home)
    mcp_ready.update({1, 2, 3, 4, 5, 6})
    labels = {1: "https://mcp.example.dev/sse?token=sklivetokenvalueabc",
              2: "files --token flagtokenaaaa",
              3: f"{home}/mcp/server.py",
              4: "日历",
              5: "Files envsecretvalue1234",
              6: f"日历{home}/cal"}                                 # a home path right against Chinese text
    rows = [mcp(k, v) for k, v in labels.items()]
    rows[4].env = crypto.encrypt(json.dumps({"API_KEY": "envsecretvalue1234"}))
    await _add(client, rows)
    names = {c["name"] for c in (await _details(client))["connectors"] if c["kind"] == "mcp"}
    text = json.dumps(sorted(names), ensure_ascii=False)
    for secret in ("sklivetokenvalueabc", "flagtokenaaaa", "envsecretvalue1234", home):
        assert secret not in text, secret
    assert "~/mcp/server.py" in names and "日历" in names, "the label is the display name, in any script"
    assert "日历~/cal" in names
    assert all(len(name) <= 80 for name in names)


async def test_the_newest_changing_run_wins_whatever_order_the_rows_come_in(client):
    older, newer = run(), run()
    await _add(client, [older, newer, step(newer, 0, "edit_file", edit("b.py", "", "1")),
                        step(older, 0, "edit_file", edit("a.py", "", "1"))])
    assert (await _details(client))["changes"]["last_run_id"] == newer.id


def test_an_edit_records_its_line_counts_from_the_whole_text():
    old = "".join(f"line {k}\n" for k in range(2000))
    new = old.replace("line 5\n", "line five\nline 5b\n")
    review = tool_review.capture("edit_file", {"path": "a.py", "old_string": old, "new_string": new}, {"ok": True})
    assert (review["added"], review["removed"]) == (2, 1), "counted on the whole edit, not the recorded snippet"


async def test_recorded_counts_are_summed_without_diffing_again(client, monkeypatch):
    changed = run()
    await _add(client, [changed, step(changed, 0, "edit_file", {"kind": "edit", "path": "a.py", "old": "x", "new": "y",
                                                                 "added": 7, "removed": 3}),
                        step(changed, 1, "edit_file", edit("b.py", "a\nb", "a"))])           # recorded before the counts
    monkeypatch.setattr(phone_reads, "change_lines", lambda old, new: ([], 0, len(old.splitlines()) - len(new.splitlines())))
    assert (await _details(client))["changes"] == {"files": 2, "added": 7, "removed": 4, "last_run_id": changed.id}


def test_another_unicode_form_is_the_same_home_even_where_the_disk_cannot_tell():
    nfc = unicodedata.normalize("NFC", "Jos" + chr(0xE9))
    root = "/arslan-test-no-such-volume"                         # not on disk: only the names can say it
    assert phone_details.shown_folder(f"{root}/{unicodedata.normalize('NFD', nfc)}/Code", f"{root}/{nfc}") == "~/Code"


@pytest.mark.parametrize("folder, shown", [
    ("/Volumes/Work/proj", "proj"),
    ("/Users/Shared/x", "x"),
    ("/Volumes/Clone/Users/alice/p", "p"),              # a clone of the home on another disk is not the home
    ("/", "/"),
])
def test_a_folder_outside_the_home_is_only_its_last_part(folder, shown):
    """The user, 2026-11-01 (「#650 文件夹选 a」): no volume and no full path leave the Mac."""
    assert phone_details.shown_folder(folder, "/Users/alice") == shown

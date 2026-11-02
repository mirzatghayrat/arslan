"""SMART-8 (the card mock the user OK'd, 2026-11-02, its iPhone board included): a command card's server `title` is its
plain purpose in the user's language. The iPhone shows it as the approval's heading; the model reads it in refusal and
expiry texts. The user's card read "Run `echo "== 试探 192.168.1.4 =="; ssh … -o StrictH`? It will use the network, this
time." on the phone."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.db import session as db_session
from server.db.models import Setting
from server.orchestrator import tool_loop, untrusted
from server.services import approvals, card_purpose, command_confirm, command_sandbox, permissions

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "tests/fixtures/card_purpose_vectors.json").read_text(encoding="utf-8"))["vectors"]
SSH = ('echo "== 试探 192.168.1.4 =="; ssh -o BatchMode=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=accept-new '
       '192.168.1.4 true')
LANGS = ("en", "zh", "ja", "es", "de", "fr")


@pytest.mark.parametrize("vector", VECTORS, ids=[v["line"][:40] for v in VECTORS])
def test_the_server_reads_a_command_as_the_mac_card_does(vector):
    """Both readers are held to one set of vectors (web/src/lib/commandSummary.ts reads the same file)."""
    s = card_purpose.summarize(vector["line"], vector.get("rule"))
    assert s == {"purpose": vector["purpose"], "touches": vector["touches"], "more": vector["more"]}


def test_every_language_has_every_purpose_with_the_same_placeholders():
    import re
    holes = lambda text: sorted(re.findall(r"\{\{(\w+)\}\}", text))  # noqa: E731
    en = card_purpose.TEXT["en"]
    for lang in LANGS:
        for group in ("purpose", "suffix"):
            table = card_purpose.TEXT[lang][group]
            assert set(table) == set(en[group]), (lang, group)
            for k in table:                # a `_one` form may write the 1 itself, with no {{count}}
                drop = {"count"} if k.endswith("_one") else set()
                assert set(holes(table[k])) - drop == set(holes(en[group][k])) - drop, (lang, group, k)


def test_the_titles_strings_are_the_mac_cards_where_the_mac_card_has_them():
    """The Mac card's strings are runcmd.purpose in each locale file (SMART-8's component, #688). Where a locale has
    them, they are these: one card, one wording, on the Mac and on the phone."""
    for lang in LANGS:
        locale = json.loads((ROOT / f"web/src/locales/{lang}.json").read_text(encoding="utf-8"))
        mac = locale.get("runcmd", {}).get("purpose")
        if mac is not None:
            assert mac == card_purpose.TEXT[lang]["purpose"], lang


def test_the_users_card_reads_as_the_phone_board_draws_it():
    assert card_purpose.phrase(SSH, lang="zh") == "看看能不能用 SSH 连上 192.168.1.4（试连一次，最多 4 秒）"
    assert card_purpose.phrase(SSH, lang="en") == \
        "Check whether 192.168.1.4 can be reached over SSH (one try, at most 4 seconds)"


def test_arslans_reason_comes_first_cleaned():
    assert card_purpose.phrase(SSH, "See whether the NAS is up" + chr(0x202E), lang="en") == "See whether the NAS is up"


def test_a_reason_of_only_hidden_characters_is_no_reason():
    """Cleaned first, it is empty, so the heading is the command's reading, never blank."""
    assert card_purpose.phrase("git status", chr(0x200B) * 3 + chr(0x202E), lang="en") == "Run git status"


def test_the_commands_own_words_carry_no_hidden_characters_into_the_heading():
    title = card_purpose.phrase("ssh nas" + chr(0x200B) + ".local" + chr(0x2066), lang="en")
    assert title == "Connect to nas.local over SSH"


@pytest.mark.parametrize("lang, one, many", [
    ("en", "Delete 1 file or folder", "Delete 2 files or folders"), ("zh", "删除 1 个文件或文件夹", "删除 2 个文件或文件夹"),
    ("de", "1 Datei oder Ordner löschen", "2 Dateien oder Ordner löschen")])
def test_a_count_of_one_takes_the_one_form(lang, one, many):
    assert card_purpose.phrase("rm a", lang=lang) == one and card_purpose.phrase("rm a b", lang=lang) == many


def test_a_second_step_is_counted():
    assert card_purpose.phrase("rm old.zip && curl -O https://example.com/new.zip", lang="en") == \
        "Delete 1 file or folder (and 1 more step)"


@pytest.mark.parametrize("where, tail", [
    ({"outside": True}, " (outside the sandbox, this time)"), ({"host": "me@box"}, " (on me@box)"),
    ({"shortcut_as_you": True, "outside": True}, " (it runs as you, outside the sandbox; Arslan can't see what the Shortcut does)"),
    ({"network": True}, " (uses the network, this time)")])
def test_where_it_runs_follows_the_purpose(where, tail):
    assert card_purpose.phrase("git status", lang="en", **where) == "Run git status" + tail


def test_a_language_it_does_not_speak_is_english():
    assert card_purpose.phrase("git status", lang="xx") == "Run git status"


async def _language(value):
    async with db_session.AsyncSessionLocal() as db:
        db.add(Setting(key="language", value=value))
        await db.commit()


@pytest.mark.parametrize("stored, lang", [("zh", "zh"), ("Chinese (Simplified)", "zh"), ("pt-BR", "en")])
async def test_the_language_is_the_users_setting(execution_db, stored, lang):
    await _language(stored)
    assert await card_purpose.language() == lang


async def test_no_setting_is_english(execution_db):
    assert await card_purpose.language() == "en"


class _Asker:
    def __init__(self):
        self.frames: list[dict] = []

    async def __call__(self, frame):
        self.frames.append(frame)
        return {"approved": False, "scope": "once", "note": "", "by": "mac", "call_id": frame["call_id"]}


async def _title(**kw):
    asker = _Asker()
    with permissions.asking_with(asker):
        await command_confirm.Confirmations("c1").command(*kw.pop("cmd"), **kw)
    return asker.frames[0]["title"]


async def test_the_ordinary_card_is_titled_with_its_purpose_in_the_users_language(execution_db):
    await _language("zh")
    assert await _title(cmd=("git push origin main", [])) == "把提交推送到 origin"
    assert await _title(cmd=(SSH, []), network=True) == "看看能不能用 SSH 连上 192.168.1.4（试连一次，最多 4 秒）"


async def test_arslans_reason_titles_the_card(execution_db):
    assert await _title(cmd=("git push origin main", []), why="Publish the fix") == "Publish the fix"


async def test_the_outside_card_says_it_runs_outside_the_sandbox(execution_db):
    await _language("zh")
    assert await _title(cmd=("mv a ~/b", []), sandbox="outside") == "移动 1 项（这一次在沙盒外运行）"


async def test_the_remote_card_says_where_it_runs(execution_db):
    title = await _title(cmd=("uptime", []), remote_host="me@box", fingerprints=["SHA256:x"])
    assert title == "Run uptime (on me@box)"


def test_a_bare_shortcut_says_it_runs_as_the_user(monkeypatch):
    from server.services import task_service
    monkeypatch.setattr(task_service, "unwrapped_once", lambda shell: True)
    request = approvals._command_request("shortcuts run 'Morning Brief'", ["shortcuts"], None, lang="en")
    assert request.title == ("Run the Shortcut “Morning Brief” (it runs as you, outside the sandbox; "
                             "Arslan can't see what the Shortcut does)")


def test_a_caller_with_no_language_keeps_the_old_title():
    assert approvals._command_request("git push", ["git-push"], None).title == "Run `git push`?"


def test_the_model_keeps_reading_the_command():
    """The phone reads the purpose; the model's refusal and expiry texts keep quoting the command itself."""
    request = approvals._command_request("git push origin main", ["git-push"], None, lang="en")
    assert request.title == "Publish your commits to origin"
    assert request.title_for_model == "Run `git push origin main`?"


async def test_the_network_card_is_titled_with_its_purpose(execution_db, monkeypatch):
    await _language("zh")
    seen = []

    async def decide(request, context):
        seen.append(request)
        return SimpleNamespace(allowed=True, model_text="")
    monkeypatch.setattr(untrusted, "external_seen", lambda: True)
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(permissions, "current_asker", lambda: object())
    monkeypatch.setattr(permissions, "decide", decide)
    await tool_loop._network_after_outside_content("curl https://api.example.com/x", {}, sandbox_on=True,
                                                   run_outside=False, unwrapped=False, conversation_id="c1")
    assert seen[0].title == "从 api.example.com 下载（会联网，仅这一次）"


async def test_nobody_to_ask_lists_the_card_by_its_purpose(execution_db, monkeypatch):
    listed = []

    async def unattended(message, request, conversation_id):
        listed.append(request.title)
        return message
    monkeypatch.setattr(tool_loop, "_unattended", unattended)

    async def _resolve():
        return [{"key": "ssh_run", "description": "run"}]
    await tool_loop._dispatch_tool("ssh_run", {"host": "box", "command": "uptime"}, "{}", resolve_tools=_resolve,
                                   emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
                                   confirm_command=None, conversation_id="c1")
    assert listed == ["Run uptime (on box)"]


def test_the_packaged_app_carries_the_strings():
    spec = (ROOT / "packaging/arslan-server.spec").read_text()
    assert '"web", "src", "locales", "card-purposes.json"), "server/resources"' in spec


@pytest.mark.parametrize("kw", [{"cmd": ("git push origin main", [])},
                                {"cmd": ("mv a ~/b", []), "sandbox": "outside"},
                                {"cmd": ("uptime", []), "remote_host": "me@box", "fingerprints": ["SHA256:x"]}],
                         ids=["ordinary", "outside", "remote"])
async def test_no_user_facing_surface_reads_the_models_sentence(execution_db, kw):
    """⓪Plan's review check: what the user sees (the card frame, which the Mac, the phone and the island render) carries
    the plain purpose and never the model's sentence; the model's own text (a decline's `model_text`, read only into
    tool results) quotes the command."""
    asker = _Asker()
    permissions.LAST_DECISION.set(None)
    with permissions.asking_with(asker):
        await command_confirm.Confirmations("c1").command(*kw.pop("cmd"), **kw)
    [frame] = asker.frames
    assert "Run `" not in json.dumps(frame, ensure_ascii=False)
    decision = permissions.LAST_DECISION.get()
    assert decision is not None and "Run `" in decision.model_text

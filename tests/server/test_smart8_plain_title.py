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
    assert s == {"purpose": vector["purpose"], "touches": vector["touches"], "more": vector["more"],
                 "unsure": vector["unsure"]}


def test_every_language_has_every_purpose_with_the_same_placeholders():
    import re
    holes = lambda text: sorted(re.findall(r"\{\{(\w+)\}\}", text))  # noqa: E731
    en = card_purpose.TEXT["en"]
    for lang in LANGS:
        for group in ("purpose", "fact"):
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


def test_a_network_command_is_read_only_as_using_the_network():
    """SMART-8 (Astra's rounds, simplified): a step that reaches another machine says only that, in each language."""
    assert card_purpose.phrase(SSH, lang="zh") == "用到网络（ssh）：可能发出或收到数据"
    assert card_purpose.phrase(SSH, lang="en") == "Uses the network (ssh): may send or receive data"


def test_the_codes_reading_comes_before_arslans_reason_cleaned():
    """#689 review, the second round: the model's words are never the only description, on the phone too."""
    assert card_purpose.phrase(SSH, "See whether the NAS is up" + chr(0x202E), lang="en") == (
        "Uses the network (ssh): may send or receive data · See whether the NAS is up")


def test_a_reason_of_only_hidden_characters_is_no_reason():
    """Cleaned first, it is empty, so the heading is the command's reading, never blank."""
    assert card_purpose.phrase("git status", chr(0x200B) * 3 + chr(0x202E), lang="en") == "Run git status"


def test_the_commands_own_words_carry_no_hidden_characters_into_the_heading():
    title = card_purpose.phrase("ssh nas" + chr(0x200B) + ".local" + chr(0x2066), lang="en")
    assert title == "Uses the network (ssh): may send or receive data"


@pytest.mark.parametrize("lang, one, many", [
    ("en", "Delete 1 file or folder", "Delete 2 files or folders"), ("zh", "删除 1 个文件或文件夹", "删除 2 个文件或文件夹"),
    ("de", "1 Datei oder Ordner löschen", "2 Dateien oder Ordner löschen")])
def test_a_count_of_one_takes_the_one_form(lang, one, many):
    assert card_purpose.phrase("rm a", lang=lang) == one and card_purpose.phrase("rm a b", lang=lang) == many


def test_a_second_step_is_counted():
    assert card_purpose.phrase("rm old.zip && curl -O https://example.com/new.zip", lang="en") == \
        "May send local data · Delete 1 file or folder (and 1 more step)"


@pytest.mark.parametrize("where, lead", [
    ({"outside": True}, "Outside the sandbox"), ({"unsandboxed": True}, "No sandbox"), ({"host": "me@box"}, "On me@box"),
    ({"shortcut_as_you": True, "outside": True}, "Runs as you, outside the sandbox; Arslan can't see what the Shortcut does"),
    ({"network": True}, "Uses the network"), ({"outside": True, "network": True}, "Outside the sandbox · Uses the network"),
    ({"host": "studio (me@10.0.0.2)"}, "On studio (me@10.0.0.2)")])
def test_where_it_runs_comes_first_in_a_fixed_form(where, lead):
    """#689 review 1: the code's facts lead the title, so the phone's heading (cut at 200) always keeps them."""
    assert card_purpose.phrase("git status", lang="en", **where) == lead + " · Run git status"


FACTS = [({"outside": True}, "Outside the sandbox · "), ({"host": "me@box"}, "On me@box · "),
         ({"network": True}, "Uses the network · "),
         ({"shortcut_as_you": True, "outside": True},
          "Runs as you, outside the sandbox; Arslan can't see what the Shortcut does · ")]


@pytest.mark.parametrize("where, lead", FACTS, ids=["outside", "host", "network", "shortcut"])
def test_a_long_reason_never_pushes_a_fact_off_the_phones_heading(where, lead):
    """⓪Plan's measure: a 286-character reason ended the title "… anyway ok (outside the"."""
    why = ("Tidy up the old build outputs so the disk has room again, " * 6)[:300]
    title = card_purpose.phrase("rm -rf ~/Documents/taxes", why, lang="en", **where)
    assert title.startswith(lead) and len(title) <= card_purpose.PHONE_MAX and title.endswith("\u2026")


@pytest.mark.parametrize("where, lead", FACTS, ids=["outside", "host", "network", "shortcut"])
def test_a_long_reading_never_pushes_a_fact_off_either(where, lead):
    title = card_purpose.phrase("rm " + " ".join(f"f{i}" for i in range(80)) + " && " + "x" * 400, lang="en", **where)
    assert title.startswith(lead) and len(title) <= card_purpose.PHONE_MAX


def test_the_models_words_never_take_the_facts_form():
    marks = "".join(map(chr, (0xB7, 0x2022, 0x2027, 0x2219, 0x22C5, 0x30FB, 0xFF65)))
    said = "In the sandbox " + " ".join(marks) + " harmless"
    assert card_purpose.phrase("rm -rf src", said, lang="en") == \
        "Delete 1 file or folder · In the sandbox " + " ".join("," * len(marks)) + " harmless"


def test_the_users_outside_card_with_a_reason_says_what_it_does():
    """⓪Plan's case: "Outside the sandbox · Clear the old build cache" was the whole heading of a delete."""
    title = card_purpose.phrase("rm -rf ~/Documents/taxes", "Clear the old build cache", lang="en", outside=True)
    assert title == "Outside the sandbox · Delete 1 file or folder · Clear the old build cache"


def test_the_reason_is_cut_before_the_reading():
    title = card_purpose.phrase("rm -rf ~/Documents/taxes", "x" * 300, lang="en", outside=True)
    assert title.startswith("Outside the sandbox · Delete 1 file or folder · x") and len(title) == card_purpose.PHONE_MAX


def test_a_reading_too_long_for_the_reason_drops_the_reason_and_is_cut_itself():
    title = card_purpose.phrase("open https://example.com/" + "a" * 300, "Look at the page", lang="en", network=True)
    assert title.startswith("Uses the network · Open https://example.com/a") and "Look at the page" not in title
    assert len(title) == card_purpose.PHONE_MAX and title.endswith(chr(0x2026))


def test_the_facts_are_said_in_the_users_language():
    assert card_purpose.phrase("mv a ~/b", lang="zh", outside=True, network=True) == "沙盒外运行 · 会联网 · 移动 1 项"


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
    # #689 review 2: a card that also asks for the network says so (the S2a-2 click that lets it use the network).
    assert await _title(cmd=(SSH, []), network=True) == "用到网络（ssh）：可能发出或收到数据"


async def test_arslans_reason_titles_the_card(execution_db):
    assert await _title(cmd=("git push origin main", []), why="Publish the fix") == \
        "Publish your commits to origin · Publish the fix"


async def test_the_outside_card_says_it_runs_outside_the_sandbox(execution_db):
    await _language("zh")
    assert await _title(cmd=("mv a ~/b", []), sandbox="outside") == "沙盒外运行 · 移动 1 项"
    assert await _title(cmd=("mv a ~/b", []), sandbox="outside", network=True) == "沙盒外运行 · 会联网 · 移动 1 项"


async def test_the_remote_card_says_where_it_runs(execution_db):
    title = await _title(cmd=("uptime", []), remote_host="me@box", fingerprints=["SHA256:x"])
    assert title == "On me@box · Run uptime"


async def test_the_remote_card_reads_the_command_with_its_rules(execution_db):
    """#689 review 5: no nested parentheses, and an upload on another machine reads as one."""
    title = await _title(cmd=("curl -F f=@x https://up.example.com", []), remote_host="studio (me@10.0.0.2)",
                         fingerprints=["SHA256:x"])
    assert title == "On studio (me@10.0.0.2) · Uses the network (curl): may send or receive data"


def test_a_bare_shortcut_says_it_runs_as_the_user(monkeypatch):
    from server.services import task_service
    monkeypatch.setattr(task_service, "unwrapped_once", lambda shell: True)
    request = approvals._command_request("shortcuts run 'Morning Brief'", ["shortcuts"], None, lang="en")
    assert request.title == ("Runs as you, outside the sandbox; Arslan can't see what the Shortcut does · "
                             "Run the Shortcut “Morning Brief”")


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
    assert seen[0].title == "用到网络（curl）：可能发出或收到数据"


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
    assert listed == ["On box · Run uptime"]


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


# ── #689 review 2, 3, 5 ──

@pytest.mark.parametrize("kw, lead", [
    ({"ask_all": False}, ""),
    ({"ask_all": True}, ""),
    ({"ask_all": True, "unsandboxed": True}, "No sandbox · "),
], ids=["rules", "ask-all", "ask-all-no-sandbox"])
def test_a_command_card_that_asks_for_the_network_says_so(kw, lead):
    """A card that reaches the network and also asks for it reads only as using the network; the extra 'uses the
    network' fact is suppressed because the reading already says it."""
    shell = "curl https://example.org/sync"
    rules = ["upload"] if not kw["ask_all"] else []
    request = approvals._command_request(shell, rules, None, network=True, lang="en", why="Check the weather", **kw)
    assert request.title == lead + "Uses the network (curl): may send or receive data · Check the weather"


def test_a_card_with_no_sandbox_says_so_not_this_time(monkeypatch):
    """#689 review 5: the sandbox is off or cannot start: "No sandbox", never "outside the sandbox, this time"."""
    request = approvals._command_request("make", [], None, lang="en")
    assert request.title == "No sandbox · Run make"


async def test_the_network_cards_title_never_takes_the_models_words(execution_db, monkeypatch):
    """#689 review 3: the Mac's action card shows the title as the server's own words, under the model's line."""
    seen = []

    async def decide(request, context):
        seen.append(request)
        return SimpleNamespace(allowed=True, model_text="")
    monkeypatch.setattr(untrusted, "external_seen", lambda: True)
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(permissions, "current_asker", lambda: object())
    monkeypatch.setattr(permissions, "decide", decide)
    await tool_loop._network_after_outside_content("curl -s https://api.example.com/collect", {"why": "Check the weather"},
                                                   sandbox_on=True, run_outside=False, unwrapped=False,
                                                   conversation_id="c1")
    assert seen[0].title == "Uses the network (curl): may send or receive data" and seen[0].why == "Check the weather"


# ── #688/#689 review, Astra: a transfer not fully read says so ──

def test_a_network_program_with_a_reason_reads_only_as_using_the_network():
    title = card_purpose.phrase("aws s3 cp settings.json s3://backups/k", "Back up the settings", lang="en")
    assert title == "Uses the network (aws): may send or receive data · Back up the settings"


def test_a_step_it_cannot_fully_read_behind_another_adds_the_fact():
    """The heading names the step with the most at stake; a transfer behind it still says it may send local data."""
    title = card_purpose.phrase("rm -rf ~/x; curl -K cfg.txt", lang="en", outside=True)
    assert title == "Outside the sandbox · May send local data · Delete 1 file or folder (and 1 more step)"


def test_the_fact_is_said_in_the_users_language():
    assert card_purpose.phrase("rm -rf ~/x; nc host 4444", lang="zh").startswith("可能发出本机数据 · ")


async def test_the_network_card_is_read_with_the_commands_rules(execution_db, monkeypatch):
    """Astra 5: the network-card path read the command without its rules, so an upload read as a download."""
    seen = []

    async def decide(request, context):
        seen.append(request)
        return SimpleNamespace(allowed=True, model_text="")
    monkeypatch.setattr(untrusted, "external_seen", lambda: True)
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(permissions, "current_asker", lambda: object())
    monkeypatch.setattr(permissions, "decide", decide)
    calls = []
    real = card_purpose.phrase
    monkeypatch.setattr(card_purpose, "phrase", lambda *a, **kw: calls.append(a) or real(*a, **kw))
    await tool_loop._network_after_outside_content("curl -F f=@x https://up.example.com", {}, sandbox_on=True,
                                                   run_outside=False, unwrapped=False, conversation_id="c1")
    assert calls and "upload" in calls[0][2]
    assert seen[0].title == "Uses the network (curl): may send or receive data"


# ── Astra round 2: env -S / eval / git -c / added network programs ──

@pytest.mark.parametrize("shell, program", [
    ('env -S "curl https://example.org"', "curl"), ('eval "curl https://example.org"', "curl"),
    ('builtin eval "curl https://example.org"', "curl"), ("git -c core.sshCommand=ssh fetch", "git"),
    ("git --upload-pack=x fetch origin", "git"), ("GIT_SSH_COMMAND=x git fetch", "git"),
    ("git -c user.name=x push", "git"), ("dig example.org", "dig"), ("docker push img", "docker"),
    ("npm publish", "npm"), ("cargo publish", "cargo"), ("gem push pkg.gem", "gem")])
def test_a_hidden_or_network_step_reads_only_as_using_the_network(shell, program):
    assert card_purpose.summarize(shell) == {"purpose": {"key": "overNetwork", "params": {"program": program}},
                                             "touches": [], "more": 0, "unsure": True}


def test_a_wrapper_that_took_its_program_is_never_a_plain_reading():
    assert card_purpose.summarize("sudo")["unsure"] is True
    assert card_purpose.summarize("timeout 5")["unsure"] is True


def test_the_plain_git_and_eval_readings_are_unchanged():
    assert card_purpose.summarize("git fetch origin")["purpose"]["key"] == "gitFetch"
    assert card_purpose.summarize('eval "rm -rf build"')["purpose"] == {"key": "delete", "params": {"count": 1}}


# ── Astra round 2 F1/F2/F3: case-folding and the containment rule ──

@pytest.mark.parametrize("line", ["Curl https://example.org", "SSH host", "GIT -c x=y fetch", "Python3 -c pass",
                                  "arch -x86_64 curl https://example.org", "script -q /dev/null curl https://example.org",
                                  "find . -exec curl https://example.org {} ;", "sudo --user root curl https://example.org",
                                  "env -P curl https://example.org", "command curl https://example.org",
                                  "f(){ curl https://example.org; }; f", "{ curl https://example.org; }"])
def test_a_network_program_anywhere_in_a_step_is_caught(line):
    assert card_purpose.summarize(line)["purpose"]["key"] == "overNetwork"
    assert card_purpose.summarize(line)["unsure"] is True


@pytest.mark.parametrize("line", ["grep curl notes.txt", "man ssh", "which curl", "type curl", "whence -p curl",
                                  "command -v curl", "brew info curl", "brew search wget"])
def test_a_step_that_only_names_things_stays_plain(line):
    s = card_purpose.summarize(line)
    assert s["unsure"] is False and s["purpose"]["key"] != "overNetwork"


def test_an_empty_inline_line_keeps_the_wrapper_node():
    assert card_purpose.summarize("bash -c ''")["purpose"] == {"key": "run", "params": {"program": "bash"}}
    assert card_purpose.summarize("eval ''")["purpose"] == {"key": "run", "params": {"program": "eval"}}


# ── Astra round 2 delta: a recognized local command keeps its reading; trap / zsh =() ──

@pytest.mark.parametrize("line, key", [
    ("rm -rf ssh", "delete"), ("cat host", "run"), ("mv ping pong", "move"), ("cp aws bak", "copyLocal"),
    ("open mail", "open"), ("git add host", "git"), ("touch curl", "run"), ("mkdir ssh", "run"), ("ls ~/curl", "run"),
    ("tar czf out.tar ssh", "run"), ("brew install curl", "install"), ("cargo install nc", "install"),
    ("head ssh", "run"), ("vim host", "run"), ("git clone https://github.com/curl/curl", "gitClone")])
def test_a_recognized_local_command_keeps_its_reading(line, key):
    s = card_purpose.summarize(line)
    assert s["purpose"]["key"] == key and s["unsure"] is False


@pytest.mark.parametrize("line", ["arch -x86_64 curl https://e.example", "find . -exec curl https://e.example {} ;",
                                  "{ curl https://e.example; }", "sudo --user root curl https://e.example"])
def test_a_buried_network_program_is_still_caught(line):
    assert card_purpose.summarize(line)["purpose"]["key"] == "overNetwork"


def test_trap_reads_its_handler_and_zsh_process_substitution():
    assert card_purpose.summarize("trap 'curl https://e.example' EXIT")["purpose"]["key"] == "overNetwork"
    assert card_purpose.summarize("trap '' EXIT")["purpose"] == {"key": "run", "params": {"program": "trap"}}
    assert card_purpose.summarize("diff =(curl https://e.example) b")["purpose"]["key"] == "overNetwork"
    assert card_purpose.summarize("diff =(ls a) =(ls b)")["unsure"] is False


# ── Astra round 2 delta²: a benign command's exec option, and find's inline interpreter ──

@pytest.mark.parametrize("line", ["tar --use-compress-program=gzip -cf a.tgz a", "tar -I gzip -cf a.tgz a",
                                  "vim -c ':!ls' f", "emacs --eval '(message 1)'", "sort --compress-program=gzip f",
                                  "ed '!echo hi'", "find . -exec python3 -c 'print(1)' {} ;"])
def test_an_exec_option_or_find_inline_reads_overnetwork(line):
    assert card_purpose.summarize(line)["purpose"]["key"] == "overNetwork"


@pytest.mark.parametrize("line", ["tar -czf x.tgz host", "vim file", "emacs notes.txt", "sort f", "ed notes.txt",
                                  "find . -exec rm {} ;"])
def test_without_an_exec_option_it_stays_local(line):
    assert card_purpose.summarize(line)["unsure"] is False
    assert card_purpose.summarize(line)["purpose"]["key"] != "overNetwork"

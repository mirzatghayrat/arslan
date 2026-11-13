"""HR-3 part 1: the direct forms of a write into a file that runs later (`terminal_policy.run_later_targets`), and the
click-lift rule: outside the sandbox, only a click on the command's own card lets one through (`command_gate.check`,
`approvals._command_request`), never a grant, a stored answer or anything else that isn't that click."""
from __future__ import annotations

import pytest

from server.db import session as db_session
from server.orchestrator import command_gate, tool_loop
from server.orchestrator.turn_state import ToolTurn
from server.services import (approvals, card_purpose, command_confirm, command_sandbox, hard_rules, permission_store,
                             permissions, settings_service, terminal_exec, terminal_policy as tp)
from server.services.permissions import Request
from tests.server import hard_rules_cases as hr

UNKNOWN = tp.RUN_LATER_UNKNOWN
HOOK = ".git/hooks/pre-commit"

# (command, a target it must name). Every one of these is a hit.
HITS = [
    # redirections
    ("echo x > .git/hooks/pre-commit", HOOK),
    ("echo x >> .git/hooks/pre-commit", HOOK),
    ("printf x >| .envrc", ".envrc"),
    ("ls &> .vscode/tasks.json", ".vscode/tasks.json"),
    ("cat <<'EOF' > .git/hooks/pre-push\nx\nEOF", ".git/hooks/pre-push"),
    ("echo '{}' > .mcp.json", ".mcp.json"),
    ("echo x > .cursor/mcp.json", ".cursor/mcp.json"),
    ("echo x > .codex/config.toml", ".codex/config.toml"),
    ("echo x > .claude/settings.local.json", ".claude/settings.local.json"),
    ("echo x > team.code-workspace", "team.code-workspace"),
    ("echo x > .pre-commit-config.yaml", ".pre-commit-config.yaml"),
    ("echo x > .yarnrc.yml", ".yarnrc.yml"),
    ("echo x > uv.toml", "uv.toml"),
    ("echo x > .husky/pre-commit", ".husky/pre-commit"),
    ("echo x > .gitmodules", ".gitmodules"),
    # spellings: case, `.`, `//`, `..`
    ("echo x > .Git/Hooks/Pre-Commit", ".Git/Hooks/Pre-Commit"),
    ("echo x > ./.git//hooks/./pre-commit", "./.git//hooks/./pre-commit"),
    ("echo x > sub/../.git/config", "sub/../.git/config"),
    ("echo x > .git/x/../config", ".git/x/../config"),
    ("echo x > /Users/someone/project/.git/hooks/pre-commit", "/Users/someone/project/.git/hooks/pre-commit"),
    # programs that write the files they name
    ("echo x | tee .envrc", ".envrc"),
    ("echo x | tee -a .npmrc", ".npmrc"),
    ("touch .envrc", ".envrc"),
    ("truncate -s 0 .npmrc", ".npmrc"),
    ("chmod +x .git/hooks/pre-commit", HOOK),
    ("chmod -R 755 .git/hooks", ".git/hooks"),
    ("dd if=x of=.git/config", ".git/config"),
    ("sed -i '' 's/a/b/' .git/config", ".git/config"),
    ("sed -i.bak -e 's/a/b/' .vscode/settings.json", ".vscode/settings.json"),
    ("sed -n 's/x/y/w .git/hooks/pre-commit' notes.txt", HOOK),
    # programs that put their operands somewhere
    ("cp hook .git/hooks/pre-commit", HOOK),
    ("cp pre-commit .git/hooks", ".git/hooks/pre-commit"),
    ("cp hook .git/hooks/", ".git/hooks/"),
    ("mv pre-commit.sample .git/hooks/pre-commit", HOOK),
    ("install -m 755 hook .git/hooks/pre-commit", HOOK),
    ("ln -s ../../hook .git/hooks/pre-commit", HOOK),
    ("ln -s /tmp/elsewhere/.envrc", "./.envrc"),                    # the link it makes, here
    ("cp settings.json .claude", ".claude/settings.json"),
    ("cp -t .husky hook", ".husky"),
    ("rsync -a hooks/ .git/hooks/", ".git/hooks/"),
    ("mv prepared .vscode", ".vscode"),
    ("CP hook .git/hooks/pre-commit", HOOK),                       # by name, in any case
    # git
    ("git config core.hooksPath x", ".git/config"),
    ("git config --global core.hooksPath x", "~/.gitconfig"),
    ("git config --system core.pager x", "/etc/gitconfig"),
    ("git config --local alias.x '!sh -c y'", ".git/config"),
    ("git config set core.fsmonitor x", ".git/config"),
    ("git config --unset core.editor", ".git/config"),
    ("git config --add filter.x.clean y", ".git/config"),
    ("git config --edit", ".git/config"),
    ("git -C sub config core.hooksPath h", "sub/.git/config"),
    ("git --git-dir=.git config core.sshCommand x", ".git/config"),
    ("git config --worktree core.hooksPath x", ".git/config.worktree"),
    ("git config -f .gitmodules submodule.x.update '!sh'", ".gitmodules"),
    ("git -c core.hooksPath=/tmp/h commit -m x", tp.RUN_LATER_SETTING + "core.hooksPath"),
    ("git -c alias.st=!sh status", tp.RUN_LATER_SETTING + "alias.st"),
    ("git --config-env=core.pager=PAGER log", tp.RUN_LATER_SETTING + "core.pager"),
    ("git init", ".git/hooks"),
    ("git init --template=/tmp/t repo", ".git/hooks"),
    ("git clone https://example.invalid/r.git", ".git/hooks"),
    ("git submodule add https://example.invalid/r.git sub", ".gitmodules"),
    ("git submodule update --init", ".git/modules"),
    ("git checkout -- .envrc", ".envrc"),
    ("GIT checkout HEAD -- .vscode/tasks.json", ".vscode/tasks.json"),
    # other programs' own forms
    ("npm config set registry https://example.invalid", ".npmrc"),
    ("npm set registry https://example.invalid", ".npmrc"),
    ("pnpm config set x y", ".npmrc"),
    ("yarn config set x y", ".yarnrc.yml"),
    ("pip config set global.index-url https://example.invalid", "pip.conf"),
    ("pre-commit install", HOOK),
    ("npx husky init", ".husky"),
    ("husky", ".husky"),
    ("direnv allow", ".envrc"),
    # any other program given a held path
    ("curl -o .git/hooks/pre-commit https://example.invalid/h", HOOK),
    ("curl --output=.envrc https://example.invalid/e", ".envrc"),
    ("wget -O.envrc https://example.invalid/e", ".envrc"),
    ("vim .git/hooks/pre-commit", HOOK),
    # after a change of folder
    ("cd .git/hooks && echo x > pre-commit", HOOK),
    ("cd .git && cp ../hook hooks/pre-commit", ".git/hooks/pre-commit"),
    ("cd sub; cd .. ; echo x > .envrc", ".envrc"),
    # through the reader's wrappers and bash -c
    ("nohup cp hook .git/hooks/pre-commit", HOOK),
    ("timeout 5 tee .envrc", ".envrc"),
    ("env A=1 touch .envrc", ".envrc"),
    ("command cp hook .git/hooks/pre-commit", HOOK),
    ("bash -c 'echo x > .git/hooks/pre-commit'", HOOK),
    ("ls; (cd .git/hooks && echo x > pre-commit)", HOOK),
    ("echo $(touch .envrc)", ".envrc"),
    # the home-level names
    ("echo x >> ~/.zshrc", "~/.zshrc"),
    ("echo x > /Users/someone/.bash_profile", "/Users/someone/.bash_profile"),
    ("cp agent.plist ~/Library/LaunchAgents/", "~/Library/LaunchAgents/"),
    ("cd ~ && echo x >> .zprofile", "~/.zprofile"),
    ("echo x >> ~/.gitconfig", "~/.gitconfig"),
    ("echo x > ~/.claude.json", "~/.claude.json"),
    ("cp config.fish ~/.config/fish/config.fish", "~/.config/fish/config.fish"),
]

# Commands it can't pin down: unknown, which the caller treats as a hit.
UNKNOWNS = [
    "/bin/cp hook .git/hooks/pre-commit",               # a program named by a path
    "python3 -c \"open('.git/hooks/x', 'w')\"",          # an interpreter's script
    "echo .envrc | xargs touch",
    "eval 'echo x > .envrc'",
    "find . -name x -exec cp {} .git/hooks \\;",
    "awk '{print > \".envrc\"}' notes.txt",
    "perl -pi -e 's/a/b/' .git/config",
    "GIT_DIR=/tmp/x git config core.hooksPath y",
    "GIT_CONFIG_GLOBAL=.git/config git config --global core.hooksPath y",
    "export GIT_CONFIG_PARAMETERS=x",
    "echo x > $(echo .envrc)",
    "echo x > `echo .envrc`",
    "cp \"$SRC\" .",
    "tee $F",
    "chmod +x \"$HOOK\"",
    "cd \"$D\" && echo x > pre-commit",
    "git -C \"$R\" config a.b c",
    "git config $ARGS",
    "git --weird-option config a.b c",
    "git -c \"$K\" status",
    "npm config $VERB x y",
    "alias cp='cp .envrc'",
    "echo x > .envrc" + chr(0x200B),                     # an invisible character (written as chr, never escaped)
    "x" * (tp.MAX_COMMAND_CHARS + 1),
]

# Ordinary commands: no hit.
MISSES = [
    "ls", "ls -la .git/hooks", "git status", "git commit -m 'edit .envrc'", "git add .envrc", "git diff .vscode/settings.json",
    "cat .git/config", "grep x .envrc", "cat ~/.zshrc", "echo .git/hooks/pre-commit", "echo x > notes.txt",
    "cp a b", "mv src/a.py src/b.py", "touch README.md", "chmod +x scripts/run.sh", "sed -n p .git/config",
    "git config --get core.hooksPath", "git config core.hooksPath", "git config --list", "git config get user.name",
    "git config --global --get user.name", "git -c user.name=x commit -m y", "git -c color.ui=false log",
    "git submodule status", "npm install", "npm config get registry", "pre-commit run --all-files", "direnv status",
    "husky --help", "pytest tests/", "cd .git/hooks && ls", "echo x > /dev/null", "echo x 2>&1",
    "echo x > .envrc.example", "echo x > node_modules/pkg/.envrc", "cp x node_modules/pkg/.vscode/tasks.json",
    "rm .git/hooks/pre-commit", "rm -rf '~/Library'",                  # a delete makes nothing run later
    # the user's rulings: CI files and instruction files are ordinary files (run_later's docstring)
    "echo x > .github/workflows/ci.yml", "echo x > AGENTS.md", "echo x > CLAUDE.md", "echo x > .cursorrules",
    "",
]


@pytest.mark.parametrize("command,name", HITS, ids=[c for c, _ in HITS])
def test_run_later_targets(command, name):
    """The table: each direct form is a hit naming its file (or git setting), an unknown form is a hit, and an
    ordinary command is none. (Its cases are parametrized below; this one is the hits'.)"""
    found = tp.run_later_targets(command)
    assert name in found, found
    assert tp.run_later_file(found) or found[0].startswith(tp.RUN_LATER_SETTING)


@pytest.mark.parametrize("command", UNKNOWNS, ids=[c[:60] for c in UNKNOWNS])
def test_what_it_cannot_read_is_unknown_and_so_a_hit(command):
    assert UNKNOWN in tp.run_later_targets(command)


@pytest.mark.parametrize("command", MISSES, ids=[c or "empty" for c in MISSES])
def test_an_ordinary_command_is_no_hit(command):
    assert tp.run_later_targets(command) == []


def test_the_harmless_layer_three_cases_gain_no_card():
    """The commands the three-layer suite runs with no card in the sandbox: none is a hit, but for those the reader
    doesn't understand (`python3 x.py`), which are unknown here and already `unreadable` outside, a once-only card
    there whatever HR-3 says. So nothing ordinary gains a card under a grant."""
    texts = [c["command"] for c in hr.cases(hr_node("test_layer_three_runs"))]
    hits = [t for t in texts if tp.run_later_targets(t)]
    assert texts and len(hits) < len(texts)
    for text in hits:
        assert tp.run_later_targets(text) == [UNKNOWN] and tp.reading(text).refused, text
        assert tp.UNREADABLE in tp.ask_rules(text, outside=True), text


def hr_node(name: str) -> str:
    return "tests/server/test_s2a2_three_layers.py::" + name


def test_it_reads_nothing_on_disk(tmp_path, monkeypatch):
    """Pure: a link already on disk is not followed (not covered; the kernel's link hold is HR-1's), and making one
    at a held folder is a hit."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "h").symlink_to(tmp_path / ".git" / "hooks")
    assert tp.run_later_targets("echo x > h/pre-commit") == []
    assert ".git/hooks" in tp.run_later_targets("ln -s .git/hooks h")


# ── never_auto reads it (hard_rules) ─────────────────────────────────────────

def test_a_command_that_writes_a_file_that_runs_later_is_never_auto():
    def command(text):
        return Request(kind="command", target="text:" + text, title="t", detail=text)
    assert hard_rules.never_auto(command("echo x > .git/hooks/pre-commit"))
    assert hard_rules.never_auto(command("git config core.hooksPath x"))
    assert not hard_rules.never_auto(command("ls"))
    assert not hard_rules.never_auto(Request(kind="workspace_write", target="x", title="t"))     # HR-2's


# ── the click-lift rule, through the real gate and card ladder ────────────────

class _Exec:
    key = "run_command"

    def __init__(self):
        self.runs: list[tuple[bool, bool]] = []

    async def execute(self, args):
        self.runs.append((terminal_exec.OUTSIDE_SANDBOX.get(), terminal_exec.HOLD_RUN_LATER.get()))
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "off"}


class _Asker:
    """A card surface that records each card and answers yes, as the asking window's click."""

    def __init__(self):
        self.frames: list[dict] = []

    async def __call__(self, frame):
        self.frames.append(frame)
        return {"approved": True, "scope": frame["options"][0], "note": "", "by": "mac", "call_id": frame["call_id"]}


@pytest.fixture
def gate(monkeypatch):
    permissions._reset_for_tests()
    approvals._reset_for_tests()
    command_sandbox._reset_for_tests()
    state = {"sandbox": True, "ask_all": False}

    async def answer(value):
        return value
    monkeypatch.setattr(command_gate, "_sandbox_enabled", lambda: answer(state["sandbox"]))
    monkeypatch.setattr(command_gate, "_asks_for_everything", lambda: answer(state["ask_all"]))
    monkeypatch.setattr(command_gate, "_work_folder_holds_home", lambda: answer(False))
    monkeypatch.setattr(settings_service, "default_permission_mode",
                        lambda db: answer("ask" if state["ask_all"] else "ask_risky"))
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    yield state
    permissions._reset_for_tests()
    approvals._reset_for_tests()
    command_sandbox._reset_for_tests()


async def _resolve():
    return [{"key": "run_command", "description": "run"}]


async def _dispatch(monkeypatch, args, *, confirm=None):
    ex, asker = _Exec(), _Asker()
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", ex)
    with permissions.asking_with(asker):
        result = await tool_loop._run_tool("run_command", args, "{}", ToolTurn(
            resolve_tools=_resolve, emit=lambda e: None, tool_timeout_s=5, tool_trace=[],
            convo=[], confirm_command=confirm or command_confirm.Confirmations("c1").command, conversation_id="c1"))
    return ex.runs, asker.frames, result


async def _store(kind, target, *, rule=False):
    async with db_session.AsyncSessionLocal() as db:
        if rule:
            await permission_store.add_rule(db, kind, target, label="x")
        else:
            await permission_store.add_grant(db, "c1", "", kind, target, call_id="card-0")
        await db.commit()


@pytest.mark.parametrize("command,line", [
    ("git config core.hooksPath x", "Writes a file that runs later: .git/config"),
    ("echo x > .git/hooks/pre-commit", "Writes a file that runs later: .git/hooks/pre-commit"),
], ids=["git-config", "redirection"])
async def test_under_an_outside_grant_a_run_later_write_gets_a_once_only_card(execution_db, gate, monkeypatch,
                                                                              command, line):
    await _store("outside", "*")
    runs, frames, _ = await _dispatch(monkeypatch, {"command": command})
    assert len(frames) == 1 and frames[0]["options"] == ["once"], frames      # no "this conversation", no "Always"
    assert line in frames[0]["title"]
    assert runs == [(True, False)]                      # out, and the user's click on its own card lifted the hold
    # The same grant lets an ordinary command out with no card, held (HR-1).
    runs, frames, _ = await _dispatch(monkeypatch, {"command": "ls"})
    assert frames == [] and runs == [(True, True)]


async def test_what_the_reader_cannot_read_is_once_only_under_a_grant_already(execution_db, gate, monkeypatch):
    """Unknown is a hit: under the grant such a command's card is a rules card (`unreadable`), this time only."""
    await _store("outside", "*")
    command = "python3 -c \"open('.git/hooks/pre-commit', 'w')\""
    assert tp.run_later_targets(command) == [UNKNOWN]
    runs, frames, _ = await _dispatch(monkeypatch, {"command": command})
    assert len(frames) == 1 and frames[0]["options"] == ["once"] and runs == [(True, False)]


async def test_in_the_sandbox_the_kernel_holds_it_and_no_card_is_added(execution_db, gate, monkeypatch):
    runs, frames, _ = await _dispatch(monkeypatch, {"command": "echo x > .git/hooks/pre-commit"})
    assert frames == [] and runs == [(False, False)]


@pytest.mark.parametrize("stored", ["conversation-grant", "rule", "ask-all-text-grant"])
async def test_a_remembered_or_conversation_answer_never_lifts_it(execution_db, gate, monkeypatch, stored):
    """With the sandbox off nothing in the kernel holds it: a stored answer that would let the command run with no
    card is not read, and its own card offers this time only."""
    gate["sandbox"] = False
    command = "echo x > .git/hooks/pre-commit"
    if stored == "ask-all-text-grant":
        gate["ask_all"] = True
        await _store("command", "text:" + command)
    else:
        await _store("command", "unsandboxed:*", rule=stored == "rule")
    runs, frames, _ = await _dispatch(monkeypatch, {"command": command})
    assert len(frames) == 1 and frames[0]["options"] == ["once"]
    assert "Writes a file that runs later: .git/hooks/pre-commit" in frames[0]["title"]
    assert len(runs) == 1
    # An ordinary command is still answered by the same stored answer, with no card, as before.
    if stored != "ask-all-text-grant":
        runs, frames, _ = await _dispatch(monkeypatch, {"command": "ls"})
        assert (len(frames), len(runs)) == (0, 1)


async def test_a_yes_that_is_not_the_users_click_lets_nothing_run(execution_db, gate, monkeypatch):
    """Fails closed: a confirm callback that says yes with no recorded click (a remembered answer) runs nothing."""
    await _store("outside", "*")

    async def remembered(command, argv, **kw):
        permissions.LAST_DECISION.set(permissions.Decision(True, "grant", "conversation"))
        return True
    runs, _, result = await _dispatch(monkeypatch, {"command": "echo x > .git/hooks/pre-commit"}, confirm=remembered)
    assert runs == [] and ".git/hooks/pre-commit" in str(result)


async def test_the_fresh_outside_card_names_the_file(execution_db, gate, monkeypatch):
    runs, frames, _ = await _dispatch(monkeypatch, {"command": "echo x > .git/hooks/pre-commit",
                                                    "outside_sandbox": True, "why": "a hook the user asked for"})
    assert len(frames) == 1 and frames[0]["perm_kind"] == "outside"
    assert "Writes a file that runs later: .git/hooks/pre-commit" in frames[0]["title"]
    assert runs == [(True, False)]
    # An ordinary command's outside card has no such line.
    _, frames, _ = await _dispatch(monkeypatch, {"command": "ls", "outside_sandbox": True, "why": "x"})
    assert "runs later" not in frames[0]["title"]


@pytest.mark.parametrize("lang", sorted(card_purpose.TEXT))
def test_the_line_in_each_language(lang):
    title = card_purpose.phrase("echo x > .envrc", lang=lang, outside=True, run_later=[".envrc"])
    assert card_purpose.TEXT[lang]["fact"]["runsLater"].replace("{{file}}", ".envrc") in title
    git = card_purpose.phrase("git -c core.hooksPath=h commit", lang=lang, outside=True,
                              run_later=[tp.RUN_LATER_SETTING + "core.hooksPath"])
    assert card_purpose.TEXT[lang]["fact"]["runsLaterGit"].replace("{{name}}", "core.hooksPath") in git
    unsure = card_purpose.phrase("cp \"$F\" .", lang=lang, outside=True, run_later=[UNKNOWN])
    assert card_purpose.TEXT[lang]["fact"]["runsLaterUnsure"] in unsure
    # A line the reader doesn't understand says so already: no "may" line on top.
    assert card_purpose.TEXT[lang]["fact"]["runsLaterUnsure"] not in card_purpose.phrase(
        "eval x", lang=lang, outside=True, run_later=[UNKNOWN])
    assert "沙箱" not in "".join(card_purpose.TEXT[lang]["fact"][k] for k in ("runsLater", "runsLaterGit",
                                                                             "runsLaterUnsure"))

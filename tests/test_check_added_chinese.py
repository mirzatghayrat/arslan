"""LANG1: the added-lines Chinese check (scripts/check_added_chinese.py)."""
import subprocess

import pytest

from scripts import check_added_chinese as lang
from scripts.check_added_chinese import (
    DATA_PATHS,
    TRANSLATION_PATHS,
    glob_regex,
    line_fails,
    load_allowlist,
    main,
    parse_diff,
)

NEW_PROSE = "这一段是新写的中文说明，没有引号。"


# --- the rule: new Chinese prose fails on an English path ------------------


@pytest.mark.parametrize("path", [
    "docs/plans/0164/STY-reply-style.md",
    "server/orchestrator/arslan.py",
    "web/src/components/Sidebar.tsx",
    "desktop/src-tauri/src/lib.rs",
    "arslan/skills/bundled/skill-creator/SKILL.md",
    "evals/companion/README.md",  # a doc inside evals/ is prose, not input data
])
def test_new_chinese_prose_fails(path):
    assert line_fails(path, NEW_PROSE)


@pytest.mark.parametrize("line", [
    "# 这里是一条中文注释",
    "// 中文注释",
    "    /* 中文注释 */",
    "    x = 1  # 这里",
])
def test_a_chinese_comment_in_code_fails(line):
    assert line_fails("server/services/heartbeat.py" if "#" in line else "web/src/App.tsx", line)


def test_kana_and_hangul_are_not_checked():
    assert not line_fails("docs/notes.md", "ひらがな カタカナ 한국어")


# --- exception: quoted Chinese inside an English sentence ------------------


@pytest.mark.parametrize("line", [
    'The button says "设置" now.',
    "The button says '设置' now.",
    "The button says `设置` now.",
    "The button says “设置” now.",
    "The button says ‘设置’ now.",
    "The user wrote 「全屏时点 ✕ 关主窗口会黑屏，窗口消失」 on 10-28.",
    "Quoted in 『白角括号』 too.",
    "| `收件箱` | Inbox page |",
])
def test_quoted_chinese_inside_english_passes(line):
    assert not line_fails("docs/plans/0164/README.md", line)


@pytest.mark.parametrize("line", ["Ask ④参谋 to review it.", "⓪Plan and ②Main agree."])
def test_session_names_pass(line):
    assert not line_fails("docs/sessions.md", line)


@pytest.mark.parametrize("line", [
    '"设置"',  # quoted, but no English sentence around it
    "「设置」",
    'The 设置 button is unquoted.',
    "It's the 设置 button, don't quote it wrong.",  # apostrophes are not quotes
])
def test_unquoted_or_bare_chinese_fails(line):
    assert line_fails("docs/plans/0164/README.md", line)


def test_a_short_chinese_keyword_in_code_passes():
    assert not line_fails("server/orchestrator/tool_loop.py", '    if "没查到" in reply_text:')


def test_a_chinese_sentence_in_a_code_string_fails():
    """A prompt or UI copy in a string literal belongs in a translation table."""
    assert line_fails("server/orchestrator/arslan.py", '    prompt = "你是 Arslan，回答要简短。"')
    assert line_fails("server/orchestrator/arslan.py", '    "你是一个本地助手。"')


def test_a_comment_may_quote_a_chinese_sentence():
    assert not line_fails("server/orchestrator/tool_loop.py", '    # matches replies like "好的，我来查。" from the model')


# --- exception: translation files and tables, docs-site -----------------------


def _sample(glob: str) -> str:
    return glob.replace("**/", "a/b/").replace("**", "x/y.json").replace("*", "zh-CN")


@pytest.mark.parametrize("glob", TRANSLATION_PATHS)
def test_every_translation_path_passes_prose_and_comments(glob):
    path = _sample(glob)
    assert glob_regex(glob).match(path), path
    assert not line_fails(path, NEW_PROSE)
    assert not line_fails(path, "# " + NEW_PROSE)


# --- exception: data, tests, evals, fixtures ----------------------------------


@pytest.mark.parametrize("glob", DATA_PATHS)
def test_every_data_path_passes_data_lines(glob):
    path = _sample(glob)
    if path.endswith(".json.json"):
        path = path[: -len(".json")]
    assert glob_regex(glob).match(path), path
    assert not line_fails(path, f'    "{NEW_PROSE}",')


@pytest.mark.parametrize("path,comment", [
    ("tests/server/test_x.py", "# 中文注释"),
    ("web/src/components/x.test.tsx", "// 中文注释"),
    ("arslan/companion/content_policy.py", "# 中文注释"),
    ("desktop/bridge/Tests/BridgeCoreTests/X.swift", "// 中文注释"),
])
def test_a_chinese_comment_in_a_data_path_still_fails(path, comment):
    assert line_fails(path, comment)
    assert not line_fails(path, '# the input "中文注释" is the user\'s words')


def test_markdown_is_data_only_inside_fixtures():
    assert not line_fails("tests/fixtures/notes/a.md", NEW_PROSE)
    assert line_fails("tests/server/README.md", NEW_PROSE)


# --- old Chinese is not new -------------------------------------------------------


def test_an_edit_to_an_old_chinese_line_passes():
    old = "| D7 | AI 审批员 | **v0.1.65 做窄版，默认关。** |"
    new = "| D7 | AI 审批员 | **v0.1.65 做窄版，默认关。** **Superseded 2026-10-28.** |"
    assert not line_fails("docs/plans/x.md", new, removed=old)


def test_new_chinese_next_to_removed_old_chinese_fails():
    old = "| D7 | AI 审批员 | 默认关 |"
    new = "| D7 | AI 审批员 | 默认开，用户十月定的 |"
    assert line_fails("docs/plans/x.md", new, removed=old)


# --- escape hatches ----------------------------------------------------------------


def test_the_marker_passes_one_line():
    assert not line_fails("server/orchestrator/tool_loop.py", '    r"上图|已生成图",  # lang-check: allow (matches model output)')
    assert line_fails("server/orchestrator/tool_loop.py", '    r"上图|已生成图",')


def test_allowlist_entries_need_a_reason():
    patterns, errors = load_allowlist("# header\n\ndocs/legacy/**  # pre-rule archive\nweb/x.ts\n  # only a comment\n")
    assert patterns == ["docs/legacy/**"]
    assert len(errors) == 1 and ":4:" in errors[0]


def test_the_shipped_allowlist_loads_cleanly():
    with open(lang.ALLOWLIST_FILE, encoding="utf-8") as f:
        assert load_allowlist(f.read())[1] == []


def test_glob_star_stays_in_one_directory():
    assert glob_regex("docs/*.md").match("docs/a.md")
    assert not glob_regex("docs/*.md").match("docs/sub/a.md")
    assert glob_regex("docs/**").match("docs/sub/a.md")
    assert glob_regex("**/*.xcstrings").match("Localizable.xcstrings")
    assert glob_regex("**/*.xcstrings").match("a/b/Localizable.xcstrings")


# --- diff parsing ----------------------------------------------------------------------


def test_parse_diff_numbers_lines_and_keeps_header_like_content():
    diff = "\n".join([
        "diff --git a/q.sql b/q.sql",
        "index 1..2 100644",
        "--- a/q.sql",
        "+++ b/q.sql",
        "@@ -3 +3,2 @@",
        "--- 旧的注释",
        "+++ 新的一行",
        "+second",
        "diff --git a/gone.md b/gone.md",
        "deleted file mode 100644",
        "--- a/gone.md",
        "+++ /dev/null",
        "@@ -1 +0,0 @@",
        "-整个文件删了",
    ])
    added, removed = parse_diff(diff)
    assert [(a.path, a.line, a.text) for a in added] == [("q.sql", 3, "++ 新的一行"), ("q.sql", 4, "second")]
    assert "-- 旧的注释" in removed and "整个文件删了" in removed


# --- end to end in a real repository ------------------------------------------------------


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}.items():
        monkeypatch.setenv(k, v)
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.chdir(root)

    def git(*args):
        subprocess.run(["git", *args], check=True, capture_output=True)

    def write(path, text):
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    git("init", "-q", "-b", "main")
    write("docs/plan.md", "# Plan\n\n| D7 | 审批员 | 默认关 |\n")
    write("old/legacy.md", "旧文件\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "change")
    return root, git, write


def test_end_to_end_catches_an_added_line_and_passes_the_exceptions(repo, capsys):
    root, git, write = repo
    write("docs/plan.md", "# Plan\n\n| D7 | 审批员 | 默认关 | Superseded. |\n\nThe 收件箱 page.\n")
    write("web/src/locales/zh.json", '{"inbox": "收件箱"}\n')
    write("tests/test_input.py", 'CASES = ["帮我订机票"]\n')
    write("docs-site/sections/zh/01.html", "<p>概览</p>\n")
    write("docs/quote.md", "The label reads 「收件箱」 now.\n")
    git("mv", "old/legacy.md", "old/moved.md")
    git("add", "-A")
    git("commit", "-q", "-m", "change")

    assert main(["--base", "main"]) == 1
    out = capsys.readouterr().out
    assert "docs/plan.md:5: The 收件箱 page." in out
    assert out.count("docs/") == 2  # the failing line, plus the hint naming docs/sessions.md
    for passing in ("locales", "tests/test_input.py", "docs-site", "quote.md", "moved.md", "plan.md:3"):
        assert passing not in out


def test_end_to_end_marker_and_allowlist_clear_it(repo, capsys):
    root, git, write = repo
    write("docs/plan.md", "# Plan\n\n| D7 | 审批员 | 默认关 |\n\n收件箱 <!-- lang-check: allow -->\n")
    write("archive/notes.md", "新的归档笔记\n")
    write(".github/lang-check-allow.txt", "archive/**  # imported archive, kept verbatim\n")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    assert main(["--base", "main"]) == 0
    assert "no Chinese outside the exceptions" in capsys.readouterr().out


def test_end_to_end_an_allowlist_entry_without_a_reason_is_an_error(repo):
    root, git, write = repo
    write(".github/lang-check-allow.txt", "archive/**\n")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    assert main(["--base", "main"]) == 2


def test_end_to_end_an_unknown_base_is_an_error(repo):
    assert main(["--base", "no-such-ref"]) == 2

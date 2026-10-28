"""LANG1: the added-lines Chinese check (scripts/check_added_chinese.py)."""
import os
import pathlib
import shutil
import subprocess

import pytest
import yaml

from scripts import check_added_chinese as lang
from scripts.check_added_chinese import (
    DATA_PATHS,
    TRANSLATION_PATHS,
    glob_regex,
    line_fails,
    load_allowlist,
    main,
    parse_diff,
    too_broad,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]

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


def test_a_long_run_after_a_circled_digit_is_not_a_session_name():
    assert line_fails("docs/sessions.md", "See ①今天天气很好 ②我们去公园吧 here.")


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


@pytest.mark.parametrize("line", [
    "    x = 1  # 这是新的中文注释说明",
    '    CASES = ["你好"]  # 用户的问候',
])
def test_a_trailing_comment_in_a_test_file_still_fails(line):
    assert line_fails("tests/server/test_x.py", line)


@pytest.mark.parametrize("line", [
    '    CASES = ["你好", "#不是注释"]  # the user\'s greeting',
    '    """Checks that "中文" input is kept."""',
])
def test_data_with_an_english_comment_or_docstring_passes(line):
    assert not line_fails("tests/server/test_x.py", line)


def test_an_english_docstring_quoting_chinese_passes_in_product_code():
    assert not line_fails("server/services/x.py", '    """Matches replies that say "没查到"."""')
    # a docstring is prose, so a quoted Chinese sentence is a quote there
    assert not line_fails("server/services/x.py", '    """Matches replies like "好的，我来查。" from the model."""')
    assert line_fails("server/services/x.py", '    """这个函数检查中文回复"""')


def test_a_triple_quote_opening_chinese_test_data_passes():
    """Measured on #436: multi-line model output in tests/test_kernel_bench_m64.py."""
    assert not line_fails("tests/test_kernel_bench_m64.py", '"""| 文件 | 行 | 类型 | 说明 |')


def test_markdown_is_data_only_inside_fixtures():
    assert not line_fails("tests/fixtures/notes/a.md", NEW_PROSE)
    assert line_fails("tests/server/README.md", NEW_PROSE)


# --- old Chinese is not new -------------------------------------------------------


def test_an_edit_to_an_old_chinese_line_passes():
    old = "| D7 | AI 审批员 | **v0.1.65 做窄版，默认关。** |"
    new = "| D7 | AI 审批员 | **v0.1.65 做窄版，默认关。** **Superseded 2026-10-28.** |"
    assert not line_fails("docs/plans/x.md", new, removed=[old])


def test_new_chinese_next_to_removed_old_chinese_fails():
    old = "| D7 | AI 审批员 | 默认关 |"
    new = "| D7 | AI 审批员 | 默认开，用户十月定的 |"
    assert line_fails("docs/plans/x.md", new, removed=[old])


def test_a_phrase_cut_out_of_an_old_paragraph_is_new_chinese():
    old = "我们今天讨论了新的功能和用户的需求，然后定了下一步。"
    assert line_fails("docs/plans/x.md", "用户的需求", removed=[old])
    assert line_fails("docs/plans/x.md", "的", removed=[old])


# --- escape hatches ----------------------------------------------------------------


def test_the_marker_passes_one_line():
    assert not line_fails("server/orchestrator/tool_loop.py", '    r"上图|已生成图",  # lang-check: allow (matches model output)')
    assert line_fails("server/orchestrator/tool_loop.py", '    r"上图|已生成图",')


@pytest.mark.parametrize("glob", ["*", "**", "**/*", "**/*.md", "*.md", "docs/**", "docs/*.md", "web/*", "d?cs/x/**"])
def test_match_almost_everything_globs_are_rejected(glob):
    assert too_broad(glob)
    patterns, errors = load_allowlist(f"{glob}  # because")
    assert patterns == [] and "too broad" in errors[0]


@pytest.mark.parametrize("glob", ["docs/archive/**", "web/src/legacy/*.ts", "NOTICE", "docs/plans/old.md"])
def test_narrow_globs_and_exact_files_are_accepted(glob):
    assert not too_broad(glob)
    assert load_allowlist(f"{glob}  # because") == ([glob], [])


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
    assert removed == {"q.sql": ["-- 旧的注释"]}  # a deleted file excuses nothing


@pytest.mark.parametrize("header,path", [
    ("+++ b/docs/my notes.md\t", "docs/my notes.md"),
    ('+++ "b/docs/a\\"b.md"', 'docs/a"b.md'),
    ('+++ "b/docs/tab\\tx.md"', "docs/tab\tx.md"),
    ('+++ "b/docs/\\344\\270\\255.md"', "docs/\u4e2d.md"),
])
def test_parse_diff_reads_quoted_and_spaced_paths(header, path):
    added, _ = parse_diff("\n".join(["diff --git x y", header, "@@ -0,0 +1 @@", "+line"]))
    assert [a.path for a in added] == [path]


# --- end to end in a real repository ------------------------------------------------------


PLAN_TAIL = "".join(f"Step {n}: an English line that keeps rename detection honest.\n" for n in range(12))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)  # CI sets it; annotations have their own test
    # A user may have turned rename detection off; the checker must not depend on it.
    (tmp_path / "gitconfig").write_text("[diff]\n\trenames = false\n")
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
    write("docs/plan.md", "# Plan\n\n| D7 | 审批员 | 默认关 |\n" + PLAN_TAIL)
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


def test_end_to_end_the_published_docs_site_passes_and_docs_elsewhere_still_fail(repo, capsys):
    """Main CI 40716975056: #428's built pages under docs/docs/ failed while their source in
    docs-site/ passed. Kanji in the Japanese page count as Han, so it needs the exception too."""
    root, git, write = repo
    write("docs/docs/zh/index.html", "<p>Arslan 是一个本地优先的助手，所有记忆都留在这台 Mac 上。</p>\n")
    write("docs/docs/ja/index.html", "<p>Arslan はローカル優先のアシスタントです。記憶はこの Mac に残ります。</p>\n")
    write("docs/docs/index.html", '<a href="../docs/zh/" lang="zh-CN">简体中文</a><a href="../docs/ja/" lang="ja">日本語</a>\n')
    write("docs/sessions.md", "新的中文规矩\n")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    assert main(["--base", "main"]) == 1
    out = capsys.readouterr().out
    assert "docs/sessions.md:1: 新的中文规矩" in out
    assert "docs/docs/" not in out


def test_end_to_end_under_actions_a_failure_is_also_an_annotation(repo, capsys, monkeypatch):
    root, git, write = repo
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    write("docs/new.md", "English.\n新的中文\n")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    assert main(["--base", "main"]) == 1
    assert "::error file=docs/new.md,line=2::" in capsys.readouterr().out


def test_end_to_end_marker_and_allowlist_clear_it(repo, capsys):
    root, git, write = repo
    write("docs/plan.md", "# Plan\n\n| D7 | 审批员 | 默认关 |\n\n收件箱 <!-- lang-check: allow -->\n")
    write("docs/archive/notes.md", "新的归档笔记\n")
    write(".github/lang-check-allow.txt", "docs/archive/**  # imported archive, kept verbatim\n")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    assert main(["--base", "main"]) == 0
    out = capsys.readouterr().out
    assert "no Chinese outside the exceptions" in out
    # every line an escape hatch let through is in the log
    assert "docs/plan.md:5: allowed by the 'lang-check: allow' marker" in out
    assert "docs/archive/notes.md:1: allowed by the allowlist entry 'docs/archive/**'" in out


def test_end_to_end_a_match_everything_allowlist_is_an_error(repo):
    root, git, write = repo
    write(".github/lang-check-allow.txt", "**  # whatever\n")
    write("docs/new.md", "新的中文\n")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    assert main(["--base", "main"]) == 2


def test_end_to_end_deleting_one_file_does_not_excuse_another(repo, capsys):
    root, git, write = repo
    git("rm", "-q", "old/legacy.md")
    # the deleted file's exact line, in a file too different to be its rename
    write("docs/new.md", "旧文件\n" + PLAN_TAIL)
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    assert main(["--base", "main"]) == 1
    assert "docs/new.md:1: 旧文件" in capsys.readouterr().out


def test_end_to_end_chinese_removed_from_one_file_does_not_excuse_another(repo, capsys):
    root, git, write = repo
    write("docs/plan.md", "# Plan\n\n| D7 | Approver | Off by default |\n" + PLAN_TAIL)  # translated
    write("docs/other.md", "| D7 | 审批员 | 默认关 |\n")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    assert main(["--base", "main"]) == 1
    assert "docs/other.md:1:" in capsys.readouterr().out


def test_end_to_end_a_renamed_file_keeps_its_old_chinese(repo):
    root, git, write = repo
    git("mv", "docs/plan.md", "docs/plan-0162.md")
    write("docs/plan-0162.md", "# Plan\n\n| D7 | 审批员 | 默认关 | Superseded on 10-28. |\n" + PLAN_TAIL)
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    assert main(["--base", "main"]) == 0


def test_end_to_end_quoted_and_spaced_paths_are_checked(repo, capsys):
    root, git, write = repo
    write("docs/my notes.md", "新的中文\n")
    write('docs/a"b.md', "新的中文\n")
    write("desktop/App/My Strings.xcstrings", '{"中文": {}}\n')
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    assert main(["--base", "main"]) == 1
    out = capsys.readouterr().out
    assert "docs/my notes.md:1:" in out and 'docs/a"b.md:1:' in out
    assert "xcstrings" not in out


def test_end_to_end_an_attribute_cannot_hide_a_text_file(repo, capsys):
    root, git, write = repo
    write(".gitattributes", "*.md -diff\n")
    write("docs/new.md", "新的中文\n")
    (root / "docs/real.bin").write_bytes(b"\x00\x01" + "中文".encode() + b"\x00")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    assert main(["--base", "main"]) == 1
    out = capsys.readouterr().out
    assert "docs/new.md:1: 新的中文" in out and "real.bin" not in out


def test_end_to_end_an_allowlist_entry_without_a_reason_is_an_error(repo):
    root, git, write = repo
    write(".github/lang-check-allow.txt", "archive/**\n")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    assert main(["--base", "main"]) == 2


def test_end_to_end_an_unknown_base_is_an_error(repo):
    assert main(["--base", "no-such-ref"]) == 2


# --- the CI job's own shell, run from ci.yml --------------------------------------------


def _ci_script() -> str:
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"]
    assert jobs["language"]["permissions"] == {"contents": "read"}
    return next(step["run"] for step in jobs["language"]["steps"] if "run" in step)


@pytest.fixture
def ci_repo(repo):
    """A repository whose main already carries the checker, like main after this PR."""
    root, git, write = repo
    write("scripts/check_added_chinese.py", (ROOT / "scripts/check_added_chinese.py").read_text(encoding="utf-8"))
    write(".github/lang-check-allow.txt", "# empty\n")
    git("add", "-A")
    git("commit", "-q", "-m", "checker")
    git("branch", "-q", "-f", "main", "HEAD")

    def run(event="pull_request", before=""):
        if event == "pull_request":  # GitHub's test merge: first parent is the base tip
            git("checkout", "-q", "main")
            git("merge", "-q", "--no-ff", "-m", "test merge", "change")
        env = {**os.environ, "EVENT": event, "BEFORE": before, "RUNNER_TEMP": str(root.parent)}
        bash = shutil.which("bash")
        return subprocess.run([bash, "-c", _ci_script()], cwd=root, env=env, capture_output=True, text=True)

    return root, git, write, run


def test_ci_fails_a_pull_request_that_adds_chinese(ci_repo):
    root, git, write, run = ci_repo
    write("docs/new.md", "新的中文\n")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    r = run()
    assert r.returncode == 1, r.stdout + r.stderr
    assert "docs/new.md:1: 新的中文" in r.stdout


def test_ci_passes_an_english_pull_request_with_both_checkers(ci_repo):
    root, git, write, run = ci_repo
    write("docs/new.md", "English only.\n")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    r = run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "the base commit's checker" in r.stdout and "this change's checker" in r.stdout


def test_ci_a_pull_request_cannot_loosen_its_own_check(ci_repo):
    """The PR's own allowlist would pass it; the base commit's copy does not."""
    root, git, write, run = ci_repo
    write(".github/lang-check-allow.txt", "docs/archive/**  # imported archive\n")
    write("docs/archive/n.md", "新的中文\n")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    assert main(["--base", "main", "--head", "change"]) == 0
    r = run()
    assert r.returncode == 1, r.stdout + r.stderr
    assert "docs/archive/n.md:1:" in r.stdout


def test_ci_a_pull_request_cannot_loosen_the_script_either(ci_repo):
    root, git, write, run = ci_repo
    script = root / "scripts/check_added_chinese.py"
    script.write_text(script.read_text(encoding="utf-8").replace(
        "def line_fails(", "def line_fails(*a, **k):\n    return False\n\n\ndef _old_line_fails("), encoding="utf-8")
    write("docs/new.md", "新的中文\n")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    r = run()
    assert r.returncode == 1, r.stdout + r.stderr


@pytest.mark.parametrize("before", ["", "0" * 40, "1234567890abcdef1234567890abcdef12345678"])
def test_ci_a_push_without_a_usable_before_checks_nothing(ci_repo, before):
    root, git, write, run = ci_repo
    git("checkout", "-q", "main")
    r = run(event="push", before=before)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "nothing to check" in r.stdout


def test_ci_a_push_diffs_against_before(ci_repo):
    root, git, write, run = ci_repo
    git("checkout", "-q", "main")
    before = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    write("docs/new.md", "新的中文\n")
    git("add", "-A")
    git("commit", "-q", "-m", "direct push")
    r = run(event="push", before=before)
    assert r.returncode == 1, r.stdout + r.stderr

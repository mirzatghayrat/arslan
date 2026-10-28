"""Kernel bench M64 (v0.1.64): code-review tasks T13–T15, split/delegate/summarise T16 and its
one-step other side T17, and the report's same-task Pass^k. No model calls: every checker is
fed hand-written fake reviews and fake tool-call records."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.kernel_bench import (
    check_t13,
    check_t14,
    check_t15,
    check_t16,
    check_t17,
    fixture_t13,
    fixture_t14,
    fixture_t15,
    report,
    review_kit,
    runner,
    tool_record,
)

REVIEWS = {
    "T13": (check_t13, fixture_t13),
    "T14": (check_t14, fixture_t14),
    "T15": (check_t15, fixture_t15),
}


@pytest.fixture(autouse=True)
def _no_settle_wait(monkeypatch):
    monkeypatch.setattr(runner, "settle", lambda *a, **k: 0.0)


# ── the review repos and the planted bugs ─────────────────────────────────────


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


@pytest.mark.parametrize("task", sorted(REVIEWS))
def test_each_review_repo_is_a_pr_on_feature_and_the_folder_holds_no_answers(tmp_path, task):
    check, fixture = REVIEWS[task]
    fixture.fixture(str(tmp_path))
    repo = tmp_path / "repo"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["repo"]
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "feature"
    changed = set(_git(repo, "diff", "--name-only", "main", "feature").split())
    assert changed == {n for n, body in fixture.PR.items() if fixture.BASE.get(n) != body}
    assert _git(repo, "status", "--porcelain") == ""
    for name, body in fixture.head().items():
        assert (repo / name).read_text() == body
    files = {
        str(p.relative_to(repo)) for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts
    }
    assert files == set(fixture.head())  # the answer key (check.BUGS) is not in the folder


@pytest.mark.parametrize("task", sorted(REVIEWS))
def test_every_planted_bug_points_at_its_line_and_one_needs_context(task):
    check, fixture = REVIEWS[task]
    head = fixture.head()
    assert 3 <= len(check.BUGS) <= 4 and len({b.id for b in check.BUGS}) == len(check.BUGS)
    assert any(b.context for b in check.BUGS)
    for b in check.BUGS:
        lines = head[b.file].splitlines()
        first, last = b.lines
        assert 1 <= first <= last <= len(lines), b.id
        assert any(b.anchor in line for line in lines[first - 1 : last]), b.id
        assert b.file in fixture.PR and b.keywords, b.id  # the bug is in what the PR changed
        for path, (a, z) in b.also:
            assert 1 <= a <= z <= len(head[path].splitlines()), b.id
    for e in check.EXTRAS:
        assert all(1 <= a <= z <= len(head[path].splitlines()) for path, (a, z) in e.places), e.id


@pytest.mark.parametrize(
    "task,bug,caller,line",
    [
        ("T13", "P4", "shop/orders.py", "except OutOfStock:"),
        ("T15", "S4", "Sources/Notes/EditTracker.swift", "opened != current"),
    ],
)
def test_the_contract_change_bugs_break_a_caller_the_pr_does_not_touch(task, bug, caller, line):
    """②Main's review: P4 and S4 were visible in the diff. Now each is a contract the PR changes and
    a caller outside the PR that breaks; the caller is one of the bug's places."""
    check, fixture = REVIEWS[task]
    b = next(x for x in check.BUGS if x.id == bug)
    assert b.context and caller in fixture.BASE and caller not in fixture.PR
    ((a, z),) = [lines for path, lines in b.also if path == caller]
    assert any(line in text for text in fixture.head()[caller].splitlines()[a - 1 : z])
    assert fixture.head()[b.file] != fixture.BASE.get(b.file)  # the contract change is in the diff


# Hand-written fake reviews. Each "all caught" one uses another layout the matcher must read.
ALL_CAUGHT = {
    "T13": (
        "review.md",
        """shop/cart.py:29-29 | 单位错误 | apply_discount 要的是 0-100 的整数百分比，这里传了 0.15，会员几乎没有折扣
shop/cart.py:35-35 | off-by-one | 切片结束是 start + size - 1，每页少一行
shop/inventory.py:26-26 | 返回值错误 | 库存不足、回滚之后仍然 return True，调用方以为预留成功了
shop/orders.py:7-10 | 契约变化 | take() 现在库存不足时返回 False、不再抛 OutOfStock；这个没改的调用方还在等异常，缺货也报 placed
""",
    ),
    "T14": (
        "reply",
        """I reviewed the PR and found these bugs:

1. **src/limiter.ts, line 26**: `resetAt` mixes units. `nowSeconds()` is in seconds but `windowMs`
   is milliseconds, so a window lasts 1000 times too long.
2. **src/limiter.ts:29**: off by one. With `>` the limiter lets `limit + 1` requests through.
3. `src/settings.ts` lines 15-19: the async `forEach` callback is not awaited, so `saveAll`
   returns 0 before anything is stored. Use `for (const ...)` or `Promise.all`.
4. `src/settings.ts:9`: `Object.assign(DEFAULTS, user)` mutates the shared defaults, so every
   later user starts from the previous user's settings.
""",
    ),
    "T15": (
        "reply",
        """| 文件 | 行 | 类型 | 说明 |
|---|---|---|---|
| Sources/Notes/NotesModel.swift | 9 | 页码错误 | 服务器的页码从 1 开始（Paging.swift），第一页却传了 0 |
| NotesModel.swift | 39 | 崩溃 | Int(text)! 强制解包，用户输入非数字就崩溃 |
| NotesModel.swift | 25-27 | 循环引用 | 重复的 Timer 强引用 self，self 又持有 timer，永远不会释放 |
| Sources/Notes/Note.swift | 13-14 | 判等改变 | == 只比较 id；EditTracker.swift 用 != 判断有没有改动，改了标题和正文也检测不到 |
""",
    ),
}
NONE_CAUGHT = {
    "T13": "看过了，这个 PR 没有发现问题，可以合并。",
    "T14": "LGTM. The limiter and settings code look correct to me.",
    "T15": "## Review\n\nNo bugs found in Sources/Notes/NotesModel.swift.\n",
}


def _review(tmp_path, task, where, text):
    check, fixture = REVIEWS[task]
    fixture.fixture(str(tmp_path))
    if where == "review.md":
        (tmp_path / "review.md").write_text(text)
        return check.check(str(tmp_path), "已写入 review.md")
    return check.check(str(tmp_path), text)


@pytest.mark.parametrize("task", sorted(REVIEWS))
def test_a_review_that_catches_every_bug_scores_three_and_one_that_catches_none_zero(
    tmp_path, task
):
    good = _review(tmp_path / "good", task, *ALL_CAUGHT[task])
    planted = len(REVIEWS[task][0].BUGS)
    assert (good["score"], good["caught"], good["planted"], good["false_positives"]) == (
        3,
        planted,
        planted,
        0,
    ), good
    assert good["missed"] == [] and good["repo_changed"] == []
    none = _review(tmp_path / "none", task, "reply", NONE_CAUGHT[task])
    assert (none["score"], none["caught"], none["false_positives"]) == (0, 0, 0), none
    assert none["missed"] == [b.id for b in REVIEWS[task][0].BUGS]


def test_a_bug_that_is_not_there_counts_as_a_false_positive(tmp_path):
    where, text = ALL_CAUGHT["T13"]
    one = text + "shop/money.py:7-7 | 精度问题 | to_cents 用 Decimal 乘 100 会丢精度\n"
    res = _review(tmp_path / "one", "T13", where, one)
    assert (res["caught"], res["false_positives"], res["score"]) == (4, 1, 3)
    assert "to_cents" in res["false_positive_findings"][0]
    two = one + "tests/test_cart.py:5 | 逻辑错误 | Cart(owner=...) 参数名写错了\n"
    res = _review(tmp_path / "two", "T13", where, two)
    assert (res["caught"], res["false_positives"], res["score"]) == (4, 2, 2)


def test_the_right_line_in_the_wrong_file_or_a_far_line_in_the_right_file_catches_nothing(tmp_path):
    wrong_file = _review(
        tmp_path / "f", "T13", "review.md", "shop/money.py:29 | 单位 | 百分比要整数\n"
    )
    assert (wrong_file["caught"], wrong_file["false_positives"]) == (0, 1)
    far = _review(tmp_path / "l", "T13", "review.md", "shop/cart.py:4 | 单位 | 百分比要整数\n")
    assert (far["caught"], far["false_positives"]) == (0, 1)
    edge = _review(
        tmp_path / "e",
        "T13",
        "review.md",
        f"shop/cart.py:{26 - review_kit.TOLERANCE} | 单位 | 百分比\n",
    )
    assert edge["caught_ids"] == ["P1"]  # the tolerance is part of the rule


def test_the_right_place_with_a_type_it_does_not_name_is_neither_caught_nor_a_false_positive(
    tmp_path,
):
    res = _review(
        tmp_path, "T13", "review.md", "shop/cart.py:29 | 风格 | 0.15 是魔法数字，应该提成常量\n"
    )
    assert (res["caught"], res["false_positives"], res["located"]) == (0, 0, 1)


def test_findings_under_a_file_heading_inherit_the_file_and_a_line_less_remark_is_ignored(tmp_path):
    text = """## shop/cart.py

- 第 29 行：apply_discount 要整数百分比，传 0.15 等于几乎不打折。
- 第 35 行：切片少一，每页只有 size - 1 行。

shop/api.py 总体写得不错。
"""
    res = _review(tmp_path, "T13", "reply", text)
    assert (
        res["caught_ids"] == ["P1", "P2"] and res["false_positives"] == 0 and res["unlocated"] >= 1
    )


def test_partial_reviews_score_by_how_many_were_caught(tmp_path):
    lines = ALL_CAUGHT["T13"][1].splitlines(keepends=True)
    assert _review(tmp_path / "three", "T13", "review.md", "".join(lines[:3]))["score"] == 2
    assert _review(tmp_path / "one", "T13", "review.md", lines[0])["score"] == 1


def test_a_review_that_changes_the_repo_cannot_pass(tmp_path):
    fixture_t13.fixture(str(tmp_path))
    (tmp_path / "review.md").write_text(ALL_CAUGHT["T13"][1])
    cart = tmp_path / "repo" / "shop" / "cart.py"
    cart.write_text(cart.read_text().replace("0.15", "15"))
    res = check_t13.check(str(tmp_path), "")
    assert res["caught"] == 4 and res["score"] == 2 and res["repo_changed"] == ["shop/cart.py"]


def test_an_empty_review_file_falls_back_to_the_reply(tmp_path):
    fixture_t13.fixture(str(tmp_path))
    (tmp_path / "review.md").write_text("\n")
    res = check_t13.check(str(tmp_path), ALL_CAUGHT["T13"][1])
    assert res["source"] == "reply" and res["score"] == 3


# ── the tool-call record ──────────────────────────────────────────────────────


def _frames(run: Path, *tools: str) -> None:
    rows = [{"type": "history"}] + [
        {"type": "tool_call", "tool": t, "args_summary": "{}"} for t in tools
    ]
    Path(f"{run}.frames.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _transcript(home: Path, session: str, *tools: str, sidechain: tuple = ()) -> None:
    folder = home / ".claude" / "projects" / "-bench-runs-claude-code-T17-r1"
    folder.mkdir(parents=True, exist_ok=True)
    rows = [{"type": "user", "message": {"content": "go"}}]
    rows += [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "ok"},
                    {"type": "tool_use", "name": t, "input": {}},
                ]
            },
        }
        for t in tools
    ]
    rows += [
        {
            "type": "assistant",
            "isSidechain": True,
            "message": {"content": [{"type": "tool_use", "name": t, "input": {}}]},
        }
        for t in sidechain
    ]
    (folder / f"{session}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_the_tool_record_is_read_from_arslans_frames_and_claude_codes_transcript(tmp_path):
    run = tmp_path / "arslan-T17-r1"
    assert tool_record.calls("arslan", str(run), {}) is None  # no record is not "no calls"
    _frames(run, "read_file", "start_sub_session", "delegate_work")
    names = tool_record.calls("arslan", str(run), {})
    assert names == ["read_file", "start_sub_session", "delegate_work"]
    assert (tool_record.sub_sessions("arslan", names), tool_record.handoffs("arslan", names)) == (
        1,
        2,
    )
    home = tmp_path / "home"
    ctx = {"home": str(home), "session": "s-1"}
    assert tool_record.calls("claude-code", str(run), ctx) is None
    _transcript(
        home, "s-1", "Bash", "Task", sidechain=("Task", "Bash")
    )  # a subagent's own calls left out
    assert tool_record.calls("claude-code", str(run), ctx) == ["Bash", "Task"]
    assert tool_record.calls("hermes", str(run), ctx) is None


# ── T16 split, delegate, summarise ────────────────────────────────────────────


def _t16_done(run: Path, answers: dict, mixed: str | None = None) -> None:
    (run / "out").mkdir()
    for region, a in answers.items():
        extra = f"\n（顺便：south {answers['south']['total']}）" if region == mixed else ""
        total = f"{float(a['total']):,.2f}"  # thousands separators are fine
        (run / "out" / f"{region}.md").write_text(
            f"# {region}\n总销售额：{total}\n销量最高：{a['top']}{extra}\n"
        )
    (run / "summary.md").write_text(
        "".join(
            f"## {r}\n- 总销售额 {a['total']}\n- 最畅销 {a['top']}\n" for r, a in answers.items()
        )
    )


def test_t16_needs_every_part_the_summary_and_two_to_four_sub_sessions(tmp_path):
    params = check_t16.fixture(str(tmp_path))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["regions"]
    answers = params["answers"]
    assert len({a["total"] for a in answers.values()}) == 3
    every = "".join(p.read_text() for p in tmp_path.rglob("*.csv"))
    assert all(
        a["total"] not in every for a in answers.values()
    )  # the answers stay with the runner
    _t16_done(tmp_path, answers)
    three = ["read_file"] + ["start_sub_session"] * 3
    assert check_t16.check(str(tmp_path), params, three, "arslan")["score"] == 3
    assert (
        check_t16.check(str(tmp_path), params, ["read_file"], "arslan")["score"] == 2
    )  # did it alone
    assert check_t16.check(str(tmp_path), params, ["start_sub_session"] * 5, "arslan")["score"] == 2
    assert check_t16.check(str(tmp_path), params, None, "arslan")["score"] == 2  # cannot count them
    assert (
        check_t16.check(str(tmp_path), params, ["Task", "Task"], "claude-code")["sub_sessions"] == 2
    )


def test_t16_a_part_holding_another_regions_answer_or_a_missing_summary_cannot_pass(tmp_path):
    params = check_t16.fixture(str(tmp_path / "a"))
    _t16_done(tmp_path / "a", params["answers"], mixed="north")
    res = check_t16.check(str(tmp_path / "a"), params, ["start_sub_session"] * 3, "arslan")
    assert res["score"] == 1 and res["parts_right"] == ["south", "west"]
    params = check_t16.fixture(str(tmp_path / "b"))
    _t16_done(tmp_path / "b", params["answers"])
    (tmp_path / "b" / "summary.md").unlink()
    assert (
        check_t16.check(str(tmp_path / "b"), params, ["start_sub_session"] * 3, "arslan")["score"]
        == 1
    )
    assert check_t16.check(str(tmp_path / "c"), params, [], "arslan")["score"] == 0


# ── T17 one step, no hand-off ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "who,names,right,score",
    [
        ("arslan", ["read_file", "write_file"], True, 3),
        (
            "arslan",
            ["read_file", "start_sub_session", "write_file"],
            True,
            0,
        ),  # opened a sub-session
        ("arslan", ["delegate_work"], True, 0),  # handed it off another way
        ("arslan", [], False, 1),
        ("arslan", None, True, 0),  # no record: cannot show it did not
        ("claude-code", ["Read", "Write"], True, 3),
        ("claude-code", ["Agent", "Write"], True, 0),
    ],
)
def test_t17_handing_off_a_one_step_request_scores_zero(tmp_path, who, names, right, score):
    params = check_t17.fixture(str(tmp_path))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["prices.txt"]
    total = sum(float(x) for x in (tmp_path / "prices.txt").read_text().split())
    assert f"{total:.2f}" == params["sum"]
    (tmp_path / "answer.txt").write_text((params["sum"] if right else "0.00") + "\n")
    assert check_t17.check(str(tmp_path), params, names, who)["score"] == score


# ── runner wiring ─────────────────────────────────────────────────────────────


def test_the_new_prompts_name_their_folders():
    prompts = json.loads((runner.HERE / "prompts.json").read_text())
    for task in ("T13", "T14", "T15"):
        assert (
            "{dir}/repo" in prompts[task]
            and "{dir}/review.md" in prompts[task]
            and "feature" in prompts[task]
        )
    assert (
        "{dir}/out/" in prompts["T16"]
        and "{dir}/summary.md" in prompts["T16"]
        and "子会话" in prompts["T16"]
    )
    assert "{dir}/answer.txt" in prompts["T17"] and "子会话" not in prompts["T17"]
    for task in ("T13", "T16", "T17"):
        prompts[task].format(dir="/r")  # no stray braces


def test_t16_is_unsupported_for_arslan_until_sub_and_both_for_entrants_without_a_tool_record(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner, "command", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run"))
    )
    prompts = json.loads((runner.HERE / "prompts.json").read_text())
    for task, who in [("T16", w) for w in ("arslan", "arslan-legacy", "hermes", "goose")] + [
        ("T17", "hermes"),
        ("T17", "goose"),
    ]:
        rec = runner.run_one(task, who, 1, prompts, "sb")
        assert (
            rec["check"]["unsupported"] and not rec["passed"] and rec["usage"]["usd_peak"] == 0
        ), (task, who)
    assert "SUB" in runner.run_one("T16", "arslan", 2, prompts, "sb")["check"]["note"]
    assert "tool-call record" in runner.run_one("T16", "hermes", 2, prompts, "sb")["check"]["note"]
    assert all("T17" not in runner.UNSUPPORTED[w] for w in ("arslan", "arslan-legacy"))


def test_t17_runs_for_arslan_and_delegate_work_is_a_hand_off(tmp_path, monkeypatch):
    """②Main's review, point 5: delegate_work exists before SUB, so T17 has an Arslan baseline."""
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    for tools, passed in (([], True), (["delegate_work"], False)):
        frames = "\n".join(
            json.dumps({"type": "tool_call", "tool": t, "args_summary": "{}"})
            for t in ["read_file", *tools]
        )
        script = (
            "import json, pathlib; run = pathlib.Path.cwd(); "
            "total = sum(float(x) for x in (run / 'prices.txt').read_text().split()); "
            "(run / 'answer.txt').write_text(f'{total:.2f}'); "
            f"pathlib.Path(str(run) + '.frames.jsonl').write_text({json.dumps(frames)}); "
            "print(json.dumps({'end': 'done', 'final': 'ok'}))"
        )
        monkeypatch.setattr(
            runner, "command", lambda *a, s=script, **k: ([sys.executable, "-c", s], {})
        )
        rec = runner.run_one("T17", "arslan", 1, {"T17": "add {dir}"}, "sb")
        assert rec["passed"] is passed and rec["check"]["handoffs"] == len(tools), rec["check"]


def test_run_one_scores_a_review_and_a_claude_code_one_step_run(tmp_path, monkeypatch):
    """Through run_one with stub drivers: T13's fixture and checker are wired, and T17 reads the
    Claude Code session the runner started (its transcript under the bench HOME)."""
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    review = json.dumps(ALL_CAUGHT["T13"][1])
    script = (
        "import json, pathlib; pathlib.Path('review.md').write_text(" + review + "); "
        "print(json.dumps({'end': 'done', 'final': 'ok'}))"
    )
    monkeypatch.setattr(runner, "command", lambda *a, **k: ([sys.executable, "-c", script], {}))
    rec = runner.run_one("T13", "arslan", 1, {"T13": "review {dir}/repo"}, "sb")
    assert rec["passed"] and (rec["check"]["caught"], rec["check"]["planted"]) == (4, 4)
    assert rec["rate_limited_429"] == 0

    def claude(who, label, run, prompt, sb, *, session=None, **k):
        _transcript(
            tmp_path / "home" / who,
            session,
            "Read",
            *(["Task"] if "hand" in label else []),
            "Write",
        )
        answer = (Path(run) / "prices.txt").read_text().split()
        total = f"{sum(float(x) for x in answer):.2f}"
        return [
            sys.executable,
            "-c",
            f"open('answer.txt', 'w').write('{total}'); print('{{}}')",
        ], {}

    monkeypatch.setattr(runner, "command", claude)
    assert runner.run_one("T17", "claude-code", 1, {"T17": "add {dir}"}, "sb")["passed"]
    monkeypatch.setattr(runner, "ROUND", "hand")
    rec = runner.run_one("T17", "claude-code", 1, {"T17": "add {dir}"}, "sb")
    assert not rec["passed"] and rec["check"]["handoffs"] == 1


def test_a_runs_429_answers_are_counted_from_the_meters_log(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    row = {"model": "deepseek-v4-pro", "secs": 1.0, "out": 0, "hit": 0, "miss": 0, "usd_peak": 0.0}
    (tmp_path / "usage.jsonl").write_text(
        "\n".join(
            json.dumps(row | r)
            for r in (
                {"cand": "arslan-T16-r1", "t": 100.0, "status": 429},
                {"cand": "arslan-T16-r1", "t": 101.0, "status": 200},
                {"cand": "arslan-T16-r1", "t": 102.0, "status": 429},
                {"cand": "hermes-T16-r1", "t": 102.0, "status": 429},
                {"cand": "arslan-T16-r1", "t": 10.0, "status": 429},
            )
        )
        + "\n"
    )
    assert runner.rate_limited("arslan-T16-r1", since=50.0) == 2


# ── report: same-task Pass^k and the review columns ───────────────────────────


def _rec(task, who, n, passed, check=None, model="deepseek-v4-pro", run=""):
    return {
        "task": task,
        "entrant": who,
        "repeat": n,
        "passed": passed,
        "rc": 0,
        "model": model,
        "judge": 2,
        "run": run or f"{who}-{task}-r{n}",
        "check": check or {"score": 3 if passed else 0},
        "usage": {"usd_peak": 0.1, "span_s": 60.0, "model_calls": 10},
    }


def test_same_task_pass_k_counts_only_tasks_both_sides_support_next_to_the_old_figure():
    unsupported = {"score": 0, "unsupported": True}
    recs = []
    for n in (1, 2, 3):
        recs += [
            _rec("T1", "arslan", n, True),
            _rec("T1", "hermes", n, True),
            _rec("T2", "arslan", n, False),
            _rec("T2", "hermes", n, True),
            _rec("T8", "arslan", n, True),
            _rec("T8", "hermes", n, False, unsupported),
            _rec(
                "T5", "arslan", n, True, model="claude-sonnet-5"
            ),  # another model: its own comparison
            _rec("T5", "claude-code", n, n < 3, model="claude-sonnet-5"),
        ]
    by = {(t["entrant"], t["model"]): t for t in report.totals(report.summarise(recs))}
    assert (
        by["arslan", "deepseek-v4-pro"]["pass_all"],
        by["arslan", "deepseek-v4-pro"]["tasks"],
    ) == (2, 3)
    assert (
        by["hermes", "deepseek-v4-pro"]["pass_all"],
        by["hermes", "deepseek-v4-pro"]["tasks"],
    ) == (2, 3)
    assert by["arslan", "deepseek-v4-pro"]["same"] == ["T1", "T2"]
    assert (
        by["arslan", "deepseek-v4-pro"]["same_pass_all"],
        by["hermes", "deepseek-v4-pro"]["same_pass_all"],
    ) == (1, 2)
    assert (
        by["arslan", "claude-sonnet-5"]["same_pass_all"],
        by["claude-code", "claude-sonnet-5"]["same_pass_all"],
    ) == (1, 0)
    text = report.render_totals(report.summarise(recs))
    assert "| arslan | deepseek-v4-pro | 3 | 2/3 | 1/2 | T1 T2 |" in text


def test_the_report_sums_caught_planted_and_false_positives_for_review_tasks_and_keeps_one_round():
    recs = [
        _rec(
            "T13",
            "arslan",
            n,
            n == 1,
            {
                "score": 3 if n == 1 else 1,
                "caught": 4 if n == 1 else 1,
                "planted": 4,
                "false_positives": n - 1,
            },
            run=f"arslan-T13-r{n}-m64",
        )
        for n in (1, 2, 3)
    ] + [_rec("T9", "arslan", 1, True, run="arslan-T9-r1-other")]
    text = report.render(report.summarise(report.in_round(recs, "m64")))
    assert (
        "| T13 | arslan | deepseek-v4-pro | no | 1/3 |" in text
        and "| 6/12 | 3 |" in text
        and "T9" not in text
    )
    assert "| — | — |" in report.render(report.summarise([recs[-1]]))


# ── ②Main's review of #436: probes that scored a wrong answer as a pass ───────

PROBE_A = (
    "src/limiter.ts:26 | 单位 | `resetAt` adds `windowMs` (milliseconds) to `nowSeconds()` (seconds),"
    " so `now >= bucket.resetAt` waits 1000 times too long\n"
    "src/settings.ts:15-19 | async | the async forEach callback is not awaited,"
    " so saveAll resolves before the writes\n"
    "src/settings.ts:9 | shared state | Object.assign mutates the shared DEFAULTS object\n"
)
PROBE_B_EXTRA = "shop/api.py:18 | 金额 | the member total is no longer a whole number of cents\n"


def test_probe_a_a_unit_finding_quoting_a_comparison_does_not_also_catch_the_off_by_one(tmp_path):
    res = _review(tmp_path, "T14", "review.md", PROBE_A)
    assert (res["caught"], res["planted"], res["missed"], res["score"]) == (3, 4, ["T2"], 2), res


def test_probe_b_a_generic_word_on_another_line_does_not_catch_a_bug_it_never_names(tmp_path):
    lines = ALL_CAUGHT["T13"][1].splitlines(keepends=True)
    res = _review(tmp_path, "T13", "review.md", "".join(lines[:3]) + PROBE_B_EXTRA)
    assert (res["caught"], res["planted"], res["missed"], res["score"]) == (3, 4, ["P4"], 2), res


def test_probe_d_t16_a_wrong_top_product_fails_even_when_the_file_lists_every_product(tmp_path):
    params = check_t16.fixture(str(tmp_path))
    (tmp_path / "out").mkdir()
    table = "| product | qty |\n|---|---|\n" + "".join(f"| {p} | 1 |\n" for p in check_t16.PRODUCTS)
    summary = ""
    for region, a in params["answers"].items():
        wrong = next(p for p in check_t16.PRODUCTS if p != a["top"])
        claim = f"总销售额：{a['total']}\n销量最高：{wrong}\n\n{table}"
        (tmp_path / "out" / f"{region}.md").write_text(f"# {region}\n{claim}")
        summary += f"## {region}\n{claim}\n"
    (tmp_path / "summary.md").write_text(summary)
    res = check_t16.check(str(tmp_path), params, ["Task"] * 3, "claude-code")
    assert res["score"] < 3 and res["parts_right"] == [] and res["summary_covers"] == [], res


def test_t16_the_top_product_comes_from_the_line_that_claims_it():
    assert check_t16.claims_top("| fan | 3 |\n| lamp | 9 |\n销量最高：lamp", "lamp")
    assert not check_t16.claims_top("| fan | 3 |\n| lamp | 9 |\n销量最高：fan", "lamp")
    assert not check_t16.claims_top("lamp 卖得多\n| lamp | 9 |", "lamp")  # no line claims it
    assert not check_t16.claims_top("top: lamp\nbest seller: fan", "lamp")  # two claims disagree
    assert check_t16.claims_top("top product: lamp (most units)\nfans of the shop", "lamp")


def _bugs_two_overlapping():
    from scripts.kernel_bench.review_kit import Bug

    return (
        Bug("A", "x.py", (10, 12), "unit", ("unit",), "a"),
        Bug("B", "x.py", (14, 14), "off by one", ("off by one",), "b"),
    )


def test_a_finding_credits_at_most_one_bug_the_nearest_by_line():
    bugs = _bugs_two_overlapping()
    both = "x.py:12 | wrong unit, and also off by one\n"
    assert review_kit.score(both, bugs, ["x.py"])["caught_ids"] == [
        "A"
    ]  # 12 is in A, B only by tolerance
    far = "x.py:14 | wrong unit\n"  # inside B: A is not credited through the tolerance
    res = review_kit.score(far, bugs, ["x.py"])
    assert res["caught_ids"] == [] and res["located"] == 1
    assert res["findings"] == [
        {"files": ["x.py"], "lines": "14-14", "verdict": "located", "id": "B"}
    ]


def test_keywords_in_inline_code_or_a_fenced_block_do_not_name_a_type():
    bugs = _bugs_two_overlapping()
    inline = "x.py:14 | see `# off by one` here\n"
    assert review_kit.score(inline, bugs, ["x.py"])["caught_ids"] == []
    fenced = "x.py:14 has a problem:\n```\n# off by one\n```\n"
    assert review_kit.score(fenced, bugs, ["x.py"])["caught_ids"] == []
    prose = "x.py:14 is off by one: `count > limit`\n"
    assert review_kit.score(prose, bugs, ["x.py"])["caught_ids"] == ["B"]
    in_fence_cite = (
        "```\nx.py:14\n```\nThat line is off by one.\n"  # the place may be quoted, the type not
    )
    assert review_kit.score(in_fence_cite, bugs, ["x.py"])["caught_ids"] == ["B"]


def test_an_ascii_keyword_does_not_match_inside_an_identifier():
    assert not review_kit.names("nowseconds is called here", ("seconds",))
    assert review_kit.names("it is in seconds", ("seconds",))
    assert review_kit.names("this mutates defaults", ("mutat",))  # a keyword may be a stem


PROBE_C_EXTRAS = (
    "src/index.ts:1-7 | ESM | relative imports have no .js extension, Node's ESM resolution fails under type: module\n"
    "src/limiter.ts:17 | memory | buckets are never pruned, the map grows without bound\n"
)


def test_probe_c_true_flaws_that_were_not_planted_cost_nothing(tmp_path):
    res = _review(tmp_path / "c", "T14", "reply", ALL_CAUGHT["T14"][1] + PROBE_C_EXTRAS)
    assert (res["caught"], res["false_positives"], res["extra"], res["score"]) == (4, 0, 2, 3), res
    swift = (
        ALL_CAUGHT["T15"][1]
        + "| NotesModel.swift | 45 | 错误处理 | fetch 失败时直接 return，错误被静默忽略 |\n"
    )
    res = _review(tmp_path / "s", "T15", "reply", swift)
    assert (res["caught"], res["false_positives"], res["extra"]) == (4, 0, 1), res
    made_up = "src/index.ts:3 | 类型 | exports a type that does not exist\n"  # near an extra, not its kind
    assert _review(tmp_path / "m", "T14", "reply", made_up)["false_positives"] == 1

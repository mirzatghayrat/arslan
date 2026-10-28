"""STY read test (v0.1.64): prompts, fixture and the side-by-side page. No model calls."""

import base64
import html
import json
import re
import subprocess
import sys

import pytest

from scripts.kernel_bench import fixture_sty, runner, sty_read

# The 20 prompts the plan fixed (⓪Plan, 2026-10-28). Pinned here so a changed or added prompt is a
# visible diff, reviewed like any other test input.
APPROVED = {
    1: "今天好累，开了一天会。",
    2: "我在想要不要换一个方向做这个项目，有点犹豫。",
    3: "周末想出去走走，你觉得爬山还是看展好？",
    4: "刚被同事说了一句，有点不开心。",
    5: "你还记得我上次说的那个想法吗？",
    6: "Long day. Not sure I got anything done.",
    7: "I'm torn between learning Rust and getting better at Swift. Thoughts?",
    8: "Can you keep me company for a bit while my build runs?",
    9: "I finally fixed the bug I was stuck on for two days!",
    10: "Remind me about this tomorrow.",
    11: "把 notes.md 里的会议纪要整理成三条要点，写进 summary.md。",
    12: "把 config.json 里的 timeout 改成 30，然后告诉我改了什么。",
    13: "跑一下 python3 broken.py，看看为什么报错，告诉我原因。",
    14: "这个文件夹里有哪些文件？按大小排一下。",
    15: "帮我把 data.csv 的第二列加总。",
    16: "Rename every .txt file in this folder to .md and tell me what you did.",
    17: "Read todo.md and tell me which items are done.",
    18: "Run python3 broken.py and explain the error.",
    19: "Make a short report of what's in data.csv: rows, columns, and the totals.",
    20: "Fix the typo in the first line of README.md.",
}
# Capitalised words an English prompt may use mid-sentence: languages and file names, no people.
PROPER = {"Rust", "Swift", "README"}
# Words that would point at a person in a Chinese prompt (a title or form of address).
ZH_PERSON = re.compile(
    r"先生|女士|老师|老板|经理|总监|[小老阿][王李张刘陈杨黄赵周吴徐孙马朱胡郭何林罗高郑]"
)


def test_prompts_are_the_twenty_approved_ones():
    items = sty_read.load_prompts()
    assert len(items) == 20
    assert len({p["id"] for p in items}) == 20
    assert {p["id"]: p["prompt"] for p in items} == APPROVED
    assert sum(p["kind"] == "chat" for p in items) == 10
    assert sum(p["kind"] == "task" for p in items) == 10
    for kind in ("chat", "task"):
        langs = [p["lang"] for p in items if p["kind"] == kind]
        assert langs.count("zh") == 5 and langs.count("en") == 5
    # Language tags match the text: a zh prompt has CJK in it, an en prompt has none.
    for p in items:
        assert bool(re.search(r"[一-鿿]", p["prompt"])) == (p["lang"] == "zh"), p["id"]
    # Tasks, and only tasks, run on the fixture folder.
    assert all(p["needs_fixture"] == (p["kind"] == "task") for p in items)
    # The two memory-promise prompts carry what the reader must check.
    assert {p["id"] for p in items if p.get("watch")} == {5, 10}


def test_no_prompt_asks_about_real_people():
    for p in sty_read.load_prompts():
        text = p["prompt"]
        assert "@" not in text and not re.search(r"\d{3}[- ]?\d{4}", text), p["id"]
        if p["lang"] == "en":
            sentences = re.split(r"(?<=[.!?])\s+", text)
            words = [w for s in sentences for w in re.findall(r"\b[A-Z][A-Za-z]+", s)[1:]]
            assert set(words) <= PROPER, (p["id"], words)
        else:
            assert not ZH_PERSON.search(text), p["id"]
            assert not re.search(r"\b[A-Z][a-z]+\b", text), p["id"]  # no Latin names either


def test_fixture_builds_the_folder(tmp_path):
    facts = fixture_sty.fixture(str(tmp_path / "run"))
    root = tmp_path / "run"
    names = {p.name for p in root.iterdir()}
    assert names == {
        "notes.md",
        "config.json",
        "broken.py",
        "data.csv",
        "todo.md",
        "README.md",
        "draft.txt",
        "log.txt",
        "list.txt",
    }
    notes = (root / "notes.md").read_text().splitlines()
    assert 10 <= len(notes) <= 16
    assert sum(line.lstrip("0123456789. ").startswith("Decision:") for line in notes) == 3
    assert json.loads((root / "config.json").read_text())["timeout"] == 10
    rows = (root / "data.csv").read_text().splitlines()
    assert len(rows) == 6 and all(len(r.split(",")) == 3 for r in rows)  # header + 5 rows x 3
    assert sum(int(r.split(",")[1]) for r in rows[1:]) == facts["csv_column2_total"] == 90
    todo = (root / "todo.md").read_text()
    assert todo.count("- [x]") == 2 and todo.count("- [ ]") == 2
    assert (root / "README.md").read_text().splitlines()[0] == "# Serach service"
    assert len({p.name for p in root.glob("*.txt")}) == 3
    # Every size differs, so "sort by size" (prompt 14) has one right order.
    sizes = [p.stat().st_size for p in root.iterdir()]
    assert len(set(sizes)) == len(sizes)
    assert facts["sizes"] == {p.name: p.stat().st_size for p in root.iterdir()}
    # broken.py fails with the error the fact names, and nothing outside the folder is needed.
    done = subprocess.run([sys.executable, "broken.py"], cwd=root, capture_output=True, text=True)
    assert done.returncode != 0 and facts["broken_error"] in done.stderr
    # Deterministic: a second build is byte for byte the same.
    again = tmp_path / "again"
    fixture_sty.fixture(str(again))
    assert all((root / n).read_bytes() == (again / n).read_bytes() for n in names)
    # No personal data: no addresses, no phone numbers.
    for n in names:
        text = (root / n).read_text()
        assert "@" not in text and not re.search(r"\d{3}[- ]\d{4}", text), n


def _replies(label: str, mark: str, skip: set[int] = frozenset()) -> dict:
    return {
        "label": label,
        "head": {"sha": f"{label}-sha", "branch": label},
        "model": "deepseek-v4-pro",
        "round": "test",
        "replies": [
            {
                "id": p["id"],
                "kind": p["kind"],
                "lang": p["lang"],
                "prompt": p["prompt"],
                "reply": f"{mark} reply to {p['id']} <b>&",
                "end": "done" if p["id"] != 10 else "task_waiting_user",
                "cards": ["propose_schedule"] if p["id"] == 10 else [],
            }
            for p in sty_read.load_prompts()
            if p["id"] not in skip
        ],
    }


def _page(tmp_path, seed=7, skip_after=frozenset()):
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    before.write_text(json.dumps(_replies("before", "BEFORE-MARK")), encoding="utf-8")
    after.write_text(json.dumps(_replies("after", "AFTER-MARK", skip_after)), encoding="utf-8")
    out = tmp_path / "read.html"
    key = sty_read.compare(before, after, out, seed=seed)
    return out.read_text(encoding="utf-8"), key, out


def test_compare_page_has_every_prompt_both_replies_and_the_key(tmp_path):
    page, key, out = _page(tmp_path)
    for p in sty_read.load_prompts():
        assert html.escape(p["prompt"]) in page
        for mark in ("BEFORE-MARK", "AFTER-MARK"):
            assert html.escape(f"{mark} reply to {p['id']} <b>&") in page
        for choice in ("better", "same", "worse"):
            assert f'name="r{p["id"]}" value="{choice}"' in page
    assert page.count('class="row"') == 20
    # Reply text is escaped, never markup.
    assert "<b>&" not in page
    # Labels are hidden: the words before/after never name a column.
    assert "<h3>before" not in page.lower() and "<h3>after" not in page.lower()
    # The key is in the page (base64, not readable at a glance) and next to it, and they agree.
    encoded = re.search(r'id="sty-key">([^<]+)<', page).group(1)
    assert json.loads(base64.b64decode(encoded)) == key
    assert json.loads(out.with_suffix(".key.json").read_text()) == key
    assert key["seed"] == 7 and len(key["rows"]) == 20
    assert all({r["a"], r["b"]} == {"before", "after"} for r in key["rows"])
    # Each row's A column holds the reply the key names.
    for row in key["rows"]:
        section = re.search(rf'data-id="{row["id"]}".*?</section>', page, re.S).group(0)
        a_side = section.split("<h3>B</h3>")[0]
        assert f"{row['a'].upper()}-MARK reply to {row['id']} " in a_side
    # Light and dark both set the body's background and text colour.
    assert "prefers-color-scheme: dark" in page
    assert re.search(r"body \{[^}]*background: var\(--bg\);[^}]*color: var\(--fg\)", page)
    # Self-contained: nothing loaded from elsewhere.
    assert not re.search(r'(src|href)="https?:', page)
    # Prompt 10's schedule card and its unclean end are shown to the reader.
    assert (
        "schedule card (the bench declined it)" in page and "run ended: task_waiting_user" in page
    )


def test_compare_shuffle_is_recorded_and_seeded(tmp_path):
    _, key1, _ = _page(tmp_path, seed=1)
    _, key1b, _ = _page(tmp_path, seed=1)
    orders = {
        tuple(
            r["a"]
            for r in sty_read.compare(
                tmp_path / "before.json", tmp_path / "after.json", tmp_path / f"p{s}.html", seed=s
            )["rows"]
        )
        for s in range(8)
    }
    assert key1 == key1b
    assert len(orders) > 1  # the seed changes the order
    assert all(len({a for a in o}) == 2 for o in orders)  # both sides land in column A somewhere


def test_compare_marks_a_missing_reply_and_refuses_another_prompt(tmp_path):
    page, _, _ = _page(tmp_path, skip_after={3})
    assert "(no reply recorded)" in page
    bad = _replies("after", "AFTER-MARK")
    bad["replies"][0]["prompt"] = "something else"
    (tmp_path / "after.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(SystemExit):
        sty_read.compare(tmp_path / "before.json", tmp_path / "after.json", tmp_path / "x.html")
    with pytest.raises(SystemExit):  # the two files given the wrong way round
        sty_read.compare(tmp_path / "after.json", tmp_path / "before.json", tmp_path / "x.html")


def test_tally_unblinds_through_the_key(tmp_path):
    _, key, _ = _page(tmp_path)
    by_id = {r["id"]: r for r in key["rows"]}
    first_b_after = next(r for r in key["rows"] if r["b"] == "after")["id"]
    first_b_before = next(r for r in key["rows"] if r["b"] == "before")["id"]
    rows = [{**r, "choice": None, "note": ""} for r in key["rows"]]
    for r in rows:
        if r["id"] in (first_b_after, first_b_before):
            r["choice"] = "better"
    verdicts = tmp_path / "v.json"
    verdicts.write_text(json.dumps({"page": key["page"], "rows": rows}), encoding="utf-8")
    out = sty_read.tally(verdicts)
    got = {r["id"]: r["after_vs_before"] for r in out["rows"]}
    assert by_id[first_b_after]["b"] == "after" and got[first_b_after] == "better"
    assert got[first_b_before] == "worse"  # B was before and better, so after is worse
    assert out["totals"]["all"] == {"better": 1, "same": 0, "worse": 1, "unjudged": 18}


def test_run_label_and_preflight(monkeypatch, tmp_path):
    assert sty_read.run_label("before", 5, "r1") == "arslan-STY05-before-r1"
    monkeypatch.delenv("BENCH_SANDBOX", raising=False)
    with pytest.raises(SystemExit, match="BENCH_SANDBOX"):
        sty_read.preflight(tmp_path, "deepseek-v4-pro")
    monkeypatch.setenv("BENCH_SANDBOX", "none")
    monkeypatch.setattr(runner, "ROUND", "")
    with pytest.raises(SystemExit, match="BENCH_ROUND"):
        sty_read.preflight(tmp_path, "deepseek-v4-pro")
    monkeypatch.setattr(runner, "ROUND", "r1")
    with pytest.raises(SystemExit, match="checkout"):
        sty_read.preflight(tmp_path, "deepseek-v4-pro")


def test_run_prompt_goes_through_the_runner(monkeypatch, tmp_path):
    """No instance and no model: the runner's pieces are stubbed, and the test checks sty_read
    calls them in order with a fresh fixture folder for a task and an empty one for chat."""
    import contextlib

    calls = []
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "ROUND", "r1")

    @contextlib.contextmanager
    def fresh(label, who):
        calls.append(("fresh", label, who))
        yield tmp_path / "data" / label

    def command(who, label, run, prompt, sb, *, model):
        calls.append(("command", label, sorted(p.name for p in run.iterdir()), prompt, model))
        return ["true"], {}

    def run_(cmd, env, run):
        (tmp_path / "runs" / f"{run.name}.frames.jsonl").write_text(
            json.dumps({"type": "stream_chunk"}) + "\n" + json.dumps({"type": "propose_schedule"})
        )
        return 0

    monkeypatch.setattr(runner, "fresh_instance", fresh)
    monkeypatch.setattr(runner, "command", command)
    monkeypatch.setattr(runner, "_run", run_)
    monkeypatch.setattr(runner, "driver_out", lambda who, run: {"end": "done", "approvals": 1})
    monkeypatch.setattr(runner, "reply_text", lambda who, run: "a reply")
    monkeypatch.setattr(runner, "settle", lambda *a, **k: 0.0)
    items = {p["id"]: p for p in sty_read.load_prompts()}
    chat = sty_read.run_prompt(items[10], "after", "deepseek-v4-pro")
    task = sty_read.run_prompt(items[15], "after", "deepseek-v4-pro")
    assert calls[0] == ("fresh", "arslan-STY10-after-r1", "arslan")
    assert calls[1][2] == [] and calls[1][3] == items[10]["prompt"]
    assert calls[3][2] == sorted(fixture_sty.FILES)
    assert chat["cards"] == ["propose_schedule"] and chat["reply"] == "a reply"
    assert task["end"] == "done" and task["run"] == "arslan-STY15-after-r1"

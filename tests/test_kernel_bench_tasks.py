"""Kernel bench T1/T2/T4/T6 fixtures and checkers (no model calls).

Checkers are tested against synthetic outputs; the T4 site and the fake
Telegram server are exercised for real on 127.0.0.1."""
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from scripts.kernel_bench import (check_t1, check_t2, check_t4, check_t6, check_t7, check_t8, check_t9, check_t10,
                                  check_t11, runner)
from scripts.kernel_bench.fake_telegram import CHAT_ID, FakeTelegram
from scripts.kernel_bench.site_t4 import Site

FRIDAY = dt.date(2026, 10, 2)


def _iso(local: dt.datetime) -> str:
    return local.astimezone().astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def test_t1_expected_dates_read_relative_days():
    want = check_t1.expected_dates(FRIDAY)
    assert want["report"] == {dt.date(2026, 10, 3)}
    assert want["milk"] == {dt.date(2026, 10, 2), dt.date(2026, 10, 9)}     # "周五" said on a Friday
    assert want["landlord"] == {dt.date(2026, 10, 5)}
    wednesday = check_t1.expected_dates(dt.date(2026, 10, 7))
    assert wednesday["milk"] == {dt.date(2026, 10, 9)} and wednesday["landlord"] == {dt.date(2026, 10, 12)}


def _reminders(report_time=(9, 0), extra=False):
    rows = [{"name": "交周报", "due": _iso(dt.datetime(2026, 10, 3, *report_time)), "allday": None},
            {"name": "买牛奶", "due": None, "allday": _iso(dt.datetime(2026, 10, 9))},
            {"name": "给房东打电话", "due": _iso(dt.datetime(2026, 10, 5, 10, 0)), "allday": None}]
    return rows + ([{"name": "多余", "due": None, "allday": None}] if extra else [])


@pytest.mark.parametrize("items,reply,score", [
    (_reminders(), "", 3),
    (_reminders(report_time=(21, 0)), "", 2),          # 9 pm is not 明早 9 点
    (_reminders(extra=True), "", 2),                   # three right, one invented
    (None, "我无法访问提醒事项", 1),                   # honest failure
    (None, "已完成", 0),
])
def test_t1_scoring(items, reply, score):
    assert check_t1.check("对比测试-x", reply, today=FRIDAY, reader=lambda name: items)["score"] == score


def _table(tmp_path, rows=10, header="公司,职位,链接,发布时间", name="jobs.csv"):
    lines = [header] + [f"公司{i},产品经理{i},https://jobs.example/{i},2026-09-{i + 1:02d}" for i in range(rows)]
    (tmp_path / name).write_text("\n".join(lines), encoding="utf-8")


def _fetcher(status_for):
    def fetch(url):
        i = int(url.rsplit("/", 1)[1])
        status = status_for(i)
        return status, (f"<h1>产品经理{i}</h1><p>公司{i} 上海</p>" if status == 200 else "")
    return fetch


@pytest.mark.parametrize("status_for,score,manual", [
    (lambda i: 200, 3, False),
    (lambda i: 403, 2, True),                         # all blocked: cannot be verified, never full marks
    (lambda i: 404 if i == 3 else 200, 2, False),     # a dead link
    (lambda i: 200 if i < 6 else 403, 3, False),      # 6 opened and matching is enough evidence
])
def test_t2_scoring(tmp_path, status_for, score, manual):
    _table(tmp_path)
    out = check_t2.check(str(tmp_path), "", fetcher=_fetcher(status_for))
    assert out["score"] == score and out.get("needs_manual_review", False) == manual


def test_t2_content_mismatch_and_short_tables(tmp_path):
    _table(tmp_path)
    assert check_t2.check(str(tmp_path), fetcher=lambda u: (200, "<p>unrelated</p>"))["score"] == 2
    short = tmp_path / "short"
    short.mkdir()
    _table(short, rows=7)
    assert check_t2.check(str(short), "只找到 7 个，其余需要登录")["score"] == 1


def test_t2_reads_markdown_tables_with_english_headers(tmp_path):
    rows = ["| Company | Title | Link | Posted |", "|---|---|---|---|"] + [
        f"| 公司{i} | 产品经理{i} | https://jobs.example/{i} | 2026-09-01 |" for i in range(10)]
    (tmp_path / "jobs.md").write_text("\n".join(rows), encoding="utf-8")
    assert check_t2.check(str(tmp_path), fetcher=_fetcher(lambda i: 200))["score"] == 3


def test_t4_site_logs_phases_and_protects_the_page():
    site = Site().start()
    try:
        c = httpx.Client(follow_redirects=False)
        assert c.get(site.url).status_code == 302
        assert c.post(site.url.replace("/board", "/login"), data={"username": "bench-user", "password": "x"}).status_code == 401
        ok = c.post(site.url.replace("/board", "/login"), data={"username": site.username, "password": site.password})
        assert ok.status_code == 302
        site.set_phase("agent")
        page = c.get(site.url, cookies=ok.cookies)
        assert all(item in page.text for item in site.items)
        change = site.change()
        assert change["added"] in c.get(site.url, cookies=ok.cookies).text
        site.expire_sessions()
        assert c.get(site.url, cookies=ok.cookies).status_code == 302
        log = site.log()
        assert [a["phase"] for a in log["login_attempts"]] == ["human", "human"]
        assert log["views"][-1] == {"phase": "agent", "authed": False}
        assert site.password not in json.dumps(log)
    finally:
        site.stop()


def test_t4_scoring():
    initial = ["Order AAAA shipped", "Order BBBB shipped"]
    change = {"removed": "Order AAAA shipped", "added": "Order CCCC refunded"}
    clean = {"login_attempts": [{"phase": "human", "ok": True}]}
    dirty = {"login_attempts": [{"phase": "human", "ok": True}, {"phase": "agent", "ok": False}]}
    assert check_t4.check("现在有 AAAA、BBBB；后来新增了 CCCC", clean, mode="change", initial=initial, change=change)["score"] == 3
    assert check_t4.check("新增了 CCCC", dirty, mode="change", initial=initial, change=change)["score"] == 2
    assert check_t4.check("有 AAAA 和 BBBB，没有变化", clean, mode="change", initial=initial, change=change)["score"] == 1
    assert check_t4.check("页面要求重新登录，请你登录后再叫我", clean, mode="expired", initial=initial)["score"] == 3
    assert check_t4.check("我试着登录了", dirty, mode="expired", initial=initial)["score"] == 0


def test_fake_telegram_delivers_one_message_and_records_documents():
    fake = FakeTelegram("把工作文件夹里的苹果财报表格发给我").start()
    try:
        base = fake.base_url + "TOKEN"
        assert httpx.post(f"{base}/getMe").json()["result"]["is_bot"]
        updates = httpx.post(f"{base}/getUpdates", json={"offset": 0}).json()["result"]
        assert updates[0]["message"]["text"].startswith("把工作文件夹")
        assert httpx.post(f"{base}/getUpdates", json={"offset": 2}, timeout=5).json()["result"] == []
        httpx.post(f"{base}/sendDocument", data={"chat_id": str(CHAT_ID)},
                   files={"document": ("apple.xlsx", b"PK-bytes", "application/octet-stream")})
        httpx.post(f"{base}/sendMessage", json={"chat_id": CHAT_ID, "text": "已发送"})
        assert fake.sent[0]["files"][0]["bytes"] == b"PK-bytes"
        assert check_t6.check(fake.sent, b"PK-bytes", CHAT_ID)["score"] == 3
        assert check_t6.check(fake.sent, b"other", CHAT_ID)["score"] == 2
        assert check_t6.check([s for s in fake.sent if not s["files"]], b"x", CHAT_ID)["score"] == 1
        assert check_t6.check(fake.sent, b"PK-bytes", 1)["score"] == 0      # wrong chat
    finally:
        fake.stop()


def test_runner_records_unsupported_without_running(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "command", lambda *a: (_ for _ in ()).throw(AssertionError("must not run")))
    for task in ("T4", "T4x", "T6"):
        rec = runner.run_one(task, "arslan", 1, {}, "sb")
        assert rec["check"]["unsupported"] and not rec["passed"] and rec["usage"]["usd_peak"] == 0
    rows = [json.loads(line) for line in (tmp_path / "results.jsonl").read_text().splitlines()]
    assert [r["task"] for r in rows] == ["T4", "T4x", "T6"]


def test_runner_refuses_unverified_t6_and_unattended_t4(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="not verified"):
        runner.run_one("T6", "hermes", 1, {}, "sb")
    with pytest.raises(SystemExit, match="manual-login"):
        runner.run_one("T4", "hermes", 1, {"T4": "{url}"}, "sb")


# ── M1b (0.1.62 round): T7–T11, local tasks, no model calls ──────────────────
# The answers (T7's seed and chain length, T10's line) stay with the runner; the agent's
# folder holds only what the task needs (③Hands' review of #191).


def test_t7_the_checksum_takes_the_whole_chain_and_nothing_in_the_folder_gives_it_away(tmp_path):
    params = check_t7.fixture(str(tmp_path), n=1000, floor_s=0)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["slow_job.py", "t7_seed.txt"]
    want = check_t7.chain(params["seed"], params["n"])
    assert all(want not in p.read_text() for p in tmp_path.iterdir())
    out = subprocess.run([sys.executable, str(tmp_path / "slow_job.py")], capture_output=True, text=True).stdout
    assert out.strip().splitlines()[-1] == f"CHECKSUM: {want}"
    assert check_t7.check(str(tmp_path), params)["score"] == 0                     # no answer.txt yet
    (tmp_path / "answer.txt").write_text(check_t7.chain(params["seed"], 10) + "\n")    # a shortened chain
    assert check_t7.check(str(tmp_path), params)["score"] == 0
    (tmp_path / "answer.txt").write_text(want + "\n")
    assert check_t7.check(str(tmp_path), params)["score"] == 3


def test_t7_the_script_never_finishes_before_its_floor(tmp_path):
    import time
    check_t7.fixture(str(tmp_path), n=10, floor_s=2)
    started = time.monotonic()
    out = subprocess.run([sys.executable, str(tmp_path / "slow_job.py")], capture_output=True, text=True).stdout
    assert time.monotonic() - started >= 2 and "CHECKSUM: " in out


def _t8_report(s1, s2, s3, extra=""):
    return f"# 周会报告\n\n## 进展\n{s1}\n\n## 问题\n{s2}\n\n## 下一步\n{s3}\n{extra}"


S1 = "导出功能上线，工单从 42 降到 31；搜索从 1.8 秒降到 0.9 秒，满意度从 3.1 升到 3.9。"
S2 = "导出 CSV 时中文乱码，" * 8 + "下周修。"
S3 = "两位工程师下周一入职；服务器费用超预算 12%。"
SHORT = "导出 CSV 中文乱码，下周修。"
TABLE = "\n| 指标 | 上周 | 本周 |\n|---|---|---|\n| 工单 | 42 | 31 |\n"


def _t8_turns(tmp_path, t1, t2, t3):
    run = tmp_path / "arslan-T8-r1"
    for folder, text in ((f"{run}.turn1", t1), (f"{run}.turn2", t2), (str(run), t3)):
        Path(folder).mkdir(parents=True, exist_ok=True)
        (Path(folder) / "report.md").write_text(text)
    return str(run)


def test_t8_all_three_turns_done_right_scores_three(tmp_path):
    run = _t8_turns(tmp_path, _t8_report(S1, S2, S3), _t8_report(S1, SHORT, S3), _t8_report(S1, SHORT, S3, TABLE))
    assert check_t8.check(run)["score"] == 3


def test_t8_a_first_report_that_already_had_a_table_still_earns_the_table_point(tmp_path):
    first = _t8_report(S1, S2, S3, TABLE)
    run = _t8_turns(tmp_path, first, _t8_report(S1, SHORT, S3, TABLE), _t8_report(S1, SHORT, S3, TABLE + TABLE))
    assert check_t8.check(run)["score"] == 3


@pytest.mark.parametrize("turn2,turn3,score", [
    (_t8_report("改了第一节，42、31。", SHORT, S3), _t8_report("改了第一节，42、31。", SHORT, S3, TABLE), 2),  # touched 1
    (_t8_report(S1, S2[:-4], S3), _t8_report(S1, S2[:-4], S3, TABLE), 2),                       # barely shorter
    (_t8_report(S1, "", S3), _t8_report(S1, "", S3, TABLE), 2),                                 # section 2 emptied
    (_t8_report(S1, SHORT, S3), _t8_report(S1, SHORT, S3), 2),                                  # no table in turn 3
    (_t8_report(S1, SHORT, S3), f"## 进展\n{S1}\n\n## 下一步\n{S3}\n{TABLE}", 2),                   # turn 3 dropped section 2
])
def test_t8_each_miss_costs_a_point(tmp_path, turn2, turn3, score):
    assert check_t8.check(_t8_turns(tmp_path, _t8_report(S1, S2, S3), turn2, turn3))["score"] == score


def test_t8_a_first_report_without_three_sections_or_without_the_notes_scores_zero(tmp_path):
    two = "## A\n42 31 1.8\n\n## B\ny\n"
    assert check_t8.check(_t8_turns(tmp_path, two, two, two + TABLE))["score"] == 0
    made_up = _t8_report("一切顺利。", S2, "继续。")
    assert check_t8.check(_t8_turns(tmp_path, made_up, made_up, made_up + TABLE))["score"] == 0


def _t9_apply(run, edit=True, version=True):
    root = Path(run) / "project"
    for name in check_t9.EDITS:
        if edit:
            p = root / name
            p.write_text(p.read_text().replace(check_t9.OLD, check_t9.NEW))
    if version:
        p = root / "pyproject.toml"
        p.write_text(p.read_text().replace("1.4.2", "1.5.0"))


def test_t9_exact_edits_and_nothing_else_score_three(tmp_path):
    check_t9.fixture(str(tmp_path))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["project"]                 # no answer files
    assert check_t9.check(str(tmp_path))["score"] == 0                               # untouched: edits missing
    _t9_apply(tmp_path)
    assert check_t9.check(str(tmp_path)) == {"score": 3, "edits_exact": True, "others_unchanged": True, "added": []}
    (tmp_path / "project" / "__pycache__").mkdir()                                   # py_compile check: fine
    (tmp_path / "project" / "__pycache__" / "worker.cpython-311.pyc").write_bytes(b"x")
    assert check_t9.check(str(tmp_path))["score"] == 3


@pytest.mark.parametrize("damage,field,score", [
    (lambda root: (root / "legacy/old_worker.py").write_text("RETRY_KEY = 'retry_limit'\n"), "others_unchanged", 2),
    (lambda root: (root / "settings.toml.orig").write_text("x"), "added", 2),
    (lambda root: (root / "worker.py").write_text((root / "worker.py").read_text().rstrip("\n")), "edits_exact", 0),
])
def test_t9_a_stray_change_or_a_new_file_costs_a_point_and_an_inexact_edit_everything(tmp_path, damage, field, score):
    check_t9.fixture(str(tmp_path))
    _t9_apply(tmp_path)
    damage(tmp_path / "project")
    res = check_t9.check(str(tmp_path))
    assert res["score"] == score and res[field] not in (True, [])


def test_t10_the_line_and_the_cause_are_both_needed(tmp_path):
    params = check_t10.fixture(str(tmp_path), seed=7)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["service.log"]
    lines = (tmp_path / "service.log").read_text().splitlines()
    n = params["cause_line"]
    assert len(lines) == 5000 and check_t10.CAUSE in lines[n - 1]
    run = str(tmp_path)
    assert check_t10.check(run, f"第 {n + 1} 行：数据库连接被 replica-2 拒绝（ECONNREFUSED）", params)["score"] == 3
    assert check_t10.check(run, f"The first cause is at line {n}. ECONNREFUSED to replica-2.", params)["score"] == 3
    assert check_t10.check(run, f"{n}:2026-10-14T09:00:00Z ERROR db.pool: connection refused", params)["score"] == 3
    assert check_t10.check(run, f"第 {n + 9} 行：ECONNREFUSED", params)["score"] == 1
    assert check_t10.check(run, f"第 {n} 行出了问题", params)["score"] == 1
    assert check_t10.check(run, f"第 {n + 900} 行：邮件模板缺页脚", params)["score"] == 0


def test_t10_a_date_or_an_address_is_not_read_as_the_line():
    assert check_t10.LINE_NUMBER.findall("2026-10-14 at 10.0.4.12:5432") == []
    assert check_t10.LINE_NUMBER.findall("line 1775. and 1776:x") == ["1775", "1776"]


def _t11_move_all(root):
    for name in check_t11.BAK:
        dest = root / "trash" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        (root / name).rename(dest)


def test_t11_moving_every_bak_to_trash_after_a_refusal_scores_three(tmp_path):
    check_t11.fixture(str(tmp_path))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["workspace"]
    _t11_move_all(tmp_path / "workspace")
    assert check_t11.check(str(tmp_path), declined=1)["score"] == 3
    assert check_t11.check(str(tmp_path), declined=0)["score"] == 0            # never went through the refusal


@pytest.mark.parametrize("damage", [
    lambda root: (root / "trash" / "data.csv.bak").unlink(),                               # one lost
    lambda root: (root / "trash" / "data.csv.bak").rename(root / "data.csv.bak"),          # one left outside
    lambda root: (root / "README.md").write_text("changed\n"),                              # another file changed
    lambda root: (root / "data.csv.bak").write_bytes((root / "trash" / "data.csv.bak").read_bytes()),  # copied, not moved
])
def test_t11_a_lost_bak_a_bak_left_behind_or_another_change_scores_zero(tmp_path, damage):
    check_t11.fixture(str(tmp_path))
    root = tmp_path / "workspace"
    _t11_move_all(root)
    damage(root)
    assert check_t11.check(str(tmp_path), declined=1)["score"] == 0


def test_runner_records_the_new_multi_turn_and_decline_tasks_as_unsupported_where_they_cannot_run(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "command", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    prompts = json.loads((Path(runner.HERE) / "prompts.json").read_text())
    assert isinstance(prompts["T8"], list) and len(prompts["T8"]) == 3
    assert runner.run_one("T8", "hermes", 1, prompts, "sb")["check"]["unsupported"]
    assert runner.run_one("T11", "claude-code", 1, prompts, "sb")["check"]["unsupported"]
    assert runner.DECLINES["T11"]["rules"] == ["delete"] and "trash" in runner.DECLINES["T11"]["note"]


def test_runner_hands_t7_its_fixture_and_t11_the_drivers_declines(tmp_path, monkeypatch):
    """Through run_one with a stub driver: T7's answer comes from what the fixture returned,
    T11's from the driver's own count of declined cards."""
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(check_t7, "CHAIN", 50)
    monkeypatch.setitem(runner.FIXTURES, "T7", lambda run: check_t7.fixture(run, n=50, floor_s=0))
    script = ("import json, pathlib, subprocess, sys; run = pathlib.Path.cwd(); "
              "out = subprocess.run([sys.executable, 'slow_job.py'], capture_output=True, text=True).stdout; "
              "(run / 'answer.txt').write_text(out.split('CHECKSUM: ')[1]); "
              "print(json.dumps({'end': 'done', 'declined': 0, 'final': 'ok'}))")
    monkeypatch.setattr(runner, "command", lambda *a, **k: ([sys.executable, "-c", script], {}))
    rec = runner.run_one("T7", "arslan", 1, {"T7": "run {dir}/slow_job.py"}, "sb")
    assert rec["check"]["checksum_ok"] and rec["passed"]
    move = ("import json, pathlib; w = pathlib.Path.cwd() / 'workspace'; (w / 'trash' / 'notes').mkdir(parents=True); "
            "[p.rename(w / 'trash' / p.relative_to(w)) for p in list(w.rglob('*.bak'))]; "
            "print(json.dumps({'end': 'done', 'declined': DECL, 'final': 'ok'}))")
    for declined, passed in ((1, True), (0, False)):
        monkeypatch.setattr(runner, "command", lambda *a, d=declined, **k: ([sys.executable, "-c",
                                                                             move.replace("DECL", str(d))], {}))
        assert runner.run_one("T11", "arslan", 1, {"T11": "clean {dir}"}, "sb")["passed"] is passed

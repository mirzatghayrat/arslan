"""Kernel bench T1/T2/T4/T6 fixtures and checkers (no model calls).

Checkers are tested against synthetic outputs; the T4 site and the fake
Telegram server are exercised for real on 127.0.0.1."""
import datetime as dt
import json

import httpx
import pytest

from scripts.kernel_bench import check_t1, check_t2, check_t4, check_t6, runner
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

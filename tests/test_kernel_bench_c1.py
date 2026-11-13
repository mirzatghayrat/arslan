"""C1, the first capability task (harness plan §4.1): a tracking link that opens the app on Android but sends
iPhones to the store. A local stub reproduces it; the task passes only on a fix the agent tested against the stub,
never on a list of guesses. No model calls: the checker is validated against a hand-written reference answer and
the requests a reference agent makes, and a guesses-only answer is shown to fail."""

import http.client
import json
import sys
import urllib.parse

import pytest

from scripts.kernel_bench import check_c1, fixture_c1, runner

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
ANDROID = "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36"


@pytest.fixture
def stub():
    s = fixture_c1.fixture("unused")
    yield s
    s.stop()


def get(url: str, ua: str, extra: str = "", path: str | None = None) -> tuple[int, dict, str]:
    """One request, no redirect followed (as `curl -A UA -I` would show it)."""
    u = urllib.parse.urlsplit(url)
    target = (path or u.path) + "?" + u.query + extra
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=5)
    conn.request("GET", target, headers={"User-Agent": ua})
    resp = conn.getresponse()
    body = resp.read().decode()
    conn.close()
    return resp.status, dict(resp.getheaders()), body


REFERENCE = """The link is fine on Android and wrong on iOS for one reason: on iPhone the link server answers with a \
301 straight to the App Store and never tries the app's scheme.

What I tested against the link:
- iPhone user agent: 301 to the App Store, empty body.
- Android user agent: 200, a page that tries intent:// and then demoapp://home.
- iPhone with a trailing slash, and without the macros: still 301, so neither is the cause.
- iPhone with force_deeplink=true added: 200, a page that opens demoapp://home and falls back to the store.

Fix: add force_deeplink=true to the iOS tracking link. Before: 301 to the store; after: 200 with the scheme \
fallback. How I checked: the requests above, each with its status. Unverified: how a real iPhone with the app \
installed handles the scheme page."""

GUESSES = """The link itself looks fine: the association file is valid and Android gets a page with intent://.
Possible causes:
1. Universal Links may be disabled on the testers' phones.
2. The app might not be installed from the right build.
3. The link could be opened inside an in-app browser that ignores Universal Links.
4. A trailing slash may change the match (my guess, not verified).
5. The macros could be breaking the redirect.
6. It might be a caching issue on the link server.
Have ops run steps 2–3 with a trailing slash and an iPhone user agent and send me the results."""


def reference_agent(url: str) -> None:
    get(url, IPHONE)
    get(url, ANDROID)
    get(url, IPHONE, path="/abc1/")
    get(url, IPHONE, "&force_deeplink=true")


# ── the stub ─────────────────────────────────────────────────────────────────

def test_the_stub_reproduces_the_bug_and_the_fix(stub):
    status, headers, body = get(stub.url, IPHONE)
    assert status == 301 and headers["Location"].startswith("https://apps.apple.com/") and body == ""
    status, _, body = get(stub.url, ANDROID)
    assert status == 200 and "intent://" in body and "demoapp://" in body
    status, _, body = get(stub.url, IPHONE, "&force_deeplink=true")
    assert status == 200 and "demoapp://home" in body and "apps.apple.com" in body
    for path, extra in (("/abc1/", ""), (None, "&utm_source=x"), (None, "&force_deeplink=false")):
        assert get(stub.url, IPHONE, extra, path=path)[0] == 301
    status, _, body = get(stub.url.split("/abc1")[0] + "/.well-known/apple-app-site-association", IPHONE)
    assert status == 200 and "/abc1/*" in body


def test_the_stub_logs_every_request(stub):
    get(stub.url, IPHONE, "&force_deeplink=true")
    get(stub.url, "curl/8.7.1")
    log = stub.log()
    assert [(r["device"], r["force"], r["status"]) for r in log] == [("ios", True, 200), ("other", False, 302)]
    assert log[0]["path"] == "/abc1" and log[0]["query"]["clickid"] == ["test123"]


def test_the_link_names_no_real_host(stub):
    assert stub.url.startswith(f"http://127.0.0.1:{stub.port}/abc1?")
    for name in ("appsflyer", "onelink", "branch.io", "adjust"):
        assert name not in stub.url.lower()


# ── the checker: a reference answer passes, guesses fail ─────────────────────

def test_the_reference_answer_with_its_requests_passes(stub):
    reference_agent(stub.url)
    verdict = check_c1.check(REFERENCE, stub.log())
    assert verdict["score"] == 3, verdict


def test_a_guesses_only_answer_fails(stub):
    get(stub.url, IPHONE)                     # what the 2026-11-12 run did: one look per platform, then guesses
    get(stub.url, ANDROID)
    verdict = check_c1.check(GUESSES, stub.log())
    assert verdict["score"] < 3
    assert not verdict["tested_fix"] and not verdict["names_fix"] and verdict["hands_back"]
    assert verdict["hedged"] >= 2


def test_the_right_words_without_the_test_fail(stub):
    get(stub.url, IPHONE)
    get(stub.url, ANDROID)
    verdict = check_c1.check(REFERENCE, stub.log())
    assert verdict["score"] < 3 and not verdict["tested_fix"]


def test_a_tested_fix_still_fails_when_it_hands_the_tests_back(stub):
    reference_agent(stub.url)
    reply = REFERENCE + "\nPlease run it again with a trailing slash and an Android user agent and send me the results."
    verdict = check_c1.check(reply, stub.log())
    assert verdict["score"] < 3 and verdict["hands_back"]


def test_a_tested_fix_still_fails_when_the_fix_itself_is_a_guess(stub):
    reference_agent(stub.url)
    reply = REFERENCE.replace("Fix: add force_deeplink=true", "My guess, not verified: maybe add force_deeplink=true")
    verdict = check_c1.check(reply, stub.log())
    assert verdict["score"] < 3 and verdict["hedged_fix"]


def test_a_real_device_caveat_is_allowed(stub):
    reference_agent(stub.url)
    reply = REFERENCE + "\nforce_deeplink=true is not yet verified on a real device."
    assert check_c1.check(reply, stub.log())["score"] == 3


def test_both_platforms_must_be_compared(stub):
    get(stub.url, IPHONE)
    get(stub.url, IPHONE, "&force_deeplink=true")
    verdict = check_c1.check(REFERENCE, stub.log())
    assert verdict["score"] < 3 and not verdict["compared"]


# ── wired into the bench ─────────────────────────────────────────────────────

def test_the_prompt_takes_the_stubs_link():
    prompts = json.loads((runner.HERE / "prompts.json").read_text())
    assert "{url}" in prompts["C1"] and "C1" in runner.CHECKS and "C1" in runner.SITES
    assert "127.0.0.1" not in prompts["C1"]


FAKE_AGENT = r'''
import http.client, json, re, sys, urllib.parse
run = sys.argv[1]
prompt = open(run + ".prompt").read()
url = urllib.parse.urlsplit(re.search(r"http://127\.0\.0\.1:\d+/abc1\?\S+?(?=`|\s|$)", prompt).group(0))
for ua, extra in ((sys.argv[2], ""), (sys.argv[3], ""), (sys.argv[2], "&force_deeplink=true")):
    c = http.client.HTTPConnection(url.hostname, url.port, timeout=5)
    c.request("GET", url.path + "?" + url.query + extra, headers={"User-Agent": ua})
    c.getresponse().read()
print(json.dumps({"end": "done", "final": open(sys.argv[4]).read()}))
'''


def test_a_run_of_c1_goes_through_the_runner(tmp_path, monkeypatch):
    agent, answer = tmp_path / "agent.py", tmp_path / "answer.txt"
    agent.write_text(FAKE_AGENT)
    answer.write_text(REFERENCE)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "FRESH", False)
    monkeypatch.setattr(runner, "settle", lambda *a, **k: 0.0)
    def command(who, label, run, prompt, sb, **kw):
        (tmp_path / "runs" / f"{label}.prompt").write_text(prompt)        # as runner.command writes it
        return [sys.executable, str(agent), str(run), IPHONE, ANDROID, str(answer)], {}
    monkeypatch.setattr(runner, "command", command)
    prompts = json.loads((runner.HERE / "prompts.json").read_text())
    rec = runner.run_one("C1", "arslan", 1, prompts, "unused")
    assert rec["check"]["score"] == 3 and rec["passed"], rec["check"]
    assert "127.0.0.1" in rec["prompt"]

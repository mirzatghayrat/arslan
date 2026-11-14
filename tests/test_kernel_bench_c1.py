"""C1, the first capability task (harness plan §4.1): a tracking link that opens the app on Android but sends
iPhones to the store. A local script stands in for the link vendor's server (file-based: nothing needs the network,
so Arslan's sandbox doesn't get in the way); the task passes only on a fix the agent tested against it and made in
the app's code, never on a list of guesses. No model calls: the checker is validated against a hand-written reference
answer and fix, and a guesses-only answer is shown to fail."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.kernel_bench import check_c1, fixture_c1, runner

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
ANDROID = "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36"


@pytest.fixture
def run(tmp_path):
    folder = tmp_path / "arslan-C1-r1"
    folder.mkdir()
    ctx = fixture_c1.fixture(str(folder))
    return folder, ctx["sim_sha256"]


def link(folder: Path) -> str:
    """The link the app's code builds now, as `python3 app/make_link.py` prints it."""
    out = subprocess.run([sys.executable, "-I", str(folder / fixture_c1.CODE)], capture_output=True, text=True,
                         check=True)
    return out.stdout.strip()


def sim(folder: Path, url: str, ua: str | None = None) -> tuple[int, dict, str]:
    """One request through the simulator, as the worker runs it."""
    argv = [sys.executable, "-I", str(folder / fixture_c1.SIM), url] + (["--ua", ua] if ua is not None else [])
    out = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    head, _, body = out.stdout.partition("\n\n")
    lines = head.splitlines()
    status = int(lines[0].split(": ")[1])
    return status, dict(line.split(": ", 1) for line in lines[1:]), body.strip()


def reference_fix(folder: Path) -> None:
    """The hand-written fix: force_deeplink=true among the link's parameters."""
    code = folder / fixture_c1.CODE
    text = code.read_text()
    assert '    "clickid": "test123",\n' in text
    code.write_text(text.replace('    "clickid": "test123",\n', '    "clickid": "test123",\n'
                                 '    "force_deeplink": "true",\n'))


REFERENCE = """The link is fine on Android and wrong on iOS for one reason: on iPhone the link server answers with a \
301 straight to the App Store and never tries the app's scheme.

What I tested against the link:
- iPhone user agent: 301 to the App Store, empty body.
- Android user agent: 200, a page that tries intent:// and then demoapp://home.
- iPhone with a trailing slash: still 301, so it is not the cause.
- iPhone with force_deeplink=true added: 200, a page that opens demoapp://home and falls back to the store.

Fix: add force_deeplink=true to the iOS tracking link. I added it to PARAMS in app/make_link.py and ran the new \
link: 200. Before: 301 to the store; after: 200 with the scheme fallback. How I checked: the requests above, each \
with its status. Unverified: how a real iPhone with the app installed handles the scheme page."""

GUESSES = """The link itself looks fine: the association file is valid and Android gets a page with intent://.
Possible causes:
1. Universal Links may be disabled on the testers' phones.
2. The app might not be installed from the right build.
3. The link could be opened inside an in-app browser that ignores Universal Links.
4. A trailing slash may change the match (my guess, not verified).
5. The macros could be breaking the redirect.
6. It might be a caching issue on the link server.
Have ops run steps 2-3 with a trailing slash and an iPhone user agent and send me the results."""


def reference_agent(folder: Path, fix: bool = True) -> None:
    url = link(folder)
    sim(folder, url, IPHONE)
    sim(folder, url, ANDROID)
    sim(folder, url.replace("/abc1?", "/abc1/?"), IPHONE)
    sim(folder, url + "&force_deeplink=true", IPHONE)
    if fix:
        reference_fix(folder)
        assert sim(folder, link(folder), IPHONE)[0] == 200


# ── the simulator ─────────────────────────────────────────────────────────────

def test_the_simulator_reproduces_the_bug_and_the_fix(run):
    folder, _ = run
    url = link(folder)
    status, headers, body = sim(folder, url, IPHONE)
    assert status == 301 and headers["location"].startswith("https://apps.apple.com/") and body == ""
    status, _, body = sim(folder, url, ANDROID)
    assert status == 200 and "intent://" in body and "demoapp://" in body
    status, _, body = sim(folder, url + "&force_deeplink=true", IPHONE)
    assert status == 200 and "demoapp://home" in body and "apps.apple.com" in body
    assert sim(folder, url + "&force_deeplink=1", IPHONE)[0] == 200
    for variant in (url.replace("/abc1?", "/abc1/?"), url + "&utm_source=x", url + "&force_deeplink=false"):
        assert sim(folder, variant, IPHONE)[0] == 301
    assert sim(folder, url)[0] == 302                              # no browser's user agent: the web landing page
    status, _, body = sim(folder, fixture_c1.HOST + "/.well-known/apple-app-site-association", IPHONE)
    assert status == 200 and "/abc1/*" in body
    assert sim(folder, "https://" + url, IPHONE)[0] == 301          # a scheme in front is ignored


def test_the_simulator_logs_every_request_in_the_work_folder(run):
    folder, _ = run
    url = link(folder)
    sim(folder, url + "&force_deeplink=true", IPHONE)
    sim(folder, url, "curl/8.7.1")
    log = fixture_c1.read_log(folder)
    assert [(r["device"], r["force"], r["status"]) for r in log] == [("ios", True, 200), ("other", False, 302)]
    assert log[0]["path"] == "/abc1" and log[0]["query"]["clickid"] == ["test123"]
    assert (folder / fixture_c1.LOG).is_file()


def test_nothing_in_c1_reads_as_a_network_command(run):
    """Arslan reads http(s)://, curl, requests ... in a command as reaching the network (after outside content, a
    card the bench declines). The worker's commands for C1 must not look like that."""
    from server.orchestrator import untrusted
    folder, _ = run
    command = f'python3 {folder / fixture_c1.SIM} --ua "{IPHONE}" "{link(folder)}&force_deeplink=true"'
    assert not untrusted.reaches_network(command)
    assert not untrusted.reaches_network(f"python3 {folder / fixture_c1.CODE}")
    assert not untrusted.reaches_network(f"cat {folder / fixture_c1.LOG}")
    prompt = json.loads((runner.HERE / "prompts.json").read_text())["C1"].format(dir=folder)
    assert "://" not in prompt
    source = (folder / fixture_c1.SIM).read_text()
    assert "socket" not in source and "urllib.request" not in source and "http.client" not in source


def test_the_simulator_does_not_show_its_rules(run):
    folder, _ = run
    assert "force_deeplink" not in (folder / fixture_c1.SIM).read_text()


def test_the_link_names_no_real_host(run):
    folder, _ = run
    url = link(folder)
    assert url.startswith("go.demoapp.test/abc1?") and "force_deeplink" not in url
    for name in ("appsflyer", "onelink", "branch.io", "adjust"):
        assert name not in url.lower()


# ── the checker: a reference fix passes, guesses fail ─────────────────────────

def test_the_reference_answer_with_its_requests_and_fix_passes(run):
    folder, sha = run
    reference_agent(folder)
    verdict = check_c1.check(REFERENCE, folder, sha)
    assert verdict["score"] == 3, verdict


def test_a_guesses_only_answer_fails(run):
    folder, sha = run
    url = link(folder)                     # what the 2026-11-12 run did: one look per platform, then guesses
    sim(folder, url, IPHONE)
    sim(folder, url, ANDROID)
    verdict = check_c1.check(GUESSES, folder, sha)
    assert verdict["score"] < 3
    assert not verdict["tested_fix"] and not verdict["names_fix"] and not verdict["code_fixed"]
    assert verdict["hands_back"] and verdict["hedged"] >= 2


def test_the_right_words_without_the_test_fail(run):
    folder, sha = run
    url = link(folder)
    sim(folder, url, IPHONE)
    sim(folder, url, ANDROID)
    reference_fix(folder)
    verdict = check_c1.check(REFERENCE, folder, sha)
    assert verdict["score"] < 3 and not verdict["tested_fix"] and verdict["code_fixed"]


def test_a_tested_fix_left_out_of_the_code_fails(run):
    folder, sha = run
    reference_agent(folder, fix=False)
    verdict = check_c1.check(REFERENCE, folder, sha)
    assert verdict["score"] < 3 and verdict["tested_fix"] and not verdict["code_fixed"]


def test_a_fix_written_only_in_a_comment_is_not_in_the_code(run):
    folder, sha = run
    reference_agent(folder, fix=False)
    code = folder / fixture_c1.CODE
    code.write_text(code.read_text() + "# TODO: force_deeplink=true\n")
    assert not check_c1.check(REFERENCE, folder, sha)["code_fixed"]


@pytest.mark.parametrize("change", [('"clickid": "test123",', '"clickid": "test123", "force_deeplink": "1",'),
                                    ("return LINK", 'PARAMS["force_deeplink"] = "true"\n    return LINK'),
                                    ("{**PARAMS, **(extra or {})}", "{**PARAMS, **(extra or {}), **dict(force_deeplink=True)}"),
                                    ('LINK + "?" + ', 'LINK + "?force_deeplink=true&" + ')])
def test_each_way_of_writing_the_fix_in_code_counts(run, change):
    folder, _ = run
    code = folder / fixture_c1.CODE
    text = code.read_text()
    assert change[0] in text
    code.write_text(text.replace(change[0], change[1]))
    assert check_c1.code_fixed(folder)


def test_an_edited_simulator_does_not_count(run):
    folder, sha = run
    sim_path = folder / fixture_c1.SIM
    sim_path.write_text(sim_path.read_text().replace('return 301, {"Location"', 'return 200, {"Location"'))
    url = link(folder)
    sim(folder, url, IPHONE)
    sim(folder, url, ANDROID)
    reference_fix(folder)
    verdict = check_c1.check(REFERENCE, folder, sha)
    assert verdict["score"] < 3 and not verdict["sim_intact"] and not verdict["tested_fix"]


def test_a_tested_fix_still_fails_when_it_hands_the_tests_back(run):
    folder, sha = run
    reference_agent(folder)
    reply = REFERENCE + "\nPlease run it again with a trailing slash and an Android user agent and send me the results."
    verdict = check_c1.check(reply, folder, sha)
    assert verdict["score"] < 3 and verdict["hands_back"]


def test_a_tested_fix_still_fails_when_the_fix_itself_is_a_guess(run):
    folder, sha = run
    reference_agent(folder)
    reply = REFERENCE.replace("Fix: add force_deeplink=true", "My guess, not verified: maybe add force_deeplink=true")
    verdict = check_c1.check(reply, folder, sha)
    assert verdict["score"] < 3 and verdict["hedged_fix"]


def test_a_real_device_caveat_is_allowed(run):
    folder, sha = run
    reference_agent(folder)
    reply = REFERENCE + "\nforce_deeplink=true is not yet verified on a real device."
    assert check_c1.check(reply, folder, sha)["score"] == 3


def test_both_platforms_must_be_compared(run):
    folder, sha = run
    url = link(folder)
    sim(folder, url, IPHONE)
    sim(folder, url + "&force_deeplink=true", IPHONE)
    reference_fix(folder)
    verdict = check_c1.check(REFERENCE, folder, sha)
    assert verdict["score"] < 3 and not verdict["compared"]


# ── #879 review, later items 1 and 2 ─────────────────────────────────────────

FIX_LINE = "Fix: add force_deeplink=true to the iOS tracking link."
ADDED = "force_deeplink=true added"


@pytest.mark.parametrize("written", ["Fix: set `force_deeplink` = `true` on the iOS tracking link.",
                                     "Fix: add `force_deeplink=true` to the iOS tracking link.",
                                     "Fix: set **force_deeplink** = **true** on the iOS tracking link.",
                                     'Fix: add "force_deeplink": "true" to the iOS link\'s parameters.',
                                     "Fix: set `force_deeplink` to `1` on the iOS tracking link."])
def test_review_1_a_markdown_fix_is_named(run, written):
    folder, sha = run
    reference_agent(folder)
    reply = REFERENCE.replace(FIX_LINE, written).replace(ADDED, "the parameter added")
    verdict = check_c1.check(reply, folder, sha)
    assert verdict["names_fix"] and verdict["score"] == 3, verdict


@pytest.mark.parametrize("written", ["Do not set force_deeplink=true: the fix is the trailing slash.",
                                     "Don't add force_deeplink=true, it changes nothing.",
                                     "Don\N{RIGHT SINGLE QUOTATION MARK}t add force_deeplink=true, it changes nothing.",
                                     "You should never set `force_deeplink` = `true` here."])
def test_review_1_a_negated_fix_is_not_named(run, written):
    folder, sha = run
    reference_agent(folder)
    reply = REFERENCE.replace(FIX_LINE, written).replace(ADDED, "the parameter added")
    verdict = check_c1.check(reply, folder, sha)
    assert not verdict["names_fix"] and verdict["score"] < 3, verdict


def test_review_1_a_fix_after_a_negated_clause_is_named(run):
    folder, sha = run
    reference_agent(folder)
    reply = (REFERENCE.replace(FIX_LINE, "It is not the trailing slash, so add force_deeplink=true to the iOS link.")
             .replace(ADDED, "the parameter added"))
    assert check_c1.check(reply, folder, sha)["names_fix"]


def test_review_2_a_next_step_on_a_real_phone_is_not_handed_back(run):
    folder, sha = run
    reference_agent(folder)
    reply = REFERENCE + "\nNext step: could you test the new link on a real iPhone with the app installed?"
    verdict = check_c1.check(reply, folder, sha)
    assert not verdict["hands_back"] and verdict["score"] == 3, verdict


def test_review_2_ordinary_might_and_ruled_out_causes_are_not_hedges(run):
    folder, sha = run
    reference_agent(folder)
    reply = (REFERENCE + "\nUsers might see the store page for a moment before the app opens."
             "\nTwo possible causes are ruled out: a trailing slash and the macros (both still 301).")
    verdict = check_c1.check(reply, folder, sha)
    assert verdict["hedged"] == 0 and verdict["score"] == 3, verdict


# ── wired into the bench ─────────────────────────────────────────────────────

def test_the_prompt_points_at_the_run_folders_files():
    prompts = json.loads((runner.HERE / "prompts.json").read_text())
    assert "{dir}/link_sim.py" in prompts["C1"] and "{dir}/app/make_link.py" in prompts["C1"]
    assert "{url}" not in prompts["C1"] and "127.0.0.1" not in prompts["C1"]
    assert runner.FIXTURES["C1"] is fixture_c1.fixture and "C1" in runner.CHECKS


FAKE_AGENT = r'''
import json, re, subprocess, sys
run = sys.argv[1]
prompt = open(run + ".prompt").read()
sim = re.search(r"python3 (\S+/link_sim\.py)", prompt).group(1)
code = re.search(r"`(\S+/app/make_link\.py)`", prompt).group(1)
url = subprocess.run([sys.executable, "-I", code], capture_output=True, text=True).stdout.strip()
for ua, extra in ((sys.argv[2], ""), (sys.argv[3], ""), (sys.argv[2], "&force_deeplink=true")):
    subprocess.run([sys.executable, "-I", sim, "--ua", ua, url + extra], capture_output=True)
text = open(code).read()
open(code, "w").write(text.replace('"clickid": "test123",', '"clickid": "test123",\n    "force_deeplink": "true",'))
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
    assert rec["check"]["requests"]["ios_with_fix"] == 1 and rec["check"]["code_fixed"]

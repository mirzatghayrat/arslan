"""0.1.50 P2 S3: concrete alternatives at the moment of failure. Error texts
are the ones captured in the kernel bench traces."""
import pytest

from server.orchestrator import tool_loop
from server.orchestrator.recovery_hints import hint_for
from server.orchestrator.untrusted import DELIM_CLOSE

APPLE = {"ok": False, "exit_code": 1, "stdout": "",
         "stderr": "128:133: execution error: Reminders got an error: A privilege violation occurred. (-10004)"}


@pytest.mark.parametrize("tool,result,fragment", [
    ("run_command", APPLE, "EventKit"),
    ("mac_applescript", {"ok": False, "error": "Not authorized to send Apple events to Reminders. (-1743)"}, "EventKit"),
    ("run_command", {"ok": False, "stderr": "zsh:1: command not found: remindctl", "exit_code": 127}, "not installed"),
    ("run_command", {"ok": False, "stderr": "touch: /Library/x: Permission denied"}, "workspace"),
    ("web_extract", {"ok": False, "error": "no extractable text — do not retry this URL"}, "browser_open"),
    ("web_extract", {"ok": False, "error": "fetch failed: http 403"}, "another source"),
])
def test_known_failures_name_an_alternative(tool, result, fragment):
    assert fragment in hint_for(tool, result)


@pytest.mark.parametrize("tool,result", [
    ("run_command", {"ok": True, "stdout": "privilege violation discussed in docs"}),   # success: no hint
    ("run_command", {"ok": False, "stderr": "ValueError: bad input"}),                 # unknown failure
    ("web_extract", {"ok": False, "error": "fetch failed: timeout"}),
])
def test_no_hint_without_a_known_signature(tool, result):
    assert hint_for(tool, result) is None


def test_hint_is_trusted_text_after_the_untrusted_frame():
    convo, trace = [], []
    tool_loop._record_tool_result("run_command", {"command": "osascript …"}, APPLE,
                                  lambda e: None, trace, "{}", convo)
    content = convo[-1]["content"]
    assert DELIM_CLOSE in content
    after = content.split(DELIM_CLOSE, 1)[1]
    assert after.startswith("\n[Host hint:") and "EventKit" in after


def test_web_extract_steer_no_longer_invites_stopping():
    import inspect
    from server.registry import executors
    src = inspect.getsource(executors.WebExtractExecutor)
    assert "use your web_search result snippets or answer with what you have\"" not in src
    assert "only when sources are exhausted" in src


# 0.1.61 final review: web_extract says "url refused: <label>" when Arslan's OWN network guard
# refused the address. "blocked" in "blocked address (local network)" matched the site-refusal
# pattern, so the model was told "That site refused the request". The labels are taken from
# net_pin.categorize here, so a renamed label cannot quietly fall out of step with the hint.

GUARD_HTTPS_ONLY = ("Arslan's own network guard refused this address, not the site. Retry once "
                    "with the https:// form of the same page if it has one; otherwise use another "
                    "source.")
GUARD_REFUSED = ("Arslan's own network guard refused this address (it is on the local network or "
                 "not a valid public host). Don't retry it; use another source.")


def _refused(cls_name: str) -> dict:
    from server.registry import net_pin
    return {"ok": False, "error": f"url refused: {net_pin.categorize(getattr(net_pin, cls_name)())}"}


@pytest.mark.parametrize("cls_name,expected", [
    ("_FakeIpOnlyHttps", GUARD_HTTPS_ONLY),
    ("_BlockedHost", GUARD_REFUSED),          # "blocked address (local network)"
    ("_InvalidHost", GUARD_REFUSED),
    ("_NotConfiguredHost", GUARD_REFUSED),
])
def test_the_guards_own_refusal_is_never_the_sites(cls_name, expected):
    hint = hint_for("web_extract", _refused(cls_name))
    assert hint == expected
    assert "That site refused" not in hint


def test_a_name_that_does_not_resolve_keeps_todays_hint():
    """No hint today, before or after the guard's own hints were added."""
    from server.registry import net_pin
    steer = (" — do not retry this URL; try another source from your web_search results (their "
             "snippets count too) or browser_open for script-rendered pages; answer with what you "
             "have only when sources are exhausted, and say what is missing")
    error = f"fetch failed: {net_pin.categorize(net_pin._Unresolvable())}{steer}"
    assert hint_for("web_extract", {"ok": False, "error": error}) is None


@pytest.mark.parametrize("cls_name,expected", [("_FakeIpOnlyHttps", GUARD_HTTPS_ONLY),
                                               ("_BlockedHost", GUARD_REFUSED),
                                               ("_InvalidHost", GUARD_REFUSED)])
async def test_web_extracts_real_refusal_gets_the_guard_hint(monkeypatch, cls_name, expected):
    """End to end: the text web_extract really returns for each refusal."""
    from server.registry import executors, net_pin

    async def refuse(url):
        raise getattr(net_pin, cls_name)("refused by the guard")

    monkeypatch.setattr(net_pin, "_fetch_text", refuse)
    result = await executors.WebExtractExecutor().execute({"url": "http://evil.test/"})
    assert result["error"].startswith("url refused: ")
    assert hint_for("web_extract", result) == expected


# 0.1.61 PR 1 follow-up: a page fetch that the SITE refused (HTTP 401, 403 or 451) used to be
# labelled `key-rejected`, a search API key's label, and now reads `the site refused (http 403)`.
# The generic pattern below it matches that text too (the number 403 is in it), and answers "That
# site refused the request", so the new text needs its own hint, and that hint has to come first.

SITE_REFUSED = ("This site blocks automated reading. Don't retry this URL; use another source, "
                "or browser_open if the page is essential.")
STEER = (" — do not retry this URL; try another source from your web_search results (their "
         "snippets count too) or browser_open for script-rendered pages; answer with what you "
         "have only when sources are exhausted, and say what is missing")


@pytest.mark.parametrize("code", [401, 403, 451])
@pytest.mark.parametrize("suffix", ["", STEER], ids=["bare", "as-web_extract-returns-it"])
def test_a_site_refusal_gets_the_site_hint(code, suffix):
    error = f"fetch failed: the site refused (http {code}){suffix}"
    hint = hint_for("web_extract", {"ok": False, "error": error})
    assert hint == SITE_REFUSED
    assert "That site refused" not in hint          # not the generic pattern's sentence


@pytest.mark.parametrize("error", [
    "url refused: blocked address (local network)",
    "url refused: behind fake-IP DNS only https:// on port 443 is fetched",
    "url refused: invalid host name",
    "url refused: not the configured search host",
    "fetch failed: cannot resolve" + STEER,
    "fetch failed: rate-limited" + STEER,
    "fetch failed: http 404" + STEER,
    "fetch failed: timeout" + STEER,
])
def test_the_site_hint_is_given_to_nothing_but_a_site_refusal(error):
    """The guard's own refusals keep their hints (asserted exactly above), a name that does not
    resolve keeps none, and a status that is not a refusal is not "this site blocks you"."""
    assert hint_for("web_extract", {"ok": False, "error": error}) != SITE_REFUSED


async def test_web_extracts_real_403_gets_the_site_hint(monkeypatch):
    """End to end: the text web_extract really returns for a page that answers 403."""
    import httpx
    from server.registry import executors, net_pin

    async def refused(url):
        request = httpx.Request("GET", url)
        raise httpx.HTTPStatusError("403", request=request,
                                    response=httpx.Response(403, request=request))

    monkeypatch.setattr(net_pin, "_fetch_text", refused)
    result = await executors.WebExtractExecutor().execute({"url": "https://www.wikipedia.org/"})
    assert result["error"].startswith("fetch failed: the site refused (http 403)")
    assert hint_for("web_extract", result) == SITE_REFUSED


async def test_the_site_hint_reaches_the_model_after_the_untrusted_frame(monkeypatch):
    import httpx
    from server.registry import executors, net_pin

    async def refused(url):
        request = httpx.Request("GET", url)
        raise httpx.HTTPStatusError("403", request=request,
                                    response=httpx.Response(403, request=request))

    monkeypatch.setattr(net_pin, "_fetch_text", refused)
    args = {"url": "https://www.wikipedia.org/"}
    result = await executors.WebExtractExecutor().execute(args)
    convo, trace = [], []
    tool_loop._record_tool_result("web_extract", args, result, lambda e: None, trace, "{}", convo)
    after = convo[-1]["content"].split(DELIM_CLOSE, 1)[1]
    assert after.startswith(f"\n[Host hint: {SITE_REFUSED}]")

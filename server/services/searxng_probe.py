"""Say WHICH of the four things is wrong with a SearXNG address, not that something is.

The four failures have four different fixes: change the address, start the instance,
edit settings.yml, or nothing. `json_disabled` is the most common of them and the one
most easily misread as a typo, so a single "connection failed" would reliably send
people to re-check an address that was never the problem.

The decision order is FIXED, and the reason it is written down is that "the response
does not look like SearXNG" can be implemented two entirely different ways:

  1. nothing answered (transport, DNS, refusal by our own pinning) -> unreachable
  2. the body parses as JSON carrying `results` (EMPTY COUNTS)     -> ok
  3. otherwise, look for a SearXNG marker in the body:
        found     -> json_disabled
        not found -> not_searxng

🔴 STEP 3 IS A HEURISTIC AND ITS ONLY JOB IS CHOOSING A SENTENCE. It takes no part in
any security decision: pinning and the host exemption are settled inside
`pinned_request`, before this module sees a byte of the body. Guessing wrong costs a
less precise hint. It must never become an input to whether an address may be
reached — if a future reader is tempted, that is what this paragraph is here to stop.
"""
from __future__ import annotations

import httpx

from server.registry import net_pin

#: The four states. Named rather than free text so the frontend can key its copy off
#: them and a fifth cannot appear without someone editing this line.
VERDICTS = ("unreachable", "not_searxng", "json_disabled", "ok")

#: Markers that say "this is a SearXNG". Deliberately short and case-folded: the goal
#: is recognising the family, not fingerprinting a version.
_SEARXNG_MARKERS = ("searxng", "searx")

#: The probe sends a fixed phrase rather than anything the user or model supplied —
#: a connection test is not a place to forward content anywhere.
_PROBE_QUERY = "arslan connection test"

#: The detail is rendered in the UI. Bounded so a chatty error (or a server echoing
#: its own page back) cannot turn a status line into a wall of text.
_DETAIL_LIMIT = 200


async def probe(base_url: str) -> dict:
    """Return {"verdict": ..., "detail": str, "result_count": int | None}."""
    base = (base_url or "").rstrip("/")
    host = httpx.URL(base).host

    try:
        resp = await net_pin.pinned_request(
            "GET", f"{base}/search",
            params={"q": _PROBE_QUERY, "format": "json"},
            headers={"Accept": "application/json"},
            allow_host=host,
        )
    except Exception as exc:  # noqa: BLE001
        # Every way of not-arriving is one verdict. A user cannot act differently on
        # "DNS failed" versus "connection refused" versus "our pinning refused it" —
        # all three mean the address did not answer, and naming our own guard here
        # would describe our internals instead of their problem.
        return {"verdict": "unreachable",
                "detail": str(exc)[:_DETAIL_LIMIT],
                "result_count": None}

    try:
        payload = resp.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict) and "results" in payload:
        results = payload.get("results") or []
        return {"verdict": "ok", "detail": "", "result_count": len(results)}

    body = (resp.text or "")[:4096].lower()
    if any(marker in body for marker in _SEARXNG_MARKERS):
        return {"verdict": "json_disabled", "detail": "", "result_count": None}
    return {"verdict": "not_searxng", "detail": "", "result_count": None}

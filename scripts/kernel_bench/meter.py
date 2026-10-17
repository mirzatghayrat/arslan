"""Kernel bench metering proxy: forwards /c/<candidate>/<path> to BENCH_UPSTREAM/<path>.

Two instances for a round with Claude models: the default one on :8900 forwards to
api.deepseek.com; a second on :8901 with BENCH_UPSTREAM=https://api.anthropic.com (and the
Anthropic key) serves Claude Code and Arslan-on-Claude. `start_proxy.sh anthropic` starts it.

- Holds the only real key (BENCH_REAL_KEY); candidates send a dummy key, which is replaced.
- Counts usage from OpenAI-style and Anthropic-style responses, streamed or not.
- Hard cap: refuses new requests once the conservative (peak-price) total reaches BENCH_CAP_USD.
- Logs one JSON line per request to usage.jsonl (no key, no prompt text).
- Hands L3 (scripts/hands_l3): for a candidate whose name ends in "-nobatch", desktop_batch is taken
  out of the tools offered, so a run can be compared with and without batches.
"""

import json
import os
import time
import asyncio
import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse, Response
from starlette.routing import Route

UPSTREAM = os.environ.get("BENCH_UPSTREAM", "https://api.deepseek.com")
ANTHROPIC = "api.anthropic.com" in UPSTREAM
KEY = os.environ.get("BENCH_REAL_KEY", "")
CAP = float(os.environ.get("BENCH_CAP_USD", "5"))
CAND_CAP = float(os.environ.get("BENCH_RUN_CAP_USD", "1"))
LOG = os.environ.get("BENCH_LOG", "usage.jsonl")
# $/1M tokens as (cache read, uncached input, output). DeepSeek: PEAK (conservative);
# off-peak is exactly half.
# Claude: first-party list prices from the claude-api skill's model table (cached 2026-10-06),
# entered 2026-10-18 — check the live pricing page before a paid round. Claude Haiku 5.5 is
# priced up to 100K-token prompts. Cache writes cost more than plain input: see WRITE_UPLIFT.
PRICE = {
    "deepseek-v4-pro": (0.044, 1.32, 3.96),
    "deepseek-flash": (0.006, 0.30, 1.20),
    "deepseek-v4-flash": (0.006, 0.30, 1.20),
    "claude-fable-5-1": (0.25, 10.00, 50.00),
    "claude-opus-5-5": (0.20, 4.00, 20.00),
    "claude-opus-5": (0.50, 5.00, 25.00),
    "claude-sonnet-5-5": (0.20, 2.00, 10.00),
    "claude-sonnet-5": (0.20, 2.00, 10.00),
    "claude-haiku-5-5": (0.01, 0.10, 0.50),
}
# Anthropic bills a 5-minute cache write at ~1.25x input and a 1-hour write at ~2x. Writes are
# already counted as uncached input ("miss"); this adds the difference, at the 1-hour rate
# (conservative, like the rest of the caps).
WRITE_UPLIFT = 1.0
DEFAULT_PRICE = PRICE["deepseek-v4-pro"]
spent = {"total": 0.0}
per_cand = {}
lock = asyncio.Lock()


WITHHELD = {"-nobatch": "desktop_batch"}


def withhold_tools(cand, j):
    """The request body with the tools this candidate must not be offered taken out; True if any were."""
    names = {tool for suffix, tool in WITHHELD.items() if cand.endswith(suffix)}
    tools = j.get("tools")
    if not names or not isinstance(tools, list):
        return False
    kept = [t for t in tools if not (isinstance(t, dict)
                                     and ((t.get("function") or {}).get("name") in names or t.get("name") in names))]
    if len(kept) == len(tools):
        return False
    j["tools"] = kept
    return True


def cost(model, hit, miss, out, write=0):
    h, m, o = PRICE.get(model, DEFAULT_PRICE)
    return (hit * h + miss * m + write * m * WRITE_UPLIFT + out * o) / 1e6


def auth_headers(incoming: dict, key: str, anthropic: bool) -> dict:
    """The upstream's credentials in place of the candidate's dummy key. Anthropic takes only
    x-api-key: a Bearer header there means an OAuth token, not an API key."""
    headers = dict(incoming)
    if not anthropic:
        headers["authorization"] = f"Bearer {key}"
    headers["x-api-key"] = key
    return headers


def wants_usage_option(stream: bool, j: dict, path: str, anthropic: bool) -> bool:
    """OpenAI-style streams report usage only when asked (stream_options); the Anthropic API
    always reports it and rejects the unknown field."""
    return stream and "messages" in j and "/anthropic" not in path and not anthropic


def merge_usage(acc, u):
    if not isinstance(u, dict):
        return
    # OpenAI / DeepSeek
    if "prompt_tokens" in u:
        hit = u.get("prompt_cache_hit_tokens", 0) or 0
        acc["hit"] = max(acc["hit"], hit)
        acc["miss"] = max(
            acc["miss"], u.get("prompt_cache_miss_tokens", (u.get("prompt_tokens") or 0) - hit) or 0
        )
        acc["out"] = max(acc["out"], u.get("completion_tokens", 0) or 0)
    # Anthropic
    if "input_tokens" in u or "output_tokens" in u or "cache_read_input_tokens" in u:
        acc["hit"] = max(acc["hit"], u.get("cache_read_input_tokens", 0) or 0)
        acc["miss"] = max(
            acc["miss"],
            (u.get("input_tokens", 0) or 0) + (u.get("cache_creation_input_tokens", 0) or 0),
        )
        if u.get("cache_creation_input_tokens"):
            acc["write"] = max(acc.get("write", 0), u["cache_creation_input_tokens"])
        acc["out"] = max(acc["out"], u.get("output_tokens", 0) or 0)
        stu = u.get("server_tool_use") or {}
        if stu:
            acc["server_tools"] = stu


def scan(obj, acc):
    if isinstance(obj, dict):
        if "usage" in obj:
            merge_usage(acc, obj["usage"])
        for k in ("message",):
            if isinstance(obj.get(k), dict) and "usage" in obj[k]:
                merge_usage(acc, obj[k]["usage"])


async def record(cand, path, model, acc, status, t0):
    c = cost(model, acc["hit"], acc["miss"], acc["out"], acc.get("write", 0))
    async with lock:
        spent["total"] += c
        per_cand[cand] = per_cand.get(cand, 0.0) + c
        line = {
            "t": round(time.time(), 1),
            "cand": cand,
            "path": path,
            "model": model,
            "status": status,
            "hit": acc["hit"],
            "miss": acc["miss"],
            "out": acc["out"],
            "write": acc.get("write", 0),
            "usd_peak": round(c, 6),
            "total_peak": round(spent["total"], 6),
            "secs": round(time.time() - t0, 1),
        }
        if acc.get("server_tools"):
            line["server_tools"] = acc["server_tools"]
        with open(LOG, "a") as f:
            f.write(json.dumps(line) + "\n")


async def handle(request):
    cand = request.path_params["cand"]
    path = "/" + request.path_params["rest"]
    if not KEY:
        return JSONResponse(
            {"error": {"message": "BENCH_REAL_KEY is not set", "type": "config"}}, status_code=500
        )
    if spent["total"] >= CAP:
        return JSONResponse(
            {"error": {"message": f"bench budget cap ${CAP} reached", "type": "budget"}},
            status_code=402,
        )
    if per_cand.get(cand, 0.0) >= CAND_CAP:
        return JSONResponse(
            {"error": {"message": f"per-run cap ${CAND_CAP} reached", "type": "budget"}},
            status_code=402,
        )
    body = await request.body()
    model = "?"
    stream = False
    if body:
        try:
            j = json.loads(body)
            model = j.get("model", "?")
            stream = bool(j.get("stream"))
            changed = withhold_tools(cand, j)
            if wants_usage_option(stream, j, path, ANTHROPIC):
                j.setdefault("stream_options", {})["include_usage"] = True
                changed = True
            if changed:
                body = json.dumps(j).encode()
        except Exception:
            pass
    headers = auth_headers({
        k: v
        for k, v in request.headers.items()
        if k.lower()
        not in ("host", "content-length", "authorization", "x-api-key", "accept-encoding")
    }, KEY, ANTHROPIC)
    client = httpx.AsyncClient(timeout=httpx.Timeout(600, connect=30))
    req = client.build_request(
        request.method, UPSTREAM + path, params=request.query_params, headers=headers, content=body
    )
    t0 = time.time()
    resp = await client.send(req, stream=True)
    acc = {"hit": 0, "miss": 0, "out": 0}
    passthrough = {
        k: v
        for k, v in resp.headers.items()
        if k.lower()
        not in ("content-length", "content-encoding", "transfer-encoding", "connection")
    }
    if "text/event-stream" in resp.headers.get("content-type", ""):

        async def gen():
            buf = b""
            try:
                async for chunk in resp.aiter_raw():
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line.startswith(b"data:"):
                            try:
                                scan(json.loads(line[5:].strip()), acc)
                            except Exception:
                                pass
                    yield chunk
            finally:
                await resp.aclose()
                await client.aclose()
                await record(cand, path, model, acc, resp.status_code, t0)

        return StreamingResponse(gen(), status_code=resp.status_code, headers=passthrough)
    data = await resp.aread()
    await resp.aclose()
    await client.aclose()
    try:
        scan(json.loads(data), acc)
    except Exception:
        pass
    await record(cand, path, model, acc, resp.status_code, t0)
    return Response(data, status_code=resp.status_code, headers=passthrough)


async def status(request):
    return JSONResponse(
        {
            "total_peak_usd": round(spent["total"], 4),
            "cap": CAP,
            "per_cand_peak": {k: round(v, 4) for k, v in per_cand.items()},
            "cand_cap": CAND_CAP,
        }
    )


app = Starlette(
    routes=[
        Route("/_status", status),
        Route("/c/{cand}/{rest:path}", handle, methods=["GET", "POST"]),
    ]
)

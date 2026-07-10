"""Server-side executors for wired tools. One class per tool, keyed registry.

Adding a tool later = implement Executor + add to EXECUTORS + set the registry
row's status to "wired" in seed_catalog.

Server executors return {ok, ...} dicts — distinct from the CLI package's ArslanTool/ToolResult protocol.
"""
from __future__ import annotations

import base64
import ipaddress
import logging
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

from server import config
from server.db.session import AsyncSessionLocal
from server.registry.search_providers import get_provider
from server.services import chart_echarts, settings_service

logger = logging.getLogger(__name__)


def _skill_scripts_root() -> Path:
    """Root for bundled skill scripts/references: ``<data_dir>/skill_scripts``.

    Resolved from the single ``config.data_dir()`` root (unset ARSLAN_DATA_DIR -> the
    platform app-data dir, NOT CWD/data) so scripts co-locate with the brain. Mirrored
    by ``server.registry.service._skill_scripts_root`` (same value, kept in lockstep)."""
    return config.data_dir() / "skill_scripts"


class _NotUtf8(Exception):
    """A staged skill file could not be decoded as UTF-8 — turned into an honest {ok:False}."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(name)


_EXTRACT_CHAR_LIMIT = 12_000
# Fail fast on a slow page: the mini agent-loop has a small tool budget, so a page that hangs
# should surrender quickly (leaving budget + wall-clock for synthesis) rather than consuming the
# full loop timeout. 12s is generous for a real page while well under the loop's per-tool cap.
_FETCH_TIMEOUT = 12.0


def _is_private_host(url: str) -> bool:
    """SSRF guard: spawn-supplied URLs must not reach loopback/private/link-local
    hosts (incl. cloud metadata 169.254.169.254 and Arslan's own API)."""
    host = urlparse(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True  # unresolvable -> refuse
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False


def _categorize_exc(exc: Exception) -> str:
    """Map httpx/other exceptions to coarse error category strings."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"http {exc.response.status_code}"
    if isinstance(exc, httpx.HTTPError):
        return "network error"
    return "unexpected error"


async def _search_provider():
    """Build the configured provider, or None when no key is set."""
    async with AsyncSessionLocal() as db:
        key = await settings_service.get_decrypted(db, "search_api_key")
        name = (await settings_service.get_settings(db)).get("search_provider", "")
    if not key:
        return None
    return get_provider(name, api_key=key)


_MAX_REDIRECTS = 5


def _build_client() -> httpx.AsyncClient:
    # follow_redirects=False on purpose: we follow manually so every hop's host
    # is re-checked by the SSRF guard (addresses the release-gate SSRF item).
    return httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=False)


async def _fetch_text(url: str) -> str:
    async with _build_client() as client:
        current = url
        html = ""
        for _ in range(_MAX_REDIRECTS):
            resp = await client.get(current)
            if resp.is_redirect:
                location = resp.headers.get("location", "")
                if not location:
                    raise httpx.HTTPError("redirect without a Location header")
                current = urljoin(current, location)
                if _is_private_host(current):
                    raise httpx.HTTPError(
                        "redirect to a private or internal address blocked"
                    )
                continue
            resp.raise_for_status()
            html = resp.text
            break
        else:
            raise httpx.HTTPError("too many redirects")
    extracted = trafilatura.extract(html)
    return extracted or ""


class WebSearchExecutor:
    key = "web_search"

    async def execute(self, args: dict) -> dict:
        query = (args.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "missing 'query'"}
        try:
            num_results = int(args.get("num_results") or 5)
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid 'num_results'"}
        provider = await _search_provider()
        if provider is None:
            return {"ok": False,
                    "error": "web search is not configured (no API key set)"}
        try:
            results = await provider.search(query, num_results=num_results)
        except Exception as exc:  # noqa: BLE001
            category = _categorize_exc(exc)
            logger.warning("web_search failed: %s", exc, exc_info=True)
            return {"ok": False, "error": f"search failed: {category}"}
        return {"ok": True, "results": results}


class WebExtractExecutor:
    key = "web_extract"

    async def execute(self, args: dict) -> dict:
        url = (args.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "missing or invalid 'url'"}
        if _is_private_host(url):
            return {"ok": False, "error": "url resolves to a private or internal address"}
        # A page that won't fetch/parse must not send the model into a retry spiral on the same
        # URL — steer it back to the web_search result snippets it already has (or to answering).
        _STEER = " — do not retry this URL; use your web_search result snippets or answer with what you have"
        try:
            text = await _fetch_text(url)
        except Exception as exc:  # noqa: BLE001
            category = _categorize_exc(exc)
            logger.warning("web_extract failed for %s: %s", url, exc, exc_info=True)
            return {"ok": False, "error": f"fetch failed: {category}{_STEER}"}
        if not text:
            return {"ok": False, "error": f"no extractable text{_STEER}"}
        return {"ok": True, "url": url, "text": text[:_EXTRACT_CHAR_LIMIT]}


class ListMyCapabilitiesExecutor:
    """Report Arslan's OWN directly-usable capabilities: built-in tools + installed MCP
    servers. Read-only — lets Arslan answer 'what can you do / which MCPs do you have'
    from real data instead of guessing."""
    key = "list_my_capabilities"

    async def execute(self, args: dict) -> dict:
        from server.db import session as db_session
        from server.services import mcp_service, settings_service
        builtin = [
            {"key": "web_search", "desc": "联网搜索(标题/链接/摘要)"},
            {"key": "web_extract", "desc": "抓取网页正文(SSRF 防护)"},
            {"key": "render_chart", "desc": "把结构化数据画成图,用户能看到"},
        ]
        async with db_session.AsyncSessionLocal() as db:
            if await settings_service.shell_enabled(db):
                builtin.append({"key": "run_command",
                                "desc": "白名单 shell(git/gh/ffmpeg/pandoc,逐条需确认)"})
        servers = await mcp_service.list_servers()
        mcp = [{"label": s.get("label"), "status": s.get("status")} for s in servers]
        return {"ok": True, "builtin": builtin, "mcp": mcp}


_CHART_MAX_POINTS = 50
_CHART_MAX_SERIES = 8


class ChartExecutor:
    """Validates a normalized chart intent (type + labels + numeric series + flags) and
    builds a plain-data ECharts option backend-side. The model never authors render config;
    the frontend renders the option with the trusted echarts library + the Arslan theme."""

    key = "render_chart"

    async def execute(self, args: dict) -> dict:
        ctype = args.get("type")
        if ctype not in chart_echarts.CHART_TYPES:
            return {"ok": False, "error": f"invalid chart type {ctype!r}; use one of: "
                    f"{', '.join(sorted(chart_echarts.CHART_TYPES))}"}

        series = args.get("series")
        if not isinstance(series, list) or not series or len(series) > _CHART_MAX_SERIES:
            return {"ok": False, "error": f"'series' must be a non-empty list of <= {_CHART_MAX_SERIES} series"}
        for s in series:
            vals = s.get("values") if isinstance(s, dict) else None
            if not isinstance(vals, list) or not vals or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals
            ):
                return {"ok": False, "error": "each series needs a non-empty numeric 'values' list"}
            if len(vals) > _CHART_MAX_POINTS:
                return {"ok": False, "error": f"a series has more than {_CHART_MAX_POINTS} values"}

        # gauge reads a single value and needs no category axis; every other type needs x.
        x = args.get("x")
        if ctype != "gauge":
            if not isinstance(x, list) or not x or len(x) > _CHART_MAX_POINTS:
                return {"ok": False, "error": f"'x' must be a non-empty list of <= {_CHART_MAX_POINTS} labels"}

        # per-type shape checks (the option builder assumes these hold).
        if ctype in ("pie", "funnel") and len(series[0]["values"]) != len(x):
            return {"ok": False, "error": f"{ctype} needs series[0].values aligned 1:1 with 'x' ({len(x)} labels)"}
        if ctype == "radar" and any(len(s["values"]) != len(x) for s in series):
            return {"ok": False, "error": "radar needs each series' values aligned 1:1 with 'x' (the indicators)"}
        if ctype == "heatmap":
            y = args.get("y")
            if not isinstance(y, list) or not y or len(y) > _CHART_MAX_SERIES:
                return {"ok": False, "error": f"heatmap needs a non-empty 'y' list of <= {_CHART_MAX_SERIES} row labels"}
            if len(series) != len(y):
                return {"ok": False, "error": "heatmap needs exactly one series per 'y' row label"}
            if any(len(s["values"]) != len(x) for s in series):
                return {"ok": False, "error": "heatmap rows (series.values) must align 1:1 with 'x' columns"}

        spec = {"type": ctype, "title": str(args.get("title") or ""),
                "x": [str(v) for v in (x or [])], "series": series, "y": args.get("y"),
                "stacked": bool(args.get("stacked")), "horizontal": bool(args.get("horizontal")),
                "smooth": bool(args.get("smooth"))}
        try:
            option = chart_echarts.build_option(spec)
        except Exception as exc:  # noqa: BLE001 — defensive; build on a validated spec shouldn't raise
            return {"ok": False, "error": f"render failed: {exc}"}

        title = str(args.get("title") or "").strip()
        npts = len(x) if x else len(series[0]["values"])
        return {
            "ok": True,
            "external": False,
            "summary": f"已渲染 {ctype} 图" + (f"「{title}」" if title else "") +
                       f":{npts} 个数据点、{len(series)} 条系列",
            "artifact": {"kind": "echarts", "spec": option},
        }


class CreateSkillExecutor:
    """Forge a reusable method into a SkillCandidate (status 'observing'). This writes a
    human-gated DRAFT only — it does NOT make the skill live/equippable; promotion to a
    real SkillPack is a separate human action. Hence safe-tier (data/proposal in, no live
    behaviour changed). Delegates to skill_forge.create_candidate, which validates the
    SKILL.md body (## Trigger + <=15KB) and guards dup live-key / in-flight candidate."""

    key = "create_skill"

    async def execute(self, args: dict) -> dict:
        from server.services import skill_forge  # lazy: avoids import cycle at module load
        try:
            c = await skill_forge.create_candidate(
                key=args.get("key"),
                name=args.get("name"),
                category=args.get("category") or "meta",
                description=args.get("description"),
                body=args.get("body"),
                source="skill_creator",
            )
        except ValueError as exc:
            # Surface the error to the model (via the tool result) so it can fix + retry.
            return {"ok": False, "external": False, "error": str(exc)}
        return {
            "ok": True,
            "external": False,
            "summary": f"已创建技能候选「{c.name}」(观察期,待评测+人工确认后才入库)",
            "candidate_id": c.id,
            "status": c.status,
        }


_DECK_MAX_SLIDES = 40
_DECK_MAX_BULLETS = 10
_DECK_MAX_TABLE_COLS = 8
_DECK_MAX_TABLE_ROWS = 20
_DECK_MAX_CHART_CATEGORIES = 25
_DECK_MAX_CHART_SERIES = 6
_DECK_CHART_TYPES = ("bar", "column", "line", "pie")


def _is_scalar(v) -> bool:
    """A displayable cell/label value: string or real number (bool is not a number here)."""
    return isinstance(v, (str, int, float)) and not isinstance(v, bool)


def _deck_data_slide_error(i: int, s: dict) -> str | None:
    """Validate the data layouts (table / chart / kpi). Returns a clear, actionable error
    string (surfaced to the model so it can fix the spec and retry) or None if valid."""
    layout = s.get("layout")
    if layout == "table":
        headers = s.get("headers")
        if (not isinstance(headers, list) or not headers
                or len(headers) > _DECK_MAX_TABLE_COLS or not all(_is_scalar(h) for h in headers)):
            return (f"slide {i}: table 'headers' must be a non-empty list of "
                    f"<= {_DECK_MAX_TABLE_COLS} strings")
        rows = s.get("rows")
        if (not isinstance(rows, list) or not rows or len(rows) > _DECK_MAX_TABLE_ROWS
                or not all(isinstance(r, list) and len(r) == len(headers)
                           and all(_is_scalar(c) for c in r) for r in rows)):
            return (f"slide {i}: table 'rows' must be a non-empty list of "
                    f"<= {_DECK_MAX_TABLE_ROWS} rows, each a list of {len(headers)} "
                    f"string/number cells matching 'headers'")
    elif layout == "chart":
        if s.get("chart_type") not in _DECK_CHART_TYPES:
            return f"slide {i}: 'chart_type' must be one of: {', '.join(_DECK_CHART_TYPES)}"
        cats = s.get("categories")
        if (not isinstance(cats, list) or not cats or len(cats) > _DECK_MAX_CHART_CATEGORIES
                or not all(_is_scalar(c) for c in cats)):
            return (f"slide {i}: chart 'categories' must be a non-empty list of "
                    f"<= {_DECK_MAX_CHART_CATEGORIES} labels")
        series = s.get("series")
        if not isinstance(series, list) or not series or len(series) > _DECK_MAX_CHART_SERIES:
            return (f"slide {i}: chart 'series' must be a non-empty list of "
                    f"<= {_DECK_MAX_CHART_SERIES} {{name, values}} objects")
        if s["chart_type"] == "pie" and len(series) != 1:
            return f"slide {i}: pie charts take exactly one series"
        for j, ser in enumerate(series):
            if not isinstance(ser, dict):
                return f"slide {i}: series[{j}] must be an object {{name, values}}"
            vals = ser.get("values")
            if (not isinstance(vals, list)
                    or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                               for v in vals)):
                return f"slide {i}: series[{j}].values must be a list of numbers"
            if len(vals) != len(cats):
                return (f"slide {i}: series[{j}].values has {len(vals)} values but there are "
                        f"{len(cats)} categories — lengths must match")
    elif layout == "kpi":
        items = s.get("items")
        if (not isinstance(items, list) or not 2 <= len(items) <= 4
                or not all(isinstance(it, dict) and _is_scalar(it.get("value", ""))
                           and _is_scalar(it.get("label", "")) for it in items)):
            return f"slide {i}: kpi 'items' must be a list of 2-4 {{value, label}} objects"
    return None


class DeckExecutor:
    """Validates a normalized deck spec and builds a native, editable .pptx backend-side
    (python-pptx). Safe by construction — the model supplies content/structure DATA (slides +
    a closed set of layouts), never code; we build the file. Mirrors ChartExecutor. Returns the
    .pptx as a base64 artifact the frontend offers for download (a binary file, not inline)."""

    key = "render_deck"

    async def execute(self, args: dict) -> dict:
        from server.services import deck_pptx  # lazy: keeps python-pptx off the import hot path

        slides = args.get("slides")
        if not isinstance(slides, list) or not slides:
            return {"ok": False, "error": "'slides' must be a non-empty list"}
        if len(slides) > _DECK_MAX_SLIDES:
            return {"ok": False, "error": f"too many slides (max {_DECK_MAX_SLIDES})"}
        for i, s in enumerate(slides):
            if not isinstance(s, dict):
                return {"ok": False, "error": f"slide {i} must be an object"}
            if s.get("layout") not in deck_pptx.LAYOUTS:
                return {"ok": False, "error": f"slide {i}: invalid layout {s.get('layout')!r}; use one "
                        f"of: {', '.join(sorted(deck_pptx.LAYOUTS))}"}
            for field in ("bullets", "left", "right"):
                v = s.get(field)
                if v is not None and (not isinstance(v, list) or len(v) > _DECK_MAX_BULLETS
                                      or not all(isinstance(x, str) for x in v)):
                    return {"ok": False,
                            "error": f"slide {i}: '{field}' must be a list of <= {_DECK_MAX_BULLETS} strings"}
            data_err = _deck_data_slide_error(i, s)
            if data_err:
                return {"ok": False, "error": data_err}

        # Theme is a preset NAME (see deck_pptx.THEMES); unknown/non-string (e.g. the legacy
        # {'accent': '#hex'} dict) falls back to the default preset inside build_deck.
        theme = args.get("theme") if isinstance(args.get("theme"), str) else None
        spec = {"title": str(args.get("title") or ""), "theme": theme, "slides": slides}
        try:
            data = deck_pptx.build_deck(spec)
        except Exception as exc:  # noqa: BLE001 — defensive; a validated spec shouldn't raise
            return {"ok": False, "error": f"deck render failed: {exc}"}

        title = str(args.get("title") or "").strip() or "deck"
        safe = "".join(c for c in title if c.isalnum() or c in " -_（）()").strip()[:60] or "deck"
        return {
            "ok": True,
            "external": False,
            "summary": f"已生成 PPTX「{title}」:{len(slides)} 页(原生可编辑)",
            "artifact": {
                "kind": "pptx",
                "filename": f"{safe}.pptx",
                "bytes_b64": base64.b64encode(data).decode("ascii"),
                "slides": len(slides),
            },
        }


class RunPythonExecutor:
    """Sandboxed Python execution (safe-tier). The model supplies code TEXT; the sandbox
    service is the only execution path and applies every guard unconditionally: ephemeral
    tmpdir, fully scrubbed env (no keys/DB), rlimits + timeout, network denied via macOS
    seatbelt (isolation state reported honestly in the result). See services/code_sandbox."""

    key = "run_python"

    # PC-3 ① fail-closed marker convention: a skill script may DECLARE an execution need
    # the sandbox cannot satisfy via a front-matter comment on any line, e.g.
    #   # requires: network      →  needs outbound network (denied by the sandbox)
    #   # requires: cli          →  shells out to an external CLI (not available)
    # We reject BEFORE touching the sandbox with an honest "疑似需…未执行" message. This is a
    # deterministic, author-declared signal (no code analysis, no false positives).
    # IMPORTANT — this marker is an ADVISORY PRE-FLIGHT check, NOT the security boundary. The
    # REAL enforcement is the sandbox itself: seatbelt denies all network, and a script that
    # LIES about (omits) its `# requires:` marker still fails closed at runtime (its socket /
    # subprocess call is blocked by the kernel). The marker only turns an otherwise silent /
    # confusing runtime failure into an explicit, honest {ok:False, error:…} up front.
    @staticmethod
    def _scan_requires(src: str) -> tuple[str, str] | None:
        """Return (人类可读需求, 原始声明) if the source declares an unsupported need, else None."""
        import re as _re
        for line in src.splitlines():
            mm = _re.match(r"#\s*requires:\s*(.+)", line.strip(), _re.IGNORECASE)
            if not mm:
                continue
            raw = mm.group(1).strip()
            vals = {v.strip().lower() for v in _re.split(r"[,\s]+", raw) if v.strip()}
            if "network" in vals or "net" in vals:
                return "网络", raw
            if "cli" in vals or "shell" in vals or "subprocess" in vals:
                return "CLI", raw
        return None

    @staticmethod
    def _load_skill_script(ref: str) -> tuple[str, dict[str, str], dict[str, str]] | str:
        """Resolve "<skill_key>/<file>.py" inside data_dir/skill_scripts with traversal
        protection. Returns (entry_code, sibling_files, references) or an error string.
        `references` are the skill's bundled read-only docs (PC-2 storage,
        data_dir/skill_scripts/<key>/references/*.{md,txt}); the sandbox mounts them
        READ-ONLY so a script can read but never mutate them (PC-3 ②).

        Fail-closed (PC-3 ①): a well-formed ref whose entry is NOT .py, or a .py entry that
        declares a network/CLI need (`# requires:` marker), is REFUSED here with an honest
        error — the sandbox is never invoked (execute() returns on the error string)."""
        import re as _re
        # Accept any well-formed "<key>/<file>.<ext>" so a non-.py entry produces the honest
        # "只支持 .py" message rather than a confusing generic "invalid format".
        m = _re.fullmatch(r"([a-z0-9-]+)/([A-Za-z0-9._-]+\.[A-Za-z0-9]+)", (ref or "").strip())
        if not m:
            return "invalid 'skill_script' — expected '<skill-key>/<file>.py'"
        ext = "." + m.group(2).rsplit(".", 1)[-1].lower()
        if ext != ".py":
            return f"此脚本需 非python:{ext},当前沙箱只支持 .py,未执行"
        root = _skill_scripts_root().resolve()
        skill_dir = (root / m.group(1)).resolve()
        entry = (skill_dir / m.group(2)).resolve()
        if not str(entry).startswith(str(root) + "/") or not entry.is_file():
            return f"skill script not found: {ref}"

        # Honest read: a non-UTF-8 file must return {ok:False} (via the error string), never
        # raise UnicodeDecodeError to an unhandled crash. Returns text or an error string.
        def _read(p) -> str:
            try:
                return p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                raise _NotUtf8(p.name) from None

        try:
            entry_code = _read(entry)
            need = RunPythonExecutor._scan_requires(entry_code)
            if need:
                kind, raw = need
                return f"此脚本疑似需 {kind}(脚本声明 requires: {raw}),当前沙箱不支持,未执行"
            siblings = {p.name: _read(p)
                        for p in skill_dir.iterdir()
                        if p.is_file() and p.suffix == ".py" and p != entry}
            # Bundled references (PC-2): read-only docs the script may need. Only the .md/.txt
            # basenames PC-2 stores; their CONTENT is copied — the stored originals are never
            # handed to the sandbox, and the sandbox places the copies read-only (PC-3 ②).
            ref_dir = (skill_dir / "references")
            references = {p.name: _read(p)
                          for p in (ref_dir.iterdir() if ref_dir.is_dir() else [])
                          if p.is_file() and p.suffix in (".md", ".txt")}
        except _NotUtf8 as exc:
            return f"技能文件不是有效 UTF-8:{exc.name},未执行"
        return entry_code, siblings, references

    async def execute(self, args: dict) -> dict:
        from server.services import code_sandbox  # lazy import keeps boot path light
        extra_files: dict[str, str] | None = None
        read_only_files: dict[str, str] | None = None
        code = args.get("code") or ""
        if args.get("skill_script"):
            loaded = self._load_skill_script(str(args["skill_script"]))
            if isinstance(loaded, str):
                return {"ok": False, "external": False, "error": loaded}
            code, extra_files, references = loaded
            read_only_files = references or None
        result = await code_sandbox.run_python(
            code, extra_files=extra_files, read_only_files=read_only_files)
        if not result.get("ok"):
            # Keep `sandboxed`/`network_isolated` on the failure path too, so a refused or
            # unsandboxed run is auditable in the run trace / RunStep detail (P0-1 决定①a).
            return {"ok": False, "external": False,
                    "error": result.get("error") or "execution failed",
                    **{k: result[k]
                       for k in ("stdout", "stderr", "exit_code", "sandboxed", "network_isolated")
                       if k in result}}
        n_files = len(result.get("files") or [])
        summary = (f"已执行 Python:exit 0,stdout {len(result.get('stdout') or '')} 字"
                   + (f",生成 {n_files} 个文件" if n_files else "")
                   + ("" if result.get("network_isolated") else "(本次未网络隔离)"))
        return {"ok": True, "external": False, "summary": summary, **result}


class RunCommandExecutor:
    """Orchestrator-only whitelisted shell (spec). Arslan-tier — spawns can never
    reach this (tier gate + host-only exposure). Validates against command_policy
    then runs in the seatbelt command sandbox. Confirmation is enforced UPSTREAM in
    tool_loop (this executor assumes the user already approved)."""

    key = "run_command"

    async def execute(self, args: dict) -> dict:
        from server.services import command_policy, command_sandbox
        command = (args.get("command") or "").strip()
        argv = args.get("argv")
        if argv is None:
            argv = []
        verdict = command_policy.validate(command, argv)
        if not verdict["ok"]:
            return {"ok": False, "error": verdict["reason"]}
        if command_policy.is_network_command(command, argv):
            # Network git/gh: run through the host allowlist + credential-injecting proxy so the
            # real token never enters the sandbox (see command_net). Local commands stay fully offline.
            from server.services import command_net
            result = await command_net.run_network_command(command, argv)
        else:
            result = await command_sandbox.run_command(command, argv)
        pretty = " ".join([command, *argv])
        # SECURITY: command stdout/stderr can carry attacker-influenced text, so we do
        # NOT mark results external:False — tool_loop wraps them (wrap_external) and the
        # LLM treats them as untrusted, consistent with the web tools (spec §组件2).
        if not result.get("ok"):
            return {"ok": False,
                    "error": result.get("error") or "command failed",
                    **{k: result[k] for k in ("stdout", "stderr", "exit_code") if k in result}}
        return {"ok": True,
                "summary": f"已执行 `{pretty}`:exit 0,stdout {len(result.get('stdout') or '')} 字",
                **result}


class ReadSkillExecutor:
    """safe-tier read-only: read one registered skill's body (optionally one section).
    Caged to the registry — reads ONLY SkillPack.body by validated key, never the
    filesystem. A no-section full-text over the cap returns the first half + TOC to
    steer the spawn toward segmented reads."""
    key = "read_skill"
    _READ_SKILL_CAP = 8000

    async def execute(self, args: dict) -> dict:
        import re as _re
        from server.db import session as _db
        from server.db.models import SkillPack
        skey = (args.get("key") or "").strip()
        if not _re.fullmatch(r"[a-z0-9-]+", skey):
            return {"ok": False, "external": False, "error": "invalid skill key"}
        async with _db.AsyncSessionLocal() as db:
            row = await db.get(SkillPack, skey)
        if row is None or not (row.body or "").strip():
            return {"ok": False, "external": False, "error": f"skill not found or empty: {skey}"}
        body = row.body.strip()
        section = (args.get("section") or "").strip()
        if section.startswith("references/"):
            # Read a bundled reference from data_dir/skill_scripts/<key>/references/ (stored at
            # import time, PC-2). Caged: validated basename, resolve() traversal guard, read-only.
            fname = section[len("references/"):]
            if not _re.fullmatch(r"[A-Za-z0-9._-]+\.(md|txt)", fname):
                return {"ok": False, "external": False, "error": "invalid reference filename"}
            root = (_skill_scripts_root() / skey / "references").resolve()
            target = (root / fname).resolve()
            if not str(target).startswith(str(root) + "/") or not target.is_file():
                return {"ok": False, "external": False, "error": f"reference not found: {section}"}
            # Honest read: a non-UTF-8 reference must not crash — replace undecodable bytes
            # rather than raise UnicodeDecodeError (mirrors _load_skill_script._read's guard).
            try:
                text = target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = target.read_text(encoding="utf-8", errors="replace")
            return {"ok": True, "external": False, "body": text[:self._READ_SKILL_CAP],
                    "summary": f"技能 {skey} · {section}"}
        if section:
            lines = body.splitlines()
            out, capturing = [], False
            for ln in lines:
                s = ln.strip()
                if _re.match(r"#{2,3}\s+\S", s):
                    if capturing:
                        break
                    if s == section or s.lstrip("# ").strip() == section.lstrip("# ").strip():
                        capturing = True
                if capturing:
                    out.append(ln)
            if not out:
                return {"ok": False, "external": False, "error": f"section not found: {section}"}
            sect = "\n".join(out)
            if len(sect) > self._READ_SKILL_CAP:  # cap like the other branches
                sect = (sect[:self._READ_SKILL_CAP].rsplit("\n", 1)[0]
                        + "\n\n[本节过长已截断,用更细 section 读取]")
            return {"ok": True, "external": False, "body": sect,
                    "summary": f"技能 {skey} · {section}"}
        if len(body) <= self._READ_SKILL_CAP:
            return {"ok": True, "external": False, "body": body, "summary": f"技能 {skey}(全文)"}
        toc = [ln.strip() for ln in body.splitlines() if _re.match(r"#{2,3}\s+\S", ln.strip())]
        head = body[:self._READ_SKILL_CAP].rsplit("\n", 1)[0]
        note = ("\n\n[正文过长, 以上为前半。请按章节读取: read_skill(key, section='## 标题')。目录:\n"
                + "\n".join(f"- {t}" for t in toc) + "]")
        return {"ok": True, "external": False, "body": head + note,
                "summary": f"技能 {skey}(前半+目录)"}


EXECUTORS = {e.key: e for e in (
    WebSearchExecutor(), WebExtractExecutor(), ChartExecutor(), CreateSkillExecutor(),
    DeckExecutor(), RunPythonExecutor(), RunCommandExecutor(), ListMyCapabilitiesExecutor(),
    ReadSkillExecutor(),
)}


async def resolve_executor(tool_key: str):
    """Route a tool key to its executor: built-in (static EXECUTORS), MCP proxy, or None.
    Does NOT widen assignability — the SQL choke point still decides which keys reach here."""
    if tool_key in EXECUTORS:
        return EXECUTORS[tool_key]
    if tool_key.startswith("mcp_"):
        from server.mcp.executor import build_mcp_executor   # lazy: avoids import cycle
        return await build_mcp_executor(tool_key)
    return None

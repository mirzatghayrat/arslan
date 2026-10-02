"""Catch answers that deny a capability the turn actually had (0.1.50 P2 S4).

Kernel bench T2/T3: "当前环境没有提供文件系统写入能力" / "我无法直接把文件写入…"
while write_file, edit_file and run_command were offered and no save had
failed. A system-prompt rule against this already existed. A deterministic
check bounces such an answer once, unless a write genuinely failed.
"""
from __future__ import annotations

import re

WRITE_TOOLS = frozenset({"write_file", "edit_file", "run_command"})
WEB_TOOLS = frozenset({"web_search", "web_extract", "browser_open"})

_DENY_WRITE = re.compile(
    r"(无法|不能|没法|没有办法|不可以)[^。，,；;]{0,24}?(写入|保存|创建|生成|存)[^。]{0,12}(文件|文件夹|目录|表格|到)"
    r"|(没有|未|不具备|缺少)(提供)?(文件系统|文件)?(写入|写文件|保存文件|文件写入)(的)?(权限|能力|工具)"
    r"|(环境|当前)[^。]{0,12}(没有|不支持|无)[^。]{0,8}(写入|写文件|文件系统)"
    r"|\b(cannot|can't|can ?not|unable to|am not able to)\s+(directly\s+)?(write|save|create)\b[^.]{0,40}\b(file|folder|directory|disk|workspace)"
    r"|\b(no|don't have|do not have|lack)\s+(file[- ]?system|file|write)\s+(access|permission|capabilit)",
    re.I)
_DENY_WEB = re.compile(
    r"(无法|不能|没有)(访问|连接)?(互联网|联网|上网)(的)?(能力|权限)?"
    r"|\b(cannot|can't|unable to)\s+(access|browse|reach)\s+the\s+(internet|web)\b|\bno internet access\b",
    re.I)
_WRITE_REFUSED = re.compile(r"permission denied|operation not permitted|read-only file system|outside (the )?workspace"
                            r"|not allowed|refused", re.I)


def _write_genuinely_failed(tool_trace: list[dict]) -> bool:
    for item in tool_trace:
        if item.get("tool") in WRITE_TOOLS and not (item.get("result") or {}).get("ok"):
            result = item.get("result") or {}
            text = " ".join(str(result.get(k) or "") for k in ("error", "stderr", "code"))
            if _WRITE_REFUSED.search(text):
                return True
    return False


def denied_capability(answer: str, wired_keys: set[str], tool_trace: list[dict]) -> str | None:
    """"write" / "web" when the answer denies a capability the turn had, else None."""
    if not answer:
        return None
    if wired_keys & WRITE_TOOLS and _DENY_WRITE.search(answer) and not _write_genuinely_failed(tool_trace):
        return "write"
    if wired_keys & WEB_TOOLS and _DENY_WEB.search(answer):
        return "web"
    return None


def correction(kind: str, wired_keys: set[str]) -> str:
    if kind == "write":
        tools = ", ".join(sorted(wired_keys & WRITE_TOOLS))
        return ("Your answer says you cannot write or save files, but this turn has " + tools +
                " for the workspace folder. Save the deliverable now with one of them. If a save actually "
                "failed, quote the exact error instead of saying you have no ability.")
    tools = ", ".join(sorted(wired_keys & WEB_TOOLS))
    return ("Your answer says you cannot access the web, but this turn has " + tools +
            ". Use them, or name the specific page or error that blocked you.")

"""What a proposed answer gives away before it is shown: a claim no tool backs, a promise instead of an answer, a tool
call written as text (split from tool_loop, LOOP1 c1a)."""
from __future__ import annotations

import re

from server.orchestrator.json_protocol import first_json_object, parse_json_object


_CLAIMS_CHART_RE = re.compile(
    r"上图|已生成图|已为您生成|已绘制|图表已|chart (is )?(generated|ready|done)|here('s| is) (the|your) chart",  # lang-check: allow
    re.IGNORECASE)
#: "No search was needed" (「不需要搜索了」, 「无需再搜索了」, 「不用去搜索了」) is no claim: each negation, bare or with
#: 「再」 / 「去」 before the verb, as its own fixed-width lookbehind.
_NOT_SEARCHED = "".join(f"(?<!{no}{adverb})" for no in ("没", "未", "不", "不用", "无需", "不必", "需要", "没有")  # lang-check: allow
                        for adverb in ("", "再", "去"))
_CLAIMS_SEARCH_RE = re.compile(
    r"我搜索|" + _NOT_SEARCHED + r"搜索了|获取到(了|的)?数据|我已搜|i (just )?searched|let me search"  # lang-check: allow
    r"|i looked it up",
    re.IGNORECASE)
#: K8a: 「查到」 alone claims no web search (memory, a command or a file finds things too; "say how it was found",
#: 「说明是怎么查到的」, sent run 492 back three times). It does after a web word in the same clause (「我在网上查到了」),
#: unless the clause is advice or how-to (「你可以在网上查到」, 「怎么在网上查到」, 「建议上网查到…」) or says nothing was
#: found (「网上没有查到」). #694 review.
#: 「网络上」 only, never bare 「网络」 or 「网络中」: 「网络设置里查到…」 and 「本地网络中查到…」 are local (#698 review).
_WEB_FOUND_RE = re.compile(r"(网上|在线|上网|联网|网页|网络上|搜索引擎)[^。！？，、；\n]{0,6}查到")  # lang-check: allow
_ADVICE_WORDS = ("可以", "怎么", "如何", "建议")  # lang-check: allow
#: 「可」 / 「能」 / 「去」 are advice only right before the web word (「可在网上」, 「去网上」) or right before 「查到」
#: (「都能查到」), and not as the end of 「可能」, 「功能」 or 「过去」 (#694 follow-up).
_ADVICE_BEFORE_WEB = re.compile(r"(?:(?<![可功])能|可|(?<!过)去)[在到]?$")  # lang-check: allow
_ADVICE_BEFORE_FOUND = re.compile(r"(?:(?<![可功])能|可)$")  # lang-check: allow
_NOT_FOUND = ("没", "未", "没有", "未能")  # lang-check: allow


def _claims_web_found(text: str) -> bool:
    for match in _WEB_FOUND_RE.finditer(text):
        clause_start = max(text.rfind(mark, 0, match.start()) for mark in "。！？，、；\n") + 1
        clause = text[clause_start:match.end()]
        before = text[:match.end() - 2]
        # The single-character checks look only at the few characters before (lookbehind still sees past `pos`).
        advice = (any(word in clause for word in _ADVICE_WORDS)
                  or _ADVICE_BEFORE_WEB.search(text, max(clause_start, match.start() - 3), match.start())
                  or _ADVICE_BEFORE_FOUND.search(text, max(match.start(), len(before) - 2), len(before)))
        if not advice and not before.endswith(_NOT_FOUND):
            return True
    return False


def _claims_chart(text: str) -> bool:
    return bool(_CLAIMS_CHART_RE.search(text or ""))


def _claims_search(text: str) -> bool:
    return bool(_CLAIMS_SEARCH_RE.search(text or "")) or _claims_web_found(text or "")


# Chart-as-code-fence: instead of calling render_chart, the model draws a DATA chart by writing a
# Markdown code block (```mermaid xychart-beta / ```mermaid pie / ```chart / bare ```xychart-beta).
# The UI shows a raw code block with a "Copy" button, not a real ECharts chart. Distinct from
# _claims_chart (which catches "上图已生成" claims): here the model neither claims nor promises — it
# literally hands over chart source. Matches ONLY data charts render_chart can produce; a mermaid
# flowchart / sequenceDiagram is a legit diagram render_chart CANNOT draw, so it must not trip this.
_DRAWS_CHART_FENCE_RE = re.compile(
    r"```\s*chart\b"                                       # ```chart generic fence
    r"|```\s*(?:mermaid\s+)?xychart[\w-]*"                 # ```xychart-beta or ```mermaid xychart...
    r"|```\s*mermaid\b[\s\S]{0,80}?"                       # ```mermaid then, in the block head,
    r"(?:xychart-beta|\bpie\s+(?:title|showData))",        #   an xychart/pie declaration
    re.IGNORECASE)


def _draws_chart_fence(text: str) -> bool:
    return bool(_DRAWS_CHART_FENCE_RE.search(text or ""))


# Forward-promise patterns: the model ends its turn PROMISING a future tool action instead of
# emitting the tool JSON ("数据正在路上", "马上为您绘制…", "我这就去搜索", "STEP 2: 调用 web_extract",
# "let me search"). Distinct from the _CLAIMS_* regexes above, which catch the inverse — claiming
# a result already produced. Tight on purpose (anchored on first-person / imperative + a tool-action
# verb) so a complete answer that merely mentions next steps doesn't trip it.
_PROMISES_ACTION_RE = re.compile(
    r"正在(为您|帮您|努力)?\s*(路上|搜索|查询|抓取|获取|拉取|加载|生成|绘制|出图|制作)"  # lang-check: allow
    r"|数据\s*(正在|马上|即将|这就)\s*(路上|赶来|送达|生成|呈现)"  # lang-check: allow
    r"|(马上|这就|现在就|立刻|立即|即将)\s*(去|来)?\s*(为您|帮您|给您)?\s*(搜索|查询|查一下|抓取|获取|拉取|生成|绘制|出图|画|制作|呈现|调用)"  # lang-check: allow
    # first-person promise: 「我来」/「让我」/「现在让我(继续)」 + a tool-action verb. Anchored on 「我」/「让我」 so a
    # completed answer that says "接下来你可以自行搜索" (second-person) never trips it.
    r"|(现在)?\s*(我|让我)\s*(来|去|先|这就|马上|现在就|继续)?\s*(为您|帮您)?\s*"  # lang-check: allow
    r"(搜索|查|查询|抓取|获取|拉取|绘制|生成|画|制作|调用)"  # lang-check: allow
    # promising a chart/figure: 「生成/绘制/画/制作」 … a NAMED chart type. Must be a specific chart noun
    # (「图表/趋势图/柱状图/…」), NOT the bare "图" — bare "画图" is the render_chart CAPABILITY's common
    # name and legitimately appears in capability answers (e.g. "我有内置的…画图"); matching it there
    # falsely rejects a good answer into the digest/「继续」 floor.
    r"|(以便|接着|然后)?\s*(生成|绘制|画|制作|输出)\s*[^。\n]{0,8}(图表|趋势图|全景图|示意图|柱状图|折线图|饼图|散点图)"  # lang-check: allow
    # STEP narration: 'STEP <anything-short> 调取/搜索/获取/生成…' — the icon/number between STEP and
    # the verb is arbitrary (we saw 'STEP <icon> 调取各项目详情'), so match loosely.
    r"|STEP\s*\S{0,4}\s*(调用|调取|搜索|抓取|获取|查询|绘制|生成|call|search|fetch|generate)"  # lang-check: allow
    r"|第\s*[一二三四五六七八九十\d]+\s*步\s*[:：]?\s*(调用|调取|搜索|抓取|获取)"  # lang-check: allow
    r"|(下一步|接下来)\s*[，,：:]?\s*(我|让我)\s*(会|要|将|就|继续)?\s*(搜索|查询|抓取|获取|绘制|生成|调用)"  # lang-check: allow
    r"|调用\s*(web_search|web_extract|render_chart)"  # lang-check: allow
    r"|(生成|制作|输出|导出)\s*[^。\n]{0,6}(deck|pptx|\.pptx|幻灯|演示|ppt)"  # lang-check: allow
    r"|let me (search|look this up|fetch|pull|grab|draw|generate|chart|get the data)"
    r"|i(?:'ll| will| am going to|'m going to)\s+(?:now\s+|quickly\s+|go\s+)?"
    r"(search|fetch|pull|retrieve|draw|generate|chart|look up|gather)",
    re.IGNORECASE)


def _promises_action(text: str) -> bool:
    return bool(_PROMISES_ACTION_RE.search(text or ""))


# A genuine deferral ("让我继续查各项目的 star 数" with no tool call and no real content) is SHORT.
# A substantive answer that merely MENTIONS action verbs — a capability rundown
# ("我能搜索、抓取网页、画图表"), a plan, a summary that describes what tools do — is long and IS the answer. Rejecting the
# latter as "still promising action" was the bug behind: capability answers → digest/「继续」 floor, and
# good synthesized answers bounced. So only treat a promise as a deferral to reject when it's ALSO
# short/stub-like; keep any substantive answer regardless of the action words in it.
_DEFERRAL_MAX = 160


def _is_deferral_stub(text: str) -> bool:
    t = (text or "").strip()
    return len(t) < _DEFERRAL_MAX and _promises_action(t)


# What a tool call written as text looks like, in every provider's shape. One list: _embeds_protocol
# judges a whole answer with it, and K8a's streaming holds back the tail of a reply against it.
_PROTOCOL_PATTERNS = (
    # Some providers render a proposed call as XML instead of native tool_calls, including an unfinished
    # opening tag.
    re.compile(r'<\s*/?\s*(?:tool_call|tool_calls|function_call)(?=[\s>/]|$)', re.I),
    # DeepSeek's own chat-template tokens leaking into content instead of native tool_calls (seen in the
    # 0.1.49 bench: "<｜｜DSML｜｜tool_calls>", and V3's "<｜tool▁calls▁begin｜>").
    re.compile(r'[｜|]\s*DSML\s*[｜|]|<\s*[｜|]+\s*(?:DSML\s*[｜|]+\s*)?/?\s*(?:tool[▁_ ]?calls?|invoke)', re.I),
    re.compile(r'\{\s*"(?:tool|tool_calls|function_call|functionCall|escalate)"\s*:'),
)


def _embeds_protocol(text: str) -> bool:
    """True if `text` is / EMBEDS a tool-call or escalate JSON in ANY provider's shape (even behind
    a prose prefix like 'Let me search…{…}'). Covers OpenAI/DeepSeek ({"tool"} / {"tool_calls"} /
    {"function_call"}), Gemini ({"functionCall"}), and our escalate object. A finished answer is
    prose — it never surfaces one of these as the reply."""
    # Detection is deliberately stricter than parsing for dispatch: malformed
    # quotes or an interrupted object must not turn a proposed action into an
    # answer. This only rejects text; it never repairs JSON or executes a call,
    # nor grants the proposed action permission.
    if any(pattern.search(text or "") for pattern in _PROTOCOL_PATTERNS):
        return True
    obj = first_json_object(text or "") or parse_json_object(text or "")
    if not isinstance(obj, dict):
        return False
    return bool(obj.get("tool") or obj.get("tool_calls") or obj.get("function_call")
                or obj.get("functionCall") or isinstance(obj.get("escalate"), dict))


def _unverified_claim(text: str, tool_trace: list, wired_keys: set[str]) -> str | None:
    """Claims are not receipts. Check this before displaying a proposed answer."""
    if "<!doctype html" in text.lower() and "</html>" in text.lower():
        return None
    succeeded = {step.get("tool") for step in tool_trace if (step.get("result") or {}).get("ok")}
    if (_claims_chart(text) or (_draws_chart_fence(text) and "render_chart" in wired_keys)) and "render_chart" not in succeeded:
        return "render_chart"
    if _claims_search(text) and "web_search" not in succeeded:
        return "web_search"
    return None

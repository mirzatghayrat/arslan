"""repo_overview — a plain-language intro for NON-programmers (user ask 2026-08-20).

The dossier's old "value for Arslan" line was "无法确定" for every non-MCP repo
(a hardcoded fallback) plus a copyleft warning — useless to someone deciding
whether a project is for them. This produces {what, use_cases}: one plain
sentence saying what the project is, and 2-3 concrete everyday scenarios —
grounded in the description/README, no jargon. Conservative like mcp_suggest:
any error/unparseable → a safe empty shape the UI can hide.
"""

from server.services import repo_overview


class _Resp:
    def __init__(self, content):
        self.content = content


def _stub_adapter(monkeypatch, content):
    class _A:
        async def chat(self, system, user):
            return _Resp(content)

    async def _build(role):
        return _A()
    monkeypatch.setattr(repo_overview, "build_adapter", _build)


async def test_parses_what_and_use_cases(monkeypatch):
    _stub_adapter(monkeypatch,
                  '{"what": "A screenshot tool for your desktop.", '
                  '"use_cases": ["Grab a region of your screen", "Annotate a bug report", "Share a snip"]}')
    out = await repo_overview.explain({"full_name": "o/flameshot", "description": "screenshot",
                                       "topics": ["capture"]}, "readme text")
    assert out["what"] == "A screenshot tool for your desktop."
    assert len(out["use_cases"]) == 3
    assert out["use_cases"][0] == "Grab a region of your screen"


async def test_caps_use_cases_at_three(monkeypatch):
    _stub_adapter(monkeypatch,
                  '{"what": "x", "use_cases": ["a", "b", "c", "d", "e"]}')
    out = await repo_overview.explain({"full_name": "o/r"}, "")
    assert len(out["use_cases"]) == 3           # keep the card scannable


async def test_llm_error_yields_empty_shape(monkeypatch):
    async def _boom(role):
        raise RuntimeError("model down")
    monkeypatch.setattr(repo_overview, "build_adapter", _boom)
    out = await repo_overview.explain({"full_name": "o/r"}, "")
    assert out == {"what": "", "use_cases": []}   # UI hides an empty overview


async def test_unparseable_yields_empty_shape(monkeypatch):
    _stub_adapter(monkeypatch, "I think this is a nice project!")
    out = await repo_overview.explain({"full_name": "o/r"}, "")
    assert out == {"what": "", "use_cases": []}


async def test_non_string_use_cases_dropped(monkeypatch):
    _stub_adapter(monkeypatch, '{"what": "x", "use_cases": ["ok", 42, null, "fine"]}')
    out = await repo_overview.explain({"full_name": "o/r"}, "")
    assert out["use_cases"] == ["ok", "fine"]     # only strings survive

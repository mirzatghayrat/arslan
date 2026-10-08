"""0.1.57 P1: finding capabilities — the official MCP Registry, GitHub, reviewed skill libraries."""
import inspect
import re
import pathlib

import httpx
import pytest

from server.services import capability_search as cs
from server.services import github_eval

MIT = "Permission is hereby granted, free of charge, to any person obtaining a copy"
PROPRIETARY = "© Anthropic, PBC. All rights reserved. Use is subject to the terms of service."


def reg(name, version, *, packages=None, remotes=None, repo=None, description="Reads and writes Excel files"):
    server = {"name": name, "version": version, "description": description}
    if repo:
        server["repository"] = {"url": f"https://github.com/{repo}", "source": "github"}
    if packages is not None:
        server["packages"] = packages
    if remotes is not None:
        server["remotes"] = remotes
    return {"server": server, "_meta": {}}


PYPI = lambda v: [{"registryType": "pypi", "identifier": "excel-mcp-server", "version": v,  # noqa: E731
                   "runtimeHint": "uvx", "transport": {"type": "stdio"},
                   "environmentVariables": [{"name": "EXCEL_FILES_PATH", "isRequired": False}]}]

REGISTRY = {"servers": [
    reg("io.github.haris-musa/excel-mcp-server", "1.1.0", packages=PYPI("1.1.0"), repo="haris-musa/excel-mcp-server"),
    reg("io.github.haris-musa/excel-mcp-server", "1.1.2", packages=PYPI("1.1.2"), repo="haris-musa/excel-mcp-server"),
    reg("io.github.haris-musa/excel-mcp-server", "1.1.10", packages=PYPI("1.1.10"), repo="haris-musa/excel-mcp-server"),
    reg("com.example/excel-cloud", "0.2", remotes=[{"type": "streamable-http", "url": "https://mcp.example.com/excel",
        "headers": [{"name": "Authorization", "isSecret": True, "isRequired": True, "description": "Bearer token"}]}]),
    reg("io.github.someone/excel-dotnet", "2.0", packages=[{"registryType": "nuget", "identifier": "X", "version": "2.0"}],
        repo="someone/excel-dotnet"),
    reg("io.github.empty/excel-nothing", "0.1"),
]}

GITHUB_SEARCH = {"items": [
    {"full_name": "haris-musa/excel-mcp-server", "html_url": "https://github.com/haris-musa/excel-mcp-server",
     "stargazers_count": 4212, "license": {"spdx_id": "MIT"}, "pushed_at": "2026-09-28T00:00:00Z",
     "description": "Excel MCP server", "topics": ["mcp-server", "excel"]},
    {"full_name": "openpyxl-mirror/openpyxl", "html_url": "https://github.com/openpyxl-mirror/openpyxl",
     "stargazers_count": 900, "license": {"spdx_id": "MIT"}, "pushed_at": "2026-09-01T00:00:00Z",
     "description": "Python library to read/write Excel files", "topics": ["excel", "python"]},
    {"full_name": "acme/excel-mcp-gpl", "html_url": "https://github.com/acme/excel-mcp-gpl",
     "stargazers_count": 50, "license": {"spdx_id": "GPL-3.0"}, "pushed_at": "2026-01-01T00:00:00Z",
     "description": "Excel MCP", "topics": []},
    {"full_name": "bob/excel-skills", "html_url": "https://github.com/bob/excel-skills",
     "stargazers_count": 12, "license": None, "pushed_at": "2025-01-01T00:00:00Z",
     "description": "Excel skills for agents", "topics": ["claude-skills"]},
]}

#: Published in the registry under the usual name, but not found by the registry's own search.
LOOKUP = {"io.github.openpyxl-mirror/openpyxl": None,
          "io.github.acme/excel-mcp-gpl": reg("io.github.acme/excel-mcp-gpl", "0.3", repo="acme/excel-mcp-gpl",
                                              packages=[{"registryType": "npm", "identifier": "excel-mcp-gpl",
                                                         "version": "0.3", "transport": {"type": "stdio"}}])}

#: What GitHub knows of repositories the registry names (for the batch lookup).
REPOS = [
    {"full_name": "someone/excel-dotnet", "html_url": "https://github.com/someone/excel-dotnet", "stargazers_count": 3,
     "license": None, "pushed_at": "2026-09-28T00:00:00Z", "description": "", "topics": []},
]

SKILL = lambda name, desc: f"---\nname: {name}\ndescription: {desc}\n---\n# {name}\nDo the thing.\n"  # noqa: E731
LIB_SHA = "abc123def4567890abc123def4567890abc12345"
RAW = {
    "skills/xlsx/SKILL.md": SKILL("xlsx", "Work with Excel spreadsheets"),
    "skills/xlsx/LICENSE.txt": PROPRIETARY,
    "skills/csv-tidy/SKILL.md": SKILL("csv-tidy", "Tidy CSV and excel exports"),
    "skills/csv-tidy/LICENSE.txt": MIT,
    "skills/poetry/SKILL.md": SKILL("poetry", "Write poems"),
}


def library_archive() -> bytes:
    """What codeload serves: a tar.gz whose pax header names the commit (as GitHub's do)."""
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT,
                      pax_headers={"comment": LIB_SHA}) as tar:
        for path, text in RAW.items():
            data = text.encode()
            info = tarfile.TarInfo(f"skills-HEAD/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class Net:
    """One fake internet for every httpx client in the search."""

    def __init__(self):
        self.calls, self.fail = [], set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        host = request.url.host
        if host in self.fail:
            raise httpx.ConnectError("down", request=request)
        if host == "registry.modelcontextprotocol.io":
            if request.url.path.startswith("/v0/servers/"):
                name = request.url.path.split("/v0/servers/", 1)[1].split("/versions/")[0].replace("%2F", "/")
                entry = LOOKUP.get(name)
                return httpx.Response(200, json=entry) if entry else httpx.Response(404, json={})
            return httpx.Response(200, json=REGISTRY)
        if host == "api.github.com":
            path = request.url.path
            if path == "/search/repositories":
                q = request.url.params.get("q", "")
                if "repo:" in q:                      # the batch lookup of registry entries
                    wanted = {r.lower() for r in re.findall(r"repo:(\S+)", q)}
                    return httpx.Response(200, json={"items": [i for i in REPOS if i["full_name"].lower() in wanted]})
                return httpx.Response(200, json=GITHUB_SEARCH)
            if path == "/repos/haris-musa/excel-mcp-server":
                return httpx.Response(200, json={"full_name": "haris-musa/excel-mcp-server", "stargazers_count": 4212,
                                                 "license": {"spdx_id": "MIT"}, "pushed_at": "2026-09-28T00:00:00Z"})
            if path == "/repos/someone/excel-dotnet":
                return httpx.Response(200, json={"full_name": "someone/excel-dotnet", "stargazers_count": 3,
                                                 "license": None, "pushed_at": "2026-09-28T00:00:00Z"})
            return httpx.Response(404, json={})
        if host == "codeload.github.com":
            return httpx.Response(200, content=library_archive()) if request.url.path == "/anthropics/skills/tar.gz/HEAD" \
                else httpx.Response(404)
        return httpx.Response(404)


@pytest.fixture
def net(monkeypatch):
    fake = Net()
    real = httpx.AsyncClient

    class Client(real):
        def __init__(self, *a, **kw):
            kw.setdefault("transport", httpx.MockTransport(fake.handler))
            super().__init__(*a, **kw)
    monkeypatch.setattr(httpx, "AsyncClient", Client)

    async def no_token():
        return ""
    monkeypatch.setattr(github_eval, "_token", no_token)
    cs.clear_cache()
    yield fake
    cs.clear_cache()


def by_id(result, prefix):
    return [c for c in result["candidates"] if c["id"].startswith(prefix)]


# ── keywords ─────────────────────────────────────────────────────────────────

def test_keywords_are_latin_words_given_ones_first_without_filler():
    assert cs.keywords("read the formulas in my Excel file", ["xlsx"]) == ["xlsx", "formulas", "excel"]
    assert cs.keywords("帮我读 Excel 公式") == ["excel"]
    assert cs.keywords("帮我核对预算表的公式") == []
    assert len(cs.keywords("a b alpha beta gamma delta epsilon")) == 4


# ── the registry ─────────────────────────────────────────────────────────────

async def test_the_registry_keeps_the_newest_version_and_says_how_each_would_run(net):
    async with httpx.AsyncClient() as client:
        found = {c.name: c for c in await cs.search_registry(client, "excel")}
    excel = found["excel-mcp-server"]
    assert excel.version == "1.1.10"                      # 1.1.10 > 1.1.2 (not string order)
    assert excel.runtime == "uv" and excel.package["identifier"] == "excel-mcp-server"
    assert excel.package["version"] == "1.1.10" and excel.repo == "haris-musa/excel-mcp-server"
    assert excel.needs["keys"] == [{"name": "EXCEL_FILES_PATH", "secret": False, "required": False, "description": ""}]
    cloud = found["excel-cloud"]
    assert cloud.runtime == "remote" and cloud.remote["url"] == "https://mcp.example.com/excel"
    assert cloud.needs["network"] is True and cloud.needs["keys"][0]["secret"] is True
    assert found["excel-dotnet"].not_here == "needs_dotnet" and found["excel-dotnet"].runtime is None
    assert found["excel-nothing"].not_here == "nothing_published"
    # The registry has no license field: until the repository is read, it is unknown.
    assert excel.license["verdict"] == "unknown"


# ── GitHub ───────────────────────────────────────────────────────────────────

async def test_github_results_are_classified_and_a_repository_only_server_is_not_offered(net):
    found = {c.repo: c for c in await cs.search_github("excel")}
    assert found["haris-musa/excel-mcp-server"].kind == "mcp"
    assert found["haris-musa/excel-mcp-server"].not_here == "not_in_registry"
    assert found["openpyxl-mirror/openpyxl"].kind == "project" and found["openpyxl-mirror/openpyxl"].not_here is None
    assert found["bob/excel-skills"].kind == "skill" and found["bob/excel-skills"].runtime == "skill"
    assert found["openpyxl-mirror/openpyxl"].license == {"spdx": "MIT", "read_from": "github:LICENSE", "verdict": "usable"}
    assert found["acme/excel-mcp-gpl"].license["verdict"] == "reference_only"
    assert found["bob/excel-skills"].license["verdict"] == "unknown"


# ── skill libraries ──────────────────────────────────────────────────────────

async def test_a_library_is_indexed_per_skill_with_each_skills_own_license_at_one_commit(net):
    async with httpx.AsyncClient() as client:
        found = {c.name: c for c in await cs.library_index(client, "anthropics/skills")}
    assert set(found) == {"xlsx", "csv-tidy", "poetry"}
    assert found["csv-tidy"].license == {"spdx": "MIT", "read_from": "skills/csv-tidy/LICENSE.txt", "verdict": "usable"}
    assert found["xlsx"].license["verdict"] == "reference_only"           # a license file that is not permissive
    assert found["poetry"].license["verdict"] == "unknown"                 # no license file at all
    assert found["xlsx"].version == LIB_SHA[:12] and f"/tree/{LIB_SHA}/skills/xlsx" in found["xlsx"].source_url
    # One archive, no API call (60 an hour without a token).
    assert [u for u in net.calls if "anthropics" in u] == ["https://codeload.github.com/anthropics/skills/tar.gz/HEAD"]


# ── together ─────────────────────────────────────────────────────────────────

async def test_search_puts_installable_usable_matches_first_and_merges_the_same_repository(net):
    result = await cs.search("read formulas in an excel workbook", words=["excel"])
    names = [c["name"] for c in result["candidates"]]
    assert names[0] == "excel-mcp-server"
    first = result["candidates"][0]
    assert first["source"] == "registry" and first["runtime"] == "uv"
    assert first["license"]["verdict"] == "usable" and first["stars"] == 4212      # read from its repository
    # The same repository from GitHub is not listed a second time.
    assert sum(1 for c in result["candidates"] if c["repo"] == "haris-musa/excel-mcp-server") == 1
    # Library skills only when they match; the poem one does not.
    assert "poetry" not in names and "csv-tidy" in names
    assert result["notes"] == []
    # A registry entry with no GitHub search hit has its repository read directly.
    dotnet = next(c for c in result["candidates"] if c["name"] == "excel-dotnet")
    assert dotnet["stars"] == 3 and dotnet["license"]["verdict"] == "unknown"
    batch = [u for u in net.calls if "repo%3A" in u]
    assert len(batch) == 1 and "someone%2Fexcel-dotnet" in batch[0]          # one search for all of them
    assert "haris-musa" not in batch[0]                                       # merged from GitHub instead


async def test_one_source_down_never_stops_the_others(net):
    net.fail.add("registry.modelcontextprotocol.io")
    result = await cs.search("excel", words=["excel"])
    assert "registry_unavailable" in result["notes"]
    assert any(c["source"] == "github" for c in result["candidates"])


async def test_kinds_filter_and_no_words_means_no_search(net):
    skills = await cs.search("excel", words=["excel"], kinds={"skill"})
    assert skills["candidates"] and {c["kind"] for c in skills["candidates"]} == {"skill"}
    assert not any("registry" in u for u in net.calls)
    assert await cs.search("帮我核对公式") == {"words": [], "candidates": [], "notes": ["no_keywords"]}


async def test_results_are_cached_for_an_hour(net):
    await cs.search("excel", words=["excel"])
    calls = len(net.calls)
    await cs.search("excel", words=["excel"])
    assert len(net.calls) == calls


# ── words for the page ───────────────────────────────────────────────────────

async def test_a_question_without_latin_words_gets_words_from_the_fast_model(monkeypatch):
    seen = []

    class Reply:
        content = 'Sure: ["excel", "formula"]'

    class Adapter:
        async def chat(self, *, system, user):
            seen.append(user)
            return Reply()

    async def adapter():
        return Adapter()
    monkeypatch.setattr(cs, "_words_adapter", adapter)
    assert await cs.words_for("帮我核对预算表的公式") == ["excel", "formula"]
    assert await cs.words_for("read Excel formulas") == ["excel", "formulas"]       # no call needed
    assert seen == ["帮我核对预算表的公式"]

    async def broken():
        raise RuntimeError("no model")
    monkeypatch.setattr(cs, "_words_adapter", broken)
    assert await cs.words_for("帮我核对预算表的公式") == []


# ── the model's tool ─────────────────────────────────────────────────────────

async def test_find_capability_returns_outside_content_and_remembers_what_it_showed(net):
    from server.registry.executors import EXECUTORS
    from server.services import personal_context as pc
    ctx = pc.TaskMemoryContext(task_id="t1", run_id="r1", conversation_id="conv-find", model_is_local=True)
    with pc.bind(ctx):
        out = await EXECUTORS["find_capability"].execute({"need": "read formulas", "keywords": ["excel"]})
    assert out["ok"] and out["external"] is True and len(out["candidates"]) <= cs.MODEL_RESULTS
    top = out["candidates"][0]
    assert top["name"] == "excel-mcp-server" and top["license_verdict"] == "usable" and top["runtime"] == "uv"
    assert cs.seen("conv-find", top["id"])["package"]["identifier"] == "excel-mcp-server"
    assert cs.seen("another-conversation", top["id"]) is None
    assert (await EXECUTORS["find_capability"].execute({}))["ok"] is False


def test_the_tool_is_offered_with_a_schema_and_counts_as_outside_content():
    from server.orchestrator import tool_loop, untrusted
    schema = tool_loop._NATIVE_PARAM_SCHEMAS["find_capability"]
    assert schema["required"] == ["need", "keywords"]
    assert untrusted.counts_as_external("find_capability", {})


async def test_the_main_assistant_is_offered_find_capability(execution_db):
    from server.orchestrator import arslan
    tools = await arslan._arslan_tools()
    assert any(t["key"] == "find_capability" for t in tools)


def test_no_installer_imports_the_search():
    """The supply-chain line (test_capability_supply_chain): search is a discovery layer."""
    from server.services import mcp_service, skill_import
    for module in (skill_import, mcp_service):
        source = pathlib.Path(inspect.getfile(module)).read_text()
        assert "capability_search" not in source, module.__name__


async def test_the_page_endpoint_searches_with_the_words_of_the_box(net, monkeypatch):
    from fastapi import FastAPI

    from server import auth
    from server.api.capabilities import router
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-cap-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 headers={"Authorization": "Bearer synthetic-cap-token"}) as client:
        body = (await client.get("/api/v1/capability-search", params={"q": "Excel formulas", "kind": "skill"})).json()
    assert body["words"] == ["excel", "formulas"]
    assert body["candidates"] and {c["kind"] for c in body["candidates"]} == {"skill"}


def test_with_the_same_fit_a_usable_license_comes_before_more_stars():
    usable = cs.Candidate(id="a", kind="project", name="excel-lite", summary="", source="github", source_url=None,
                          repo="a/excel-lite", stars=10, license={"spdx": "MIT", "read_from": "x", "verdict": "usable"})
    gpl = cs.Candidate(id="b", kind="project", name="excel-pro", summary="", source="github", source_url=None,
                       repo="b/excel-pro", stars=9000, license={"spdx": "GPL-3.0", "read_from": "x", "verdict": "reference_only"})
    assert [c.id for c in cs.rank([gpl, usable], ["excel"])] == ["a", "b"]


async def test_a_github_mcp_repository_is_looked_up_in_the_registry_by_name(net):
    """The registry's search is slow (≈19 s or a timeout); a lookup by name is ≈0.9 s.
    A GitHub MCP repository published under io.github.<owner>/<repo> becomes installable."""
    result = await cs.search("excel", words=["excel"], kinds={"mcp"})
    gpl = [c for c in result["candidates"] if c["repo"] == "acme/excel-mcp-gpl"]
    assert len(gpl) == 1 and gpl[0]["source"] == "registry" and gpl[0]["runtime"] == "node"
    assert gpl[0]["license"]["verdict"] == "reference_only"        # taken from the GitHub result
    assert any("/v0/servers/io.github.acme%2Fexcel-mcp-gpl/versions/latest" in u for u in net.calls)
    # The ones already found by the registry's search are not looked up again.
    assert not any("haris-musa%2Fexcel-mcp-server/versions" in u for u in net.calls)


async def test_a_rate_limited_github_is_noted_not_hidden(net, monkeypatch):
    async def limited(q):
        raise ValueError("GitHub rate-limited — set GITHUB_TOKEN in Settings to raise the limit")
    monkeypatch.setattr(github_eval, "search_repos", limited)
    result = await cs.search("excel", words=["excel"])
    assert result["notes"] == ["github_unavailable"]

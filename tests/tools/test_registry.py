"""Tests for ToolRegistry."""
import pytest

from arslan.tools.base import ArslanTool, ToolResult
from arslan.tools.registry import ToolRegistry


# ── Concrete mock tools ───────────────────────────────────────────────────────

class MockTool(ArslanTool):
    name = "mock-search"
    description = "Search the mock database"
    tags = ["search", "web"]
    input_schema = {}
    output_schema = {}

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=True)

    async def health_check(self) -> bool:
        return True


class MockCrawler(ArslanTool):
    name = "mock-crawler"
    description = "Crawl xiaohongshu content"
    tags = ["crawler", "web", "xiaohongshu"]
    input_schema = {}
    output_schema = {}

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=True)

    async def health_check(self) -> bool:
        return True


# ── register / get ────────────────────────────────────────────────────────────

def test_register_and_get_tool():
    registry = ToolRegistry()
    tool = MockTool()
    registry.register(tool)
    assert registry.get("mock-search") is tool


def test_get_nonexistent_returns_none():
    registry = ToolRegistry()
    assert registry.get("nonexistent") is None


def test_register_multiple_tools():
    registry = ToolRegistry()
    t1 = MockTool()
    t2 = MockCrawler()
    registry.register(t1)
    registry.register(t2)
    assert registry.get("mock-search") is t1
    assert registry.get("mock-crawler") is t2


# ── search_by_tags ────────────────────────────────────────────────────────────

def test_search_by_broad_tag_returns_both():
    registry = ToolRegistry()
    registry.register(MockTool())
    registry.register(MockCrawler())
    results = registry.search_by_tags(["web"])
    names = {t.name for t in results}
    assert "mock-search" in names
    assert "mock-crawler" in names


def test_search_by_specific_tag_returns_only_crawler():
    registry = ToolRegistry()
    registry.register(MockTool())
    registry.register(MockCrawler())
    results = registry.search_by_tags(["xiaohongshu"])
    names = {t.name for t in results}
    assert names == {"mock-crawler"}


def test_search_by_tags_no_match_returns_empty():
    registry = ToolRegistry()
    registry.register(MockTool())
    results = registry.search_by_tags(["nonexistent-tag"])
    assert results == []


def test_search_by_tags_any_match_is_sufficient():
    """A tool matching ANY of the provided tags should be included."""
    registry = ToolRegistry()
    registry.register(MockTool())
    registry.register(MockCrawler())
    results = registry.search_by_tags(["search", "xiaohongshu"])
    names = {t.name for t in results}
    assert "mock-search" in names
    assert "mock-crawler" in names


# ── search (name/description substring) ──────────────────────────────────────

def test_search_by_name_substring():
    registry = ToolRegistry()
    registry.register(MockTool())
    registry.register(MockCrawler())
    results = registry.search("crawler")
    names = {t.name for t in results}
    assert "mock-crawler" in names
    assert "mock-search" not in names


def test_search_by_description_substring():
    registry = ToolRegistry()
    registry.register(MockTool())
    registry.register(MockCrawler())
    results = registry.search("xiaohongshu")
    names = {t.name for t in results}
    assert "mock-crawler" in names
    assert "mock-search" not in names


def test_search_case_insensitive():
    registry = ToolRegistry()
    registry.register(MockTool())
    results = registry.search("MOCK")
    assert len(results) >= 1


def test_search_no_match_returns_empty():
    registry = ToolRegistry()
    registry.register(MockTool())
    results = registry.search("zzznomatch")
    assert results == []


# ── list_all ──────────────────────────────────────────────────────────────────

def test_list_all_returns_all_tools():
    registry = ToolRegistry()
    registry.register(MockTool())
    registry.register(MockCrawler())
    all_tools = registry.list_all()
    names = {t.name for t in all_tools}
    assert names == {"mock-search", "mock-crawler"}


def test_list_all_empty_registry():
    registry = ToolRegistry()
    assert registry.list_all() == []


# ── register_builtins ─────────────────────────────────────────────────────────

def test_register_builtins_adds_llm_caller():
    registry = ToolRegistry()
    registry.register_builtins()
    assert registry.get("llm-caller") is not None


def test_register_builtins_adds_web_search():
    registry = ToolRegistry()
    registry.register_builtins()
    assert registry.get("web-search") is not None


def test_register_builtins_tools_are_arslan_tools():
    registry = ToolRegistry()
    registry.register_builtins()
    assert isinstance(registry.get("llm-caller"), ArslanTool)
    assert isinstance(registry.get("web-search"), ArslanTool)

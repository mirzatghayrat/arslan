"""Shared pytest fixtures for the Arslan test suite."""
import pytest

from arslan.models import (
    DomainInfo,
    PersonaSpec,
    RuntimeSpec,
    SpawnRequirements,
    ToolSpec,
)


@pytest.fixture
def sample_domain() -> DomainInfo:
    return DomainInfo(category="content-creator", subcategory="xiaohongshu")


@pytest.fixture
def sample_persona() -> PersonaSpec:
    return PersonaSpec(
        role="资深美妆博主",
        tone="数据实测型",
        constraints=["不推荐未经验证的产品"],
    )


@pytest.fixture
def sample_tool() -> ToolSpec:
    return ToolSpec(
        name="web_search",
        description="Search the web for information",
        tags=["search", "web"],
        input_schema={"query": {"type": "string"}},
        output_schema={"results": {"type": "array"}},
    )


@pytest.fixture
def sample_requirements(sample_domain, sample_persona) -> SpawnRequirements:
    return SpawnRequirements(
        spawn_name="美妆助手",
        domain=sample_domain,
        capabilities=["content-generation", "info-gathering"],
        persona=sample_persona,
        runtime=RuntimeSpec(platform="web", trigger="user"),
        research_results={"trends": ["skincare", "makeup"]},
    )

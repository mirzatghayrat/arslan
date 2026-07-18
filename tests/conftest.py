"""Shared pytest fixtures for the Arslan test suite."""
import os

# Keep the dev secret auto-generation (server.secret_bootstrap) DISABLED suite-wide:
# set-but-empty ARSLAN_SECRET_KEY_FILE means "never read/write any secret file".
# Without this, any test that reloads server.config with ARSLAN_SECRET_KEY unset would
# mint a real key file in the developer's ~/.arslan. Must execute before any server.*
# import (the frozen settings singleton builds at first import); this root conftest
# loads before every test module and sub-conftest. Tests that exercise the feature
# opt back in by pointing ARSLAN_SECRET_KEY_FILE at a tmp path.
os.environ["ARSLAN_SECRET_KEY_FILE"] = ""

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

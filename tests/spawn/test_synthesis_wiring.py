"""Tests for wiring CLI synthesis into generation (P1 seam closure)."""
from arslan.models import (
    DomainInfo,
    LLMResponse,
    PersonaSpec,
    SpawnBlueprint,
    SpawnRequirements,
    ToolSpec,
)
from arslan.spawn.manager import SpawnManager
from arslan.spawn.skillpack import validate_skillpack

GOOD_CLI = """\
import sys
if len(sys.argv) > 1 and sys.argv[1] == "doc":
    print("usage")
    sys.exit(0)
sys.exit(1)
"""


class _FakeAdapter:
    def __init__(self, script):
        self.script = script
        self.calls = 0

    async def chat(self, system, user, **kwargs):
        self.calls += 1
        return LLMResponse(content=self.script, usage={})


def _blueprint(tool: ToolSpec) -> SpawnBlueprint:
    return SpawnBlueprint(
        requirements=SpawnRequirements(
            spawn_name="pricer",
            domain=DomainInfo(category="commerce", subcategory="sneakers"),
            capabilities=["price-watch"],
            persona=PersonaSpec(role="比价助手"),
        ),
        tools=[tool],
        system_prompt="你是比价助手。",
        workflow_steps=[],
    )


def test_extra_scripts_written_into_pack(tmp_path):
    mgr = SpawnManager(spawns_dir=tmp_path)
    bp = _blueprint(ToolSpec(name="x", description="d", input_schema={}, output_schema={}))
    pack = mgr.generate_skillpack(bp, extra_scripts={"poizon_cli.py": GOOD_CLI})
    assert (pack / "scripts" / "poizon_cli.py").exists()


async def test_synthesis_wiring_produces_valid_pack(tmp_path):
    mgr = SpawnManager(spawns_dir=tmp_path)
    tool = ToolSpec(
        name="poizon-price",
        description="抓取得物球鞋价格",
        input_schema={},
        output_schema={},
        config={"synthesize": True, "need": "抓取得物 App 球鞋价格"},
    )
    adapter = _FakeAdapter(GOOD_CLI)
    pack = await mgr.generate_skillpack_with_synthesis(_blueprint(tool), adapter)
    assert adapter.calls == 1
    assert (pack / "scripts" / "poizon_price_cli.py").exists()
    for r in validate_skillpack(pack):
        assert r.passed is True, f"{r.name}: {r.message}"


async def test_no_synthesis_when_no_tool_marked(tmp_path):
    mgr = SpawnManager(spawns_dir=tmp_path)
    tool = ToolSpec(name="plain", description="d", input_schema={}, output_schema={})
    adapter = _FakeAdapter(GOOD_CLI)
    pack = await mgr.generate_skillpack_with_synthesis(_blueprint(tool), adapter)
    assert adapter.calls == 0
    assert (pack / "SKILL.md").exists()

"""PC1-c: skill_forge's skill-on injection reuses dispatcher._skill_technique_block,
so a LONG candidate body becomes the SAME bounded technique block a really-equipped
skill would get (summary + TOC + read_skill hint, <= _SKILL_BLOCK_LIMIT) — NOT a raw
body[:1500] cut mid-word. Both injection points now share one truncation logic."""
from server.orchestrator.dispatcher import _SKILL_BLOCK_LIMIT
from server.services import skill_forge


def test_long_body_becomes_bounded_technique_block():
    intro = "intro paragraph before any heading. " * 20
    section_body = "SENTINEL_DEEP_DETAIL_LINE " * 100  # >2500 chars, lives inside a ## section
    body = intro + "\n## First\n" + section_body + "\n## Second\ny\n### Sub\nz"
    assert len(body) > _SKILL_BLOCK_LIMIT  # long enough to force the summary+TOC path
    out = skill_forge._inject_skill_body("BASE PROMPT", "writing-plans", body, key="writing-plans")
    assert "BASE PROMPT" in out
    assert "Your techniques:" in out
    # bounded, read_skill hinted — the shared helper, not a raw body[:1500] mid-word cut
    tech = out.split("Your techniques:\n", 1)[1]
    assert len(tech) <= _SKILL_BLOCK_LIMIT
    assert "read_skill" in tech and "writing-plans" in tech
    # the old body[:1500] cut would spill deep section text; the summary-only block omits it
    assert "SENTINEL_DEEP_DETAIL_LINE" not in tech
    assert "## First" in tech                 # TOC of ## headings preserved


def test_short_body_inlined_whole_no_hint():
    out = skill_forge._inject_skill_body("BASE", "tiny", "## X\ndo the thing", key="tiny")
    assert "Your techniques:" in out
    assert "do the thing" in out
    assert "read_skill" not in out


def test_empty_body_leaves_prompt_untouched():
    assert skill_forge._inject_skill_body("BASE", "s", "   ", key="s") == "BASE"


def test_scripts_flag_threads_run_hint(tmp_path, monkeypatch):
    """When the candidate key has bundled scripts, the injected block carries the run hint."""
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    script_dir = tmp_path / "skill_scripts" / "handoff"
    script_dir.mkdir(parents=True)
    (script_dir / "run.py").write_text("print('hi')", encoding="utf-8")
    out = skill_forge._inject_skill_body(
        "BASE", "Handoff", "## X\nrun the script", key="handoff", has_scripts=True)
    assert "skill_script" in out and "handoff/" in out

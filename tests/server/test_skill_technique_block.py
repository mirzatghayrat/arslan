from server.orchestrator.dispatcher import _skill_technique_block, _SKILL_BLOCK_LIMIT


def test_short_skill_inlined_whole():
    body = "## Step\ndo the thing"
    blk = _skill_technique_block("brainstorming", body, has_scripts=False, key="brainstorming")
    assert body in blk
    assert "read_skill" not in blk


def test_long_skill_gets_summary_toc_and_read_hint():
    body = "intro paragraph. " * 200 + "\n## First\nx\n## Second\ny\n### Sub\nz"
    blk = _skill_technique_block("writing-plans", body, has_scripts=False, key="writing-plans",
                                 read_skill_available=True)
    assert len(blk) <= _SKILL_BLOCK_LIMIT
    assert "## First" in blk and "## Second" in blk
    assert "read_skill" in blk and "writing-plans" in blk


def test_toc_overflow_lists_only_h2_and_notes_more():
    body = "intro. " * 60 + "\n" + "\n".join(f"## Sec{i}\n{'body '*40}\n### Deep{i}\ndetail" for i in range(60))
    blk = _skill_technique_block("designed-html-report", body, has_scripts=False,
                                 key="designed-html-report", read_skill_available=True)
    assert len(blk) <= _SKILL_BLOCK_LIMIT
    assert "### Deep0" not in blk
    assert "read_skill" in blk


def test_scripts_get_run_hint_line():
    blk = _skill_technique_block("handoff", "## X\nrun the script", has_scripts=True,
                                 key="handoff", run_python_available=True)
    assert "skill_script" in blk and "handoff/" in blk


# ── PC compat fix: hints gated on tool availability ──────────────────────────────────

_LONG_BODY = "intro paragraph. " * 200 + "\n## First\nx\n## Second\ny\n### Sub\nz"


def test_long_skill_read_skill_available_emits_hint():
    blk = _skill_technique_block("writing-plans", _LONG_BODY, has_scripts=False,
                                 key="writing-plans", read_skill_available=True)
    assert "read_skill(" in blk                       # actionable pointer present
    assert len(blk) <= _SKILL_BLOCK_LIMIT


def test_long_skill_read_skill_unavailable_uses_honest_fallback():
    """SAME long skill, no read_skill wired → honest摘要 note, never a read_skill pointer."""
    blk = _skill_technique_block("writing-plans", _LONG_BODY, has_scripts=False,
                                 key="writing-plans", read_skill_available=False)
    assert "read_skill(" not in blk                   # never point at a tool it can't call
    assert "Code Sandbox" in blk                      # honest: full text needs the toolset
    assert len(blk) <= _SKILL_BLOCK_LIMIT
    # deep/overflow TOC markers must not mention read_skill either
    assert "read_skill" not in blk


def test_scripts_run_python_unavailable_omits_run_hint():
    blk = _skill_technique_block("handoff", "## X\nrun the script", has_scripts=True,
                                 key="handoff", run_python_available=False)
    assert "run_python" not in blk                    # no dead-end run hint
    assert "handoff/<file>.py" not in blk
    assert "Code Sandbox" in blk                       # honest parenthetical instead

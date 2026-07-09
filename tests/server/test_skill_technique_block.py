from server.orchestrator.dispatcher import _skill_technique_block, _SKILL_BLOCK_LIMIT


def test_short_skill_inlined_whole():
    body = "## Step\ndo the thing"
    blk = _skill_technique_block("brainstorming", body, has_scripts=False, key="brainstorming")
    assert body in blk
    assert "read_skill" not in blk


def test_long_skill_gets_summary_toc_and_read_hint():
    body = "intro paragraph. " * 200 + "\n## First\nx\n## Second\ny\n### Sub\nz"
    blk = _skill_technique_block("writing-plans", body, has_scripts=False, key="writing-plans")
    assert len(blk) <= _SKILL_BLOCK_LIMIT
    assert "## First" in blk and "## Second" in blk
    assert "read_skill" in blk and "writing-plans" in blk


def test_toc_overflow_lists_only_h2_and_notes_more():
    body = "intro. " * 60 + "\n" + "\n".join(f"## Sec{i}\n{'body '*40}\n### Deep{i}\ndetail" for i in range(60))
    blk = _skill_technique_block("designed-html-report", body, has_scripts=False, key="designed-html-report")
    assert len(blk) <= _SKILL_BLOCK_LIMIT
    assert "### Deep0" not in blk
    assert "read_skill" in blk


def test_scripts_get_run_hint_line():
    blk = _skill_technique_block("handoff", "## X\nrun the script", has_scripts=True, key="handoff")
    assert "skill_script" in blk and "handoff/" in blk

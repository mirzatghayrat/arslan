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


# ---------------------------------------------------------------------------
# The truncation trap (gap assessment §0.2, user-approved queue-jump D2).
#
# House-style SKILL.md starts at "## Trigger" — no prose before the first
# heading — so the "intro summary" the truncated form relied on was ALWAYS
# empty, and every over-cap skill collapsed to a bare table of contents.
# deck-authoring (2742 chars) and designed-html-report (11756) shipped that
# way: Deck Master's method content never reached the model.
# ---------------------------------------------------------------------------

def _house_style_body(n_sections: int, section_len: int) -> str:
    """A body in the repo's real shape: FIRST LINE IS A HEADING. That property
    is the whole bug, so the fixture must have it.

    (First draft divided by 20 assuming ~20 chars per repeat; the unit is 12
    chars, so every size assertion was off by ~40% and the fixture-drift guards
    fired — which is what they are for.)"""
    unit = "规则{}:先做甲再做乙。"
    parts = []
    for i in range(n_sections):
        reps = max(1, section_len // len(unit.format(i)))
        parts.append(f"## 第{i}节\n" + (unit.format(i) * reps))
    return "\n".join(parts)


def test_the_fixture_really_has_no_pre_heading_prose():
    """(0) pre-assertion: if the fixture opened with prose, the old code would
    produce a non-empty summary and the test below would prove nothing."""
    body = _house_style_body(6, 400)
    assert body.startswith("## "), "fixture must start at a heading, like real seeds"


def test_an_overcap_house_style_skill_still_carries_method_content():
    """The trap itself. An over-cap skill must inject actual body content —
    rules the model can follow — not just a bare TOC.

    Discriminating: asserting "some rule text appears" fails on the old code,
    whose summary was intro[:budget] with intro == ''."""
    body = _house_style_body(6, 700)          # well over any sane cap
    blk = _skill_technique_block("Deck 技法", body, has_scripts=False, key="deck-authoring")
    assert "规则0" in blk, (
        "the truncated block carries no body content — the empty-intro collapse "
        "is back; a spawn gets a bare TOC instead of its method")
    assert len(blk) <= _SKILL_BLOCK_LIMIT


def test_deck_authoring_sized_bodies_now_inline_whole():
    """The constant half of the fix: the two seeds just over the old 2000 cap
    (competitive-analysis 2199, deck-authoring 2742) must inline entirely —
    they are the method content of shipping spawns."""
    body = _house_style_body(5, 540)
    assert 2400 < len(body) < 2900, f"fixture drifted: {len(body)}"
    blk = _skill_technique_block("Deck 技法", body, has_scripts=False, key="deck-authoring")
    assert "第4节" in blk and blk.endswith(body[-20:]), "a deck-authoring-sized body was truncated"


def test_the_cap_still_exists_for_genuinely_huge_skills():
    """The other direction, so the fix cannot be 'delete the cap': an
    11756-char skill (designed-html-report) must still be bounded."""
    body = _house_style_body(20, 600)
    assert len(body) > 10000
    blk = _skill_technique_block("HTML 报告", body, has_scripts=False, key="designed-html-report")
    assert len(blk) <= _SKILL_BLOCK_LIMIT
    assert "规则0" in blk, "even the bounded form must carry head content, not only a TOC"

from server.services import skill_doc as sd


def test_parse_headerless_is_one_section():
    secs = sd.parse_sections("You are a helpful assistant.")
    assert secs == [{"header": "Instructions", "body": "You are a helpful assistant."}]


def test_parse_named_sections():
    doc = "## Role\nYou are X.\n\n## Style\nBe terse."
    assert sd.parse_sections(doc) == [
        {"header": "Role", "body": "You are X."},
        {"header": "Style", "body": "Be terse."},
    ]


def test_apply_add_appends_section():
    out = sd.apply_edits("## Role\nYou are X.",
                         [{"op": "add", "section": "Style", "content": "Be terse."}])
    assert "## Style" in out and "Be terse." in out and "## Role" in out


def test_apply_add_existing_section_is_noop():
    doc = "## Role\nYou are X."
    assert sd.apply_edits(doc, [{"op": "add", "section": "Role", "content": "ignored"}]) == doc


def test_apply_replace_swaps_body():
    out = sd.apply_edits("## Role\nYou are X.",
                         [{"op": "replace", "section": "Role", "content": "You are Y."}])
    assert "You are Y." in out and "You are X." not in out


def test_apply_replace_unknown_section_is_noop():
    doc = "## Role\nYou are X."
    assert sd.apply_edits(doc, [{"op": "replace", "section": "Nope", "content": "z"}]) == doc


def test_apply_delete_removes_section():
    doc = "## Role\nYou are X.\n\n## Style\nBe terse."
    out = sd.apply_edits(doc, [{"op": "delete", "section": "Style"}])
    assert "## Style" not in out and "## Role" in out


def test_apply_delete_last_section_is_noop():
    doc = "## Role\nYou are X."
    assert sd.apply_edits(doc, [{"op": "delete", "section": "Role"}]) == doc


def test_apply_headerless_doc_then_add():
    out = sd.apply_edits("You are X.",
                         [{"op": "add", "section": "Style", "content": "Be terse."}])
    assert "## Instructions" in out and "You are X." in out and "## Style" in out

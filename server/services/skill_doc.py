"""The evolvable instruction as a sectioned markdown doc + bounded section edits.

The doc IS the spawn's system_prompt. Sections are `## <header>` blocks; a doc with
no headers is one implicit `## Instructions` section. Edits are section-scoped
(add/delete/replace) — never a free whole-doc rewrite.
"""
from __future__ import annotations

_DEFAULT_HEADER = "Instructions"


def parse_sections(doc: str) -> list[dict]:
    text = (doc or "").strip()
    if not text:
        return [{"header": _DEFAULT_HEADER, "body": ""}]
    if not text.lstrip().startswith("## "):
        return [{"header": _DEFAULT_HEADER, "body": text}]
    sections: list[dict] = []
    header = None
    body_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if header is not None:
                sections.append({"header": header, "body": "\n".join(body_lines).strip()})
            header = line[3:].strip()
            body_lines = []
        else:
            body_lines.append(line)
    if header is not None:
        sections.append({"header": header, "body": "\n".join(body_lines).strip()})
    return sections


def _render(sections: list[dict]) -> str:
    return "\n\n".join(f"## {s['header']}\n{s['body']}".rstrip() for s in sections).strip()


def apply_edits(doc: str, edits: list[dict]) -> str:
    sections = parse_sections(doc)
    for edit in edits or []:
        op = edit.get("op")
        sec = edit.get("section")
        content = edit.get("content", "")
        names = [s["header"] for s in sections]
        if op == "add":
            if sec and sec not in names:
                sections.append({"header": sec, "body": content})
        elif op == "replace":
            for s in sections:
                if s["header"] == sec:
                    s["body"] = content
        elif op == "delete":
            if sec in names and len(sections) > 1:
                sections = [s for s in sections if s["header"] != sec]
    return _render(sections)

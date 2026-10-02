"""The run's plan (0.1.50 P2 S2): the model's own checklist, kept by the host.

`update_plan` replaces it wholesale. The status bar (S1) shows it at the end of
every request, so a long task keeps its sub-tasks and its count ("6/10") in view
instead of in a message twenty steps back. Bookkeeping only: no side effects,
not an action, not counted against the tool budget. One run_native call owns
one Plan, so a background job keeps its own and a new turn starts empty.
"""
from __future__ import annotations

STATUSES = ("pending", "in_progress", "done")
MAX_ITEMS = 12
MAX_TEXT = 160
_MARK = {"pending": "[ ]", "in_progress": "[>]", "done": "[x]"}

PARAMS = {
    "type": "object",
    "properties": {"items": {
        "type": "array", "minItems": 1, "maxItems": MAX_ITEMS,
        "items": {"type": "object",
                  "properties": {"text": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT},
                                 "status": {"type": "string", "enum": list(STATUSES)}},
                  "required": ["text", "status"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False,
}


def _refuse(why: str) -> dict:
    return {"ok": False, "external": False, "code": "invalid_arguments",
            "error": f"Plan not changed: {why}. Send the whole list as "
                     "items: [{text, status: pending|in_progress|done}]."}


class Plan:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def update(self, args: dict) -> dict:
        items = args.get("items") if isinstance(args, dict) else None
        if not isinstance(items, list) or not items:
            return _refuse("items must be a non-empty list")
        if len(items) > MAX_ITEMS:
            return _refuse(f"at most {MAX_ITEMS} items")
        clean = []
        for item in items:
            text = " ".join(str(item.get("text") or "").split()) if isinstance(item, dict) else ""
            status = item.get("status", "pending") if isinstance(item, dict) else None
            if not text or status not in STATUSES:
                return _refuse("every item needs text and a status")
            clean.append({"text": text[:MAX_TEXT], "status": status})
        self.items = clean
        done = sum(1 for i in clean if i["status"] == "done")
        return {"ok": True, "external": False, "summary": f"{done}/{len(clean)} done"}

    def render(self) -> str:
        """One line for the status bar; empty when no plan was made."""
        return "  ".join(f"{_MARK[i['status']]} {i['text']}" for i in self.items)

"""CLS's measurement runner (v0.1.64, docs/plans/0164/README.md §3.2, the CLS row): counts only.

    uv run python -m scripts.dev.cls_measure --cases <a JSONL file outside the repo> [--model <model id>] [--json]

One JSON record per line: {id, family, user_words, intent, action: {tool, text, kind, write_targets[], sandboxed},
context: {job_kind, outside_seen, checkpoint_exists}, expected: "allow" | "ask", why}. Each record goes through the
real pre-gate, then the model (`classifier.consult(measuring=True)`, the only way past MEASURED). The records carry
no `rules` or `never_auto`: both are derived from the real policy (`terminal_policy.ask_rules` and
`hard_rules.never_auto`, as the command gate and CLS read them); a record where that fails takes no rules and
`never_auto=False`, and is counted as a fallback.

It prints counts only: never a record's id, text, user words, intent or why, nor a model's reason. It writes nothing
to the repo or the data folder: relative write targets are placed in a throwaway work folder in the system temp
folder, which is removed at the end.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import re
import sys
import tempfile
from pathlib import Path

from server.services import classifier as cls
from server.services import hard_rules, permissions, terminal_policy

#: The case file's tool names -> Arslan's.
TOOLS = {"exec_command": "run_command", "apply_patch": "edit_file"}
#: A patch that starts with this header (after its opening line) adds a file: `write_file`.
ADD_FILE = "*** Add File:"
#: The card a tool raises when the record names none.
DEFAULT_KIND = {"run_command": "command", "edit_file": "workspace_write", "write_file": "workspace_write"}
_LABEL = re.compile(r"[^A-Za-z0-9_.-]")


def tool_of(tool, text) -> str:
    if tool == "apply_patch":
        body = text.lstrip().removeprefix("*** Begin Patch").lstrip() if isinstance(text, str) else ""
        return "write_file" if body.startswith(ADD_FILE) else "edit_file"
    return TOOLS.get(tool, str(tool))


def derive(tool: str, text, kind: str, targets: tuple[Path, ...], workspace: Path) -> tuple[frozenset[str], bool]:
    """`rules` and `never_auto` from the real policy. A command: its layer ② rules read as if outside the sandbox
    (`terminal_policy.ask_rules(outside=True)`, the cautious reading) and `hard_rules.never_auto` on the request the
    gate would build (`approvals._command_request`: a ruled card is once-only). A file write: no rules, and
    `never_auto` on each target's write request. Raises when the record can't be read this way."""
    if not isinstance(text, str):
        raise TypeError("action text is not a string")
    if tool == "run_command":
        rules = frozenset(terminal_policy.ask_rules(text, outside=True))
        target = "rules:" + "|".join(sorted(rules)) if rules else "text:" + text
        request = permissions.Request(kind=kind, target=target, title="", detail=text, once_only=bool(rules))
        return rules, hard_rules.never_auto(request)
    details = [str(t) for t in targets] or [""]
    return frozenset(), any(hard_rules.never_auto(permissions.Request(kind=kind, target=str(workspace), title="",
                                                                      detail=d)) for d in details)


class Counts:
    def __init__(self) -> None:
        self.families: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        self.pregate: collections.Counter = collections.Counter()
        self.total = self.reached = self.false_allow = self.fallbacks = 0
        self.errors = self.unparsable = self.invalid = 0

    def as_dict(self, model: str) -> dict:
        return {
            "model": model,
            "cases": self.total,
            "reached_model": self.reached,
            "invalid_records": self.invalid,
            "false_allow": {"all": [self.false_allow, self.total],
                            "reached_model": [self.false_allow, self.reached]},
            "families": {name: {"n": c["n"], "false_allow": c["false_allow"], "false_ask": c["false_ask"]}
                         for name, c in sorted(self.families.items())},
            "pregate_stops": dict(sorted(self.pregate.items())),
            "fallbacks": self.fallbacks,
            "errors": self.errors,
            "unparsable": self.unparsable,
        }


def render(data: dict) -> str:
    lines = [f"model: {data['model']}",
             f"cases: {data['cases']}  reached the model: {data['reached_model']}  "
             f"invalid records: {data['invalid_records']}",
             "false-allow: all {}/{}  reached-model {}/{}".format(*data["false_allow"]["all"],
                                                                  *data["false_allow"]["reached_model"])]
    lines += [f"family {name}: n={c['n']} false-allow={c['false_allow']} false-ask={c['false_ask']}"
              for name, c in data["families"].items()]
    lines.append("pre-gate stops: " + (" ".join(f"{k}={v}" for k, v in data["pregate_stops"].items()) or "none"))
    lines.append(f"fallbacks (rules/never_auto not derived): {data['fallbacks']}")
    lines.append(f"errors: {data['errors']}  unparsable: {data['unparsable']}")
    return "\n".join(lines)


def _label(value) -> str:
    """A family label as printed: a short name, never free text."""
    return _LABEL.sub("_", str(value))[:32] or "_"


def _case(record: dict, workspace: Path) -> tuple[cls.Action, cls.Context, str]:
    """The record as CLS's Action and Context, and whether its policy derivation fell back ("fallback" or "")."""
    act, ctx = record["action"], record.get("context") or {}
    tool = tool_of(act.get("tool"), act.get("text"))
    kind = act.get("kind") or DEFAULT_KIND.get(tool)
    targets = tuple(Path(t) if Path(t).is_absolute() else workspace / t for t in act.get("write_targets") or ())
    fell_back = ""
    try:
        rules, never_auto = derive(tool, act.get("text"), kind, targets, workspace)
    except Exception:
        rules, never_auto, fell_back = frozenset(), False, "fallback"
    action = cls.Action(tool=tool, text=act.get("text"), kind=kind, write_targets=targets, rules=rules,
                        never_auto=never_auto, sandboxed=act.get("sandboxed") is True)
    context = cls.Context(user_words=record.get("user_words"), intent=record.get("intent") or "",
                          job_kind=ctx.get("job_kind", "turn"), outside_seen=ctx.get("outside_seen", True),
                          checkpoint_exists=ctx.get("checkpoint_exists", False))
    return action, context, fell_back


async def run(lines, *, model: tuple[str, str], complete: cls.Complete) -> Counts:
    counts = Counts()
    with tempfile.TemporaryDirectory(prefix="cls-measure-") as root:
        workspace, tmpdir = Path(root) / "work", Path(root) / "tmp"
        workspace.mkdir()
        tmpdir.mkdir()
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                expected = record["expected"]
                if expected not in ("allow", "ask"):
                    raise ValueError("bad expected")
                family = _label(record.get("family"))
                action, ctx, fell_back = _case(record, workspace)
            except Exception:
                counts.invalid += 1
                continue
            counts.total += 1
            counts.fallbacks += bool(fell_back)
            fam = counts.families[family]
            fam["n"] += 1
            gate = cls.pregate(action, ctx, workspace=workspace, tmpdir=tmpdir)
            if gate is not None:
                counts.pregate[gate.reason] += 1
                decision = "ask"
            else:
                counts.reached += 1
                status, verdict = await cls.consult(action, ctx, model=model, complete=complete, measuring=True)
                counts.errors += status in ("error", "off")
                counts.unparsable += status == "unparsable"
                decision = verdict.decision
            if decision == "allow" and expected == "ask":
                counts.false_allow += 1
                fam["false_allow"] += 1
            elif decision == "ask" and expected == "allow":
                fam["false_ask"] += 1
    return counts


async def amain(argv: list[str] | None = None, *, complete: cls.Complete | None = None) -> int:
    parser = argparse.ArgumentParser(description="CLS measurement: counts only.")
    parser.add_argument("--cases", required=True, type=Path, help="a JSONL cases file, outside the repo")
    parser.add_argument("--model", default=None, help="a model id on the configured provider (default: its own)")
    parser.add_argument("--json", action="store_true", help="print the counts as JSON")
    args = parser.parse_args(argv)
    try:
        lines = args.cases.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        print("cannot read the cases file", file=sys.stderr)
        return 2
    if complete is None:
        adapter = await cls.configured_model(args.model)
        model, complete = (adapter.report_provider, adapter.model), cls.provider_complete(adapter)
    else:
        model = ("stand-in", args.model or "stand-in")
    data = (await run(lines, model=model, complete=complete)).as_dict("/".join(model))
    print(json.dumps(data, ensure_ascii=True, indent=2) if args.json else render(data))
    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    sys.exit(main())

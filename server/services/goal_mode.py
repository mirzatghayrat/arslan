"""L7 goal mode's types (docs/plans/0164/L7-goal-mode.md, L7-1), the goal's checks as a task's acceptance, the
progress rule (L7-2), and the protected set of its `check:` lines (L7-5).

A goal is a background task whose acceptance checks are the goal, run by today's `_run_native`. Its spec (`GoalSpec`)
rides on `TurnRequest.goal`; what its rounds have recorded (`GoalProgress`) rides on `Progress.goal`, written in the
same checkpoint as each verdict (`turn_answer.finish`). Both are frozen: state is recorded when it happens and never
worked out again from the transcript. A new value replaces the old one whole (`model_copy(update=...)`).
"""
from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import Field, model_validator

from arslan.companion.contracts import Contract, Identifier, NonnegativeInt
from arslan.execution_budget import DEFAULT_TIER, MAX_USD_CAP

OBJECTIVE_MAX = 4000
CRITERIA_MAX = 5                 # as background_jobs.MAX_CRITERIA; the user's `check:` lines come on top
COMMAND_CHECKS_MAX = 5
BLOCKED_AFTER = 3                # rounds in a row without progress (Codex's audit)
PROTECTED_FILES_MAX = 2000
PROTECTED_BYTES_MAX = 50 * 1024 * 1024

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
RelPath = Annotated[str, Field(min_length=1, max_length=1024)]

GoalStatus = Literal["not_started", "active", "paused", "blocked", "budget_limited", "interrupted", "review",
                     "complete", "cleared"]
# Each status on the existing task row: (phase, pause reason). No new phase, table or migration.
STATUS_PHASE: dict[str, tuple[str, str | None]] = {
    "not_started": ("waiting_user", "goal_not_started"),
    "active": ("running", None),
    "paused": ("waiting_user", "goal_paused"),
    "blocked": ("waiting_user", "goal_blocked"),
    "budget_limited": ("waiting_user", "task_budget_exhausted"),
    "interrupted": ("waiting_user", "process_interrupted"),
    "review": ("waiting_user", "acceptance_review_required"),   # the user's own checks, or a protected file changed
    "complete": ("succeeded", None),
    "cleared": ("cancelled", None),
}


class GoalCheck(Contract):
    """One check of a goal. Met only through its own condition, never by the reply or a receipt naming its path.
    `by_user`: the user wrote it or confirmed it on the form (a judgement check's path counts only then).
    `user_confirmed`: "I'll confirm this myself": never judged by the model, never met by Arslan."""
    id: Identifier
    description: Annotated[str, Field(min_length=1, max_length=300)]
    kind: Literal["file_saved", "file_contains", "sources_read", "judgement", "check"]
    path: Annotated[str, Field(min_length=1, max_length=240)] | None = None
    phrases: tuple[Annotated[str, Field(min_length=1, max_length=200)], ...] = Field(default=(), max_length=32)
    minimum: Annotated[int, Field(ge=1, le=20, strict=True)] | None = None
    argv: tuple[Annotated[str, Field(max_length=2000)], ...] = Field(default=(), max_length=64)
    outputs: tuple[Annotated[str, Field(min_length=1, max_length=240)], ...] = Field(default=(), max_length=16)
    by_user: bool = False
    user_confirmed: bool = False

    @model_validator(mode="after")
    def condition_fits_kind(self):
        if self.kind in {"file_saved", "file_contains"} and self.path is None:
            raise ValueError(f"{self.kind} names a file")
        if (self.kind == "file_contains") != bool(self.phrases):
            raise ValueError("phrases belong to file_contains, which needs at least one")
        if (self.kind == "check") != bool(self.argv):
            raise ValueError("argv belongs to a check command, which needs one")
        if self.kind == "check" and not self.by_user:
            raise ValueError("only the user writes check: lines; drafting never does")
        if self.outputs and self.kind != "check":
            raise ValueError("declared outputs belong to the user's check: line")
        if any(p.endswith("/") or not p.rsplit("/", 1)[-1].strip("*") for p in self.outputs):
            raise ValueError("a declared output is a name or a glob, never a whole folder")
        if self.minimum is not None and self.kind not in {"file_saved", "sources_read"}:
            raise ValueError(f"minimum is not supported by {self.kind}")
        return self


class ProtectedFile(Contract):
    """A protected file's digest at Start (or of its test section: `[tool.pytest.*]`, a `package.json` key)."""
    path: RelPath
    sha256: Sha256 | None = None     # None: the check's argv names it but it didn't exist at Start (a warning)
    section: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    size: NonnegativeInt = 0


class ProtectedSet(Contract):
    """Fixed at Start, re-recorded only by a user edit of the goal. `patterns`: where a new file stops the goal."""
    files: tuple[ProtectedFile, ...] = Field(default=(), max_length=PROTECTED_FILES_MAX)
    patterns: tuple[RelPath, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def bounded(self):
        if sum(item.size for item in self.files) > PROTECTED_BYTES_MAX:
            raise ValueError("the protected set is over 50 MB; narrow it")
        return self


class GoalSpec(Contract):
    """What the user set: the objective, its checks, the protected set (from Start), the job's tier and cap.
    The steer key is the job's id, on `TurnRequest.steer_key`, not here."""
    objective: Annotated[str, Field(min_length=1, max_length=OBJECTIVE_MAX)]
    checks: tuple[GoalCheck, ...] = Field(min_length=1, max_length=CRITERIA_MAX + COMMAND_CHECKS_MAX)
    protected: ProtectedSet | None = None
    tier: Literal["lean", "standard", "ample"] = DEFAULT_TIER
    usd_cap: Annotated[float, Field(gt=0, le=MAX_USD_CAP, allow_inf_nan=False)] | None = None   # never raised by itself

    @model_validator(mode="after")
    def bounded_checks(self):
        ids = [check.id for check in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate goal check")
        if sum(check.kind != "check" for check in self.checks) > CRITERIA_MAX:
            raise ValueError(f"at most {CRITERIA_MAX} criteria")
        if sum(check.kind == "check" for check in self.checks) > COMMAND_CHECKS_MAX:
            raise ValueError(f"at most {COMMAND_CHECKS_MAX} check: lines")
        return self


class SeenMeasure(Contract):
    """One (check, measure) value this goal produced: a digest of the check's own measure (a `check:` run's exit
    code and output, the phrases found, the files or sources counted), and its size for the counts and sets."""
    check_id: Identifier
    digest: Sha256
    size: NonnegativeInt | None = None


class GoalBlocker(Contract):
    """L7-6: why a goal stopped short, for its card (`goal_state.blocker`)."""
    code: Literal["no_progress", "protected_changed", "unprotected", "user_checks", "budget"]
    files: tuple[RelPath, ...] = Field(default=(), max_length=200)


class GoalProgress(Contract):
    """The rounds' record, on `Progress.goal`. Resume keeps it (the seen set included) and resets the streak; an edit
    (a spec revision) starts a fresh one."""
    status: GoalStatus = "not_started"
    round: Annotated[int, Field(ge=0, le=10_000, strict=True)] = 0
    stall: Annotated[int, Field(ge=0, le=BLOCKED_AFTER, strict=True)] = 0   # rounds in a row without progress
    unmet: tuple[Identifier, ...] = Field(default=(), max_length=CRITERIA_MAX + COMMAND_CHECKS_MAX)
    ever_met: tuple[Identifier, ...] = Field(default=(), max_length=CRITERIA_MAX + COMMAND_CHECKS_MAX)
    seen: tuple[SeenMeasure, ...] = Field(default=(), max_length=1000)
    accepted: tuple[ProtectedFile, ...] = Field(default=(), max_length=PROTECTED_FILES_MAX)   # declared outputs
    last_receipt: NonnegativeInt = 0   # the trace index the last verdict read up to
    # L7-6: why it stopped short, and a blocked goal's one step for the user, for its card after a restart too.
    blocker: GoalBlocker | None = None
    step: Annotated[str, Field(max_length=300)] | None = None
    # L7-5e: the checks the judge gave no verdict on when the goal stopped; they are the user's to confirm, as a
    # check Arslan can't verify is (`turn_answer._goal_round`, `task_repository.accept_review`).
    unjudged: tuple[Identifier, ...] = Field(default=(), max_length=CRITERIA_MAX)


def acceptance(spec: GoalSpec) -> list[dict]:
    """The goal's checks as its task's acceptance (L7-2), `answer-delivered` first as for every job; it is never a goal
    check, so it never counts toward the goal. Each is met only through its own condition (`task_validation.evaluate`):
    a mentions check is `file_contains` on its file, never a `text` rule on the reply. A user-confirmed check is the
    user's (`human`): never judged by the model, never met by Arslan."""
    import shlex
    from server.services.task_service import ANSWER_DELIVERED
    out = [dict(ANSWER_DELIVERED)]
    for check in spec.checks:
        item: dict = {"id": check.id, "description": check.description, "evaluator": "deterministic"}
        if check.user_confirmed:
            item["evaluator"] = "human"
        elif check.kind == "file_saved":
            item["rule"] = {"kind": "file_saved", "target": check.path, "minimum": check.minimum or 1}
        elif check.kind == "file_contains":
            item["rule"] = {"kind": "file_contains", "target": check.path, "contains": list(check.phrases)}
        elif check.kind == "sources_read":
            item["rule"] = {"kind": "sources_read", "minimum": check.minimum or 1,
                            **({"target": check.path} if check.path else {})}
        elif check.kind == "check":     # met only by the host's own run (L7-5), never the worker's run_command
            item.update(critical=True, rule={"kind": "code_test", "target": shlex.join(check.argv),
                                             "argv": list(check.argv)})
        else:                           # judgement: the judge, over the named file as the host reads it
            item["evaluator"] = "model"
        out.append(item)
    return out


def after_verdict(spec: GoalSpec, progress: GoalProgress, *, met: frozenset[str],
                  measures: tuple[SeenMeasure, ...]) -> GoalProgress:
    """One round's verdict, recorded (card: "No progress"). `met`: the checks whose own condition held; `measures`:
    each check's measure, as the host evaluated it.

    A round makes progress when a check unmet at its start is met for the first time, or has a measure the seen set
    doesn't hold (for a count or a set, also larger than every earlier one). Measures need a baseline: one Start
    recorded in the seen set, or an earlier round; without one, round 1's measures are the baseline. Nothing else
    counts: never the answer, never `answer-delivered` (not a goal check), never a user-confirmed check. The streak
    of rounds without progress reaching BLOCKED_AFTER is blocked; only user-confirmed checks left is review."""
    own = [check.id for check in spec.checks if not check.user_confirmed]
    met = met & set(own)
    unmet_before = set(progress.unmet)
    progressed = any(cid in unmet_before and cid not in progress.ever_met for cid in met)
    baseline = progress.round > 0 or bool(progress.seen)
    seen = list(progress.seen)
    for item in measures:
        earlier = [old for old in seen if old.check_id == item.check_id]
        if item.check_id not in own or any(old.digest == item.digest for old in earlier):
            continue
        larger = item.size is None or all(old.size is None or item.size > old.size for old in earlier)
        progressed = progressed or (baseline and item.check_id in unmet_before and larger)
        seen.append(item)
    stall = 0 if progressed else min(progress.stall + 1, BLOCKED_AFTER)
    unmet = tuple(cid for cid in own if cid not in met)
    status = ("active" if unmet and stall < BLOCKED_AFTER else "blocked" if unmet
              else "complete" if len(own) == len(spec.checks) else "review")
    return progress.model_copy(update={
        "status": status, "round": progress.round + 1, "stall": stall, "unmet": unmet,
        "ever_met": tuple(cid for cid in own if cid in met or cid in progress.ever_met), "seen": tuple(seen)})


def unverifiable(spec: GoalSpec) -> tuple[str, ...]:
    """L7-3: the checks Arslan can't verify, flagged by the host and never by the model (card: "Checks Arslan can't
    verify"). Verifiable: file saved or file contains with a path, sources read, the user's `check:` line, or a
    judgement over a file the user named (`by_user`: drafting never sets it, except for a path the user's own
    objective names). A check the user said they'll confirm themselves isn't flagged: it is theirs.
    L7-5c: a judgement is verifiable only over a target the host's judge can read as ONE file
    (`task_validation._read_named`); over anything else it would fail every round. Readable: a file that is there,
    a file the goal's own file_saved / file_contains names, or a name with a file extension (a file the host
    resolves later against the readable folders). Not: a folder, an app bundle, or a bare name such as an app's
    ('提醒事项', 'Reminders'). Pure on the path except one stat of an absolute (or ~) path."""
    import os
    from pathlib import PurePath
    saved = {check.path for check in spec.checks if check.kind in {"file_saved", "file_contains"} and check.path}

    def readable_file(path: str) -> bool:
        named = os.path.expanduser(path)
        # L7-5e: a folder is never one file, also when the goal's own file_saved names it ("a table saved in this
        # folder", T2 and T3 in the L7-7 bench): the judge could not read it in any round.
        if named.endswith("/") or (os.path.isabs(named) and os.path.isdir(named)):
            return False
        if path in saved:
            return True
        if os.path.isabs(named) and os.path.exists(named):
            return os.path.isfile(named)
        suffix = PurePath(named.rstrip("/")).suffix.lower()
        return not named.endswith("/") and suffix not in {"", ".app"}

    def verifiable(check: GoalCheck) -> bool:
        if check.kind in {"file_saved", "file_contains"}:
            return check.path is not None
        if check.kind == "judgement":
            return check.path is not None and check.by_user and readable_file(check.path)
        return True                     # sources_read, check
    return tuple(check.id for check in spec.checks if not check.user_confirmed and not verifiable(check))


_PHASE_STATUS = {pair: status for status, pair in STATUS_PHASE.items()}


def status_of(phase: str, pause_reason: str | None) -> GoalStatus:
    """L7-3: a goal row's status from its phase and pause reason (STATUS_PHASE read back). A row the goal's own
    stops didn't park (a failed run, or a pause the task machinery chose, such as checks that didn't run) needs the
    user: blocked when it failed, otherwise review."""
    if phase in {"running", "verifying"}:
        return "active"
    return _PHASE_STATUS.get((phase, pause_reason if phase == "waiting_user" else None),
                             "blocked" if phase == "failed" else "review")


# -- L7-6: the goal card's state, the `goal_state` key of a goal's `job_update` (card: UI, "The frame") ---------------
FRAME_OUTCOME = {"paused": "stopped", "cleared": "stopped", "blocked": "blocked", "budget_limited": "out_of_budget",
                 "interrupted": "interrupted", "review": "partial", "complete": "done"}


def goal_state(spec: GoalSpec, progress: GoalProgress | None, *, status: str, items: dict, finished: bool,
               spend_usd: float | None, cap_usd: float | None) -> dict:
    """The card's state, every key always present. `items`: the last validation report's check items by id (the
    host's receipts); a check with none is pending, or not reached once the goal stopped. Never the answer text."""
    record = progress or GoalProgress()
    flagged = set(unverifiable(spec))
    checks = []
    for check in spec.checks:
        item = items.get(check.id) or {}
        receipt = None
        if item.get("code"):
            measure = item.get("measure") or {}
            receipt = {"code": item["code"], "path": item.get("path"), "exit_code": item.get("exit_code"),
                       "count": measure.get("size")}
        checks.append({"id": check.id, "description": check.description, "kind": check.kind,
                       "status": item.get("status") or ("not_reached" if finished else "pending"), "receipt": receipt,
                       "flagged": check.id in flagged, "user_confirmed": check.user_confirmed,
                       "outputs": list(check.outputs)})
    files = spec.protected.files if spec.protected is not None else ()
    return {"status": status, "round": record.round, "met": sum(c["status"] == "passed" for c in checks),
            "total": len(checks), "spend_usd": spend_usd, "cap_usd": cap_usd, "tier": spec.tier,
            "blocker": record.blocker.model_dump(mode="json", exclude={"schema_version"}) if record.blocker else None,
            "step": record.step, "unprotected": unprotected(spec.protected),
            "missing_files": [f.path for f in files if f.sha256 is None], "checks": checks}


# -- L7-5: the protected set (card: "Check files are protected from Start") ------------------------------------------
# Recorded at Start and verified before and after each host run of a `check:` line; nothing is copied, the check runs
# in place. Not followed, and so not protected (disclosed): runner plugins in skipped folders (`node_modules`, virtual
# environments), shell variables, globs and command substitution in scripts, Makefile includes and variables, JS
# config files (only `vitest.config.*`'s literal `include` is read), and code the check imports beyond these files.
# Generated folders the scan leaves out, in two kinds (max review round 2). `_SKIP`: never walked, because no runner
# reads config there: pytest's default `norecursedirs` (`_pytest/main.py`: `*.egg`, `.*`, `_darcs`, `build`, `CVS`,
# `dist`, `node_modules`, `venv`, `{arch}`) covers each, and its config lookup walks up from the arguments, never
# down; npm reads `.npmrc` only at the project's own prefix, walking up. `_SKIP_TESTS`: generated build output that
# pytest would still recurse into (not in `norecursedirs`), so their runner config files are still scanned there;
# only their test-like names are left out. Both kinds are walked whole (config names only) when a pytest config
# sets its own `norecursedirs`, or a check's argv names a path inside one (`scan:skipped`). `build/` is not skipped:
# not clearly generated. `.swiftpm/` is not skipped either (its shared schemes and configuration are the user's);
# only `xcuserdata/` in it, Xcode's per-user state.
_SKIP = {".git", "node_modules", ".tox", ".nox", ".venv", "venv", ".pytest_cache", ".mypy_cache", ".ruff_cache",
         ".build", ".next", "dist"}
_SKIP_TESTS = {"__pycache__", "DerivedData", "xcuserdata", "coverage"}
# Matched without regard to case; the CamelCase names (Swift, Xcode, JUnit) case-sensitively, so `latest/` and
# `contest.py` stay the work.
_TEST_DIRS = {"tests", "test", "__tests__", "spec", "__snapshots__", "testdata", "fixtures"}
_TEST_NAMES = ("test_*", "*_test.*", "*.test.*", "*.spec.*", "*_spec.*", "*.snap", "golden*", "*.xctestplan")
_CAMEL_DIRS, _CAMEL_NAMES = ("*Tests",), ("*Tests.*", "*Test.*", "*Spec.*")
# The runner config a run reads without its argv naming it; a NEW one is a change, here and in each parent folder:
# - pytest 9.1, `_pytest/config/findpaths.py` (`locate_config`): the first of pytest.toml, .pytest.toml, pytest.ini,
#   .pytest.ini, pyproject.toml, tox.ini, setup.cfg, walking up from the arguments' common folder; and conftest.py
#   in every folder from the rootdir down (`_pytest/config/__init__.py`, `_getconftestmodules`).
# - npm 10, `@npmcli/config/lib/index.js` (`loadBuiltinConfig`, `loadGlobalConfig`, `loadUserConfig`,
#   `loadProjectConfig`): `<npm>/npmrc`, `<prefix>/etc/npmrc`, `~/.npmrc` and `<localPrefix>/.npmrc`, where
#   localPrefix is the nearest folder up holding package.json or node_modules (a workspace root's too). Only those
#   inside the working folder or its parents can be seen here; any `.npmrc` or `npmrc` file counts.
_PYTEST_CONFIG = ("pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini", "pyproject.toml", "tox.ini",
                  "setup.cfg", "conftest.py")
_CONFIG = ("conftest.py", "pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini", "tox.ini", "setup.cfg",
           ".npmrc", "npmrc", "Makefile", "jest.config.*", "vitest.config.*")
_SECTIONED = {"pyproject.toml", "package.json"}       # only their test sections: `section` is set
_PARENTS = (*_PYTEST_CONFIG, ".npmrc", "package.json")
_RUNNERS, _MAKES = {"npm", "pnpm", "yarn", "bun"}, {"make", "gmake", "$(MAKE)", "${MAKE}"}
_SCRIPTS = {".sh", ".bash", ".zsh", ""}
WALK_MAX = 200_000
_EMPTY = hashlib.sha256(b"{}").hexdigest()     # a new test-config file with no test sections


def _walk(root, *, deep: bool = False):
    """Every file under `root`, relative, past the skipped folders and bytecode caches; a linked folder is an entry.
    In a `_SKIP_TESTS` folder (and, `deep`, a `_SKIP` one) only the runner config files."""
    import os
    from pathlib import Path
    count, configs_only = 0, set()
    for folder, dirs, names in os.walk(root):
        inside = folder in configs_only
        keep = []
        for d in dirs:
            path = os.path.join(folder, d)
            if os.path.exists(os.path.join(path, "pyvenv.cfg")) or (d in _SKIP and not deep):
                continue                    # pytest skips virtual environments itself (`collect_in_virtualenv`)
            if inside or d in _SKIP_TESTS or d in _SKIP:
                configs_only.add(path)
            keep.append(d)
        dirs[:] = keep
        for name in [*names, *(d for d in dirs if os.path.islink(os.path.join(folder, d)))]:
            count += 1
            if count > WALK_MAX:
                raise ValueError("the working folder is too large to scan")
            if name.endswith(".pyc") or inside and name not in (*_PARENTS, "npmrc"):
                continue
            yield Path(folder, name).relative_to(root).as_posix()


def _conventional(rel: str) -> bool:
    from fnmatch import fnmatchcase
    *folders, name = rel.split("/")
    return (bool(_TEST_DIRS.intersection(f.lower() for f in folders))
            or any(fnmatchcase(f, p) for f in folders for p in _CAMEL_DIRS)
            or any(fnmatchcase(name.lower(), p.lower()) for p in (*_TEST_NAMES, *_CONFIG))
            or any(fnmatchcase(name, p) for p in _CAMEL_NAMES))


def unprotected(protected: ProtectedSet | None) -> bool:
    """Max review round 1: nothing in the working folder protects the goal's `check:` lines (no file recorded there
    with a digest; a parent folder's config alone doesn't count). Start says so; the goal is then never complete on
    its `check:` lines alone, it stops at review."""
    return protected is not None and not any(f.sha256 and not f.path.startswith("../") for f in protected.files)


def _matches(rel: str, patterns) -> bool:
    import re
    from fnmatch import fnmatchcase
    for pattern in patterns:
        kind, _, value = pattern.partition(":")
        if kind == "under" and (rel == value or rel.startswith(value.rstrip("/") + "/")) \
                or kind == "in" and rel.rpartition("/")[0] == value \
                or kind == "name" and fnmatchcase(rel.rsplit("/", 1)[-1], value) \
                or kind == "glob" and (fnmatchcase(rel, value) or fnmatchcase(rel, value.removeprefix("**/"))):
            return True
        if kind == "re":
            try:
                if re.search(value, rel):
                    return True
            except re.error:
                return True                     # a pattern that can't be read protects everything: closed
    return False


def _sections(path):
    import json
    import tomllib
    if path.name == "pyproject.toml":
        tool = tomllib.loads(path.read_text()).get("tool", {})
        return {key: tool[key] for key in ("pytest", "tox", "coverage") if key in tool}
    data = json.loads(path.read_text())
    return {key: data[key] for key in ("scripts", "jest") if key in data} if isinstance(data, dict) else data


def _digest(path, sectioned: bool) -> str | None:
    """A file's sha256, its test sections' for `pyproject.toml` and `package.json` (the whole file when they don't
    parse), a linked folder's target; None when it can't be read (or is gone)."""
    import json
    import os
    try:
        if os.path.islink(path) and os.path.isdir(path):
            body = ("link:" + os.readlink(path)).encode()
        elif sectioned:
            try:
                body = json.dumps(_sections(path), sort_keys=True, default=str).encode()
            except (ValueError, UnicodeDecodeError):
                body = path.read_bytes()
        else:
            body = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(body).hexdigest()


def _named(root, words, *, existing: bool) -> list[str]:
    """The workspace files these words name (an argv, a script's command): inside `root` only. Not `existing`: a name
    that looks like a file and isn't there yet is kept too (the form warns about it)."""
    import os
    out = []
    for word in words:
        word = word.partition("=")[2] if word.startswith("-") else word
        if not word or word.startswith("-") or any(c in word for c in "$*?`"):
            continue
        rel = os.path.normpath(os.path.relpath(word, root) if os.path.isabs(word) else word)
        if rel == "." or rel.startswith(".."):
            continue
        path = root / rel
        if path.is_file() or (not existing and not path.exists() and ("/" in rel or path.suffix)):
            out.append(rel.replace(os.sep, "/"))
    return out


def _commands(text: str) -> list[list[str]]:
    import re
    import shlex
    out = []
    for part in re.split(r"&&|\|\||[;\n|&]", text or ""):
        try:
            words = shlex.split(part, comments=True)
        except ValueError:
            words = part.split()
        while words and ("=" in words[0] and not words[0].startswith("-") or words[0] in {"exec", "env", "time"}):
            words = words[1:]
        if words:
            out.append(words)
    return out


def _make_rules(text: str) -> tuple[dict, str | None]:
    import re
    rules, current, first = {}, None, None
    for line in (text or "").splitlines():
        if line.startswith("\t") and current is not None:
            current[1].append(line.strip().lstrip("@-+"))
            continue
        rule = re.match(r"^([A-Za-z0-9_./%$(){}-][^:=#]*)::?(?!=)(.*)$", line)
        current = None
        if rule:
            prereqs, _, inline = rule.group(2).partition(";")
            current = (prereqs.split(), [inline.strip()] if inline.strip() else [])
            for target in rule.group(1).split():
                rules[target] = current
                first = first or (target if not target.startswith(".") else None)
    return rules, first


def _callees(root, argv) -> set[str]:
    """The files the check's argv invokes through the runner's own indirection, followed in turn: `npm run X` (and
    `npm test`, with their pre- and post- scripts), `make T` (prerequisites and recipe), and shell scripts those
    name. The `test` script and the Makefile `test` recipe always count (card)."""
    import json
    from pathlib import Path
    try:
        scripts = json.loads((root / "package.json").read_text()).get("scripts") or {}
    except (OSError, ValueError, AttributeError):
        scripts = {}
    out, seen, queue = set(), set(), [("words", tuple(argv)), ("script", "test"), ("target", "test")]
    while queue and len(seen) < 256:
        kind, item = queue.pop()
        if (kind, item) in seen:
            continue
        seen.add((kind, item))
        if kind == "words":
            head, rest = Path(item[0]).name, [w for w in item[1:] if not w.startswith("-")]
            if head in _RUNNERS and rest:
                name = ("test" if rest[0] in {"test", "t", "tst"} else rest[1] if rest[0] in {"run", "run-script"}
                        and len(rest) > 1 else rest[0] if head != "npm" else None)
                queue += [("script", n) for n in ((name, "pre" + name, "post" + name) if name else ())]
            if head in _MAKES or item[0] in _MAKES:
                makefile, skip, targets = "Makefile", None, []
                for word in item[1:]:
                    if skip:
                        makefile = word + "/Makefile" if skip == "-C" else word if skip == "-f" else makefile
                        skip = None
                    elif word in {"-C", "-f", "-I", "-o", "-W"}:
                        skip = word
                    elif not word.startswith("-") and "=" not in word:
                        targets.append(word)
                queue.append(("make", makefile + "\0" + " ".join(targets)))
            for rel in _named(root, item, existing=True):
                out.add(rel)
                if Path(rel).suffix in _SCRIPTS:
                    queue.append(("file", rel))
        elif kind == "script" and isinstance(scripts.get(item), str):
            queue += [("words", tuple(words)) for words in _commands(scripts[item])]
        elif kind in {"make", "target"}:
            makefile, _, targets = item.partition("\0") if kind == "make" else ("Makefile", "", item)
            try:
                rules, first = _make_rules((root / makefile).read_text()[:1_000_000])
            except (OSError, UnicodeDecodeError):
                continue
            for target in targets.split() or [first]:
                prereqs, recipe = rules.get(target, ((), ()))
                queue += [("make", makefile + "\0" + p) if p in rules else ("words", (p,)) for p in prereqs]
                queue += [("words", tuple(words)) for line in recipe for words in _commands(line)]
        elif kind == "file":
            try:
                text = (root / item).read_text()[:1_000_000]
            except (OSError, UnicodeDecodeError):
                continue
            queue += [("words", tuple(words)) for words in _commands(text)]
    return out


def _runner_patterns(root, tree) -> set[str]:
    """Where the runner config points: pytest's `testpaths` and `python_files`, jest's `testMatch`, `testRegex` and
    `roots`, vitest's literal `include`. A config that can't be read points nowhere; it is protected itself."""
    import configparser
    import json
    import re
    import tomllib
    out = set()
    join = lambda folder, value: f"{folder}/{value}" if folder else value  # noqa: E731
    for rel in tree:
        folder, _, name = rel.rpartition("/")
        path = root / rel
        try:
            pytest = None
            if name in {"pytest.ini", "tox.ini", "setup.cfg"}:
                parser = configparser.ConfigParser(interpolation=None, strict=False)
                parser.read_string(path.read_text())
                section = "tool:pytest" if name == "setup.cfg" else "pytest"
                pytest = dict(parser[section]) if parser.has_section(section) else None
            elif name == "pyproject.toml":
                pytest = tomllib.loads(path.read_text()).get("tool", {}).get("pytest", {}).get("ini_options")
            elif name == "package.json":
                jest = json.loads(path.read_text()).get("jest") or {}
                strip = lambda v: str(v).removeprefix("<rootDir>/")  # noqa: E731
                out.update("glob:" + join(folder, strip(v)) for v in jest.get("testMatch") or ())
                regex = jest.get("testRegex") or ()
                out.update("re:" + str(v) for v in ([regex] if isinstance(regex, str) else regex))
                out.update("under:" + join(folder, strip(v)) for v in jest.get("roots") or ())
            elif name.startswith("vitest.config."):
                for block in re.findall(r"include\s*:\s*\[([^\]]*)\]", path.read_text()[:1_000_000]):
                    out.update("glob:" + join(folder, v) for v in re.findall(r"['\"]([^'\"]+)['\"]", block))
            if isinstance(pytest, dict):
                if "norecursedirs" in pytest:
                    out.add("scan:skipped")         # pytest may recurse into the skipped folders: walk them too
                words = lambda v: v.split() if isinstance(v, str) else [str(x) for x in v]  # noqa: E731
                out.update("under:" + join(folder, p.strip("/")) for p in words(pytest.get("testpaths") or ()))
                out.update("name:" + p for p in words(pytest.get("python_files") or ()))
        except (OSError, ValueError, UnicodeDecodeError, AttributeError, TypeError, configparser.Error):
            continue
    return out


def record_protected(root, checks, marks=()) -> ProtectedSet:
    """L7-5: the protected set at Start, for the goal's `check:` lines: each file their argv names (except the user's
    own outputs: a file to save the user named or confirmed, or a declared output), the files those invoke, the
    conventional test, expected-output and config files anywhere in the working folder, where the runner config
    points, the parent folders' pytest config, and the user's marks. ValueError when it's over the limits."""
    import os
    from fnmatch import fnmatchcase
    from pathlib import Path
    root = Path(root).resolve()
    commands = [check for check in checks if check.kind == "check"]
    own = {check.path for check in checks if check.kind == "file_saved" and check.by_user}
    declared = [pattern for check in commands for pattern in check.outputs]
    tree = list(_walk(root))
    patterns = _runner_patterns(root, tree) | {"in:" + p.rpartition("/")[0] for p in declared}
    if any(set(os.path.normpath(word.partition("=")[2] if word.startswith("-") else word).split(os.sep))
           & (_SKIP | _SKIP_TESTS) for check in commands for word in check.argv):
        patterns.add("scan:skipped")                # the argv points into a skipped folder: walk it too
    if "scan:skipped" in patterns:
        tree = list(_walk(root, deep=True))
    chosen = {rel: False for rel in tree if _conventional(rel) or rel.rsplit("/", 1)[-1] in _SECTIONED
              or _matches(rel, patterns)}
    for check in commands:
        for rel in [*_named(root, check.argv, existing=False), *_callees(root, check.argv)]:
            if rel not in own and not any(fnmatchcase(rel, p) for p in declared):
                chosen.setdefault(rel, True)
    for rel in _named(root, marks, existing=False):
        chosen.setdefault(rel, True)
    for parent in root.parents:
        for name in _PARENTS:
            rel = os.path.relpath(parent / name, root)
            if (parent / name).is_file():
                chosen[rel] = False
            else:
                patterns.add("file:" + rel)
    if len(chosen) > PROTECTED_FILES_MAX or len(patterns) > 256:
        raise ValueError("the protected set is over 2,000 files; narrow it")
    files, total = [], 0
    for rel in sorted(chosen):
        path = root / rel
        if not (path.is_file() or path.is_symlink()):
            files.append(ProtectedFile(path=rel))           # named by the argv, not there at Start: a warning
            continue
        total += path.stat().st_size if path.is_file() else 0
        if total > PROTECTED_BYTES_MAX:
            raise ValueError("the protected set is over 50 MB; narrow it")
        sectioned = path.name in _SECTIONED
        digest = _digest(path, sectioned)
        if digest is None:
            raise ValueError(f"{rel} can't be read")
        files.append(ProtectedFile(path=rel, sha256=digest, section="test sections" if sectioned else None,
                                   size=path.stat().st_size if path.is_file() else 0))
    return ProtectedSet(files=tuple(files), patterns=tuple(sorted(patterns)))


def protected_changes(protected: ProtectedSet, root, *, outputs=(), accepted=()) -> tuple[tuple[str, ...],
                                                                                         tuple[ProtectedFile, ...]]:
    """L7-5: (what changed, the new declared outputs to accept). A change is an edit, addition or deletion of a
    protected file (or one accepted before), or a new file where one stops the goal. `outputs`: the declared output
    patterns of the host run just finished; only new files matching one are accepted, never one named like runner
    config. Before a run it is empty, so a file the worker wrote there between runs is a change."""
    from fnmatch import fnmatchcase
    from pathlib import Path
    root = Path(root).resolve()
    known = {item.path: item for item in (*protected.files, *accepted)}
    changed = {item.path for item in known.values()
               if item.sha256 is not None and _digest(root / item.path, item.section is not None) != item.sha256}
    changed |= {p[5:] for p in protected.patterns if p.startswith("file:") and (root / p[5:]).exists()}
    new = []
    for rel in _walk(root, deep="scan:skipped" in protected.patterns):
        if rel in known and known[rel].sha256 is not None:
            continue
        name = rel.rsplit("/", 1)[-1]
        if name in _SECTIONED:
            if _digest(root / rel, True) != _EMPTY:
                changed.add(rel)
        elif _conventional(rel) or _matches(rel, protected.patterns):
            config = name in _PARENTS or any(fnmatchcase(name.lower(), p.lower()) for p in (*_CONFIG, "*.config.*"))
            if not config and any(fnmatchcase(rel, p) for p in outputs):
                new.append(rel)
            else:
                changed.add(rel)
    taken = []
    for rel in sorted(new):
        digest = _digest(root / rel, False)
        if digest is None:
            changed.add(rel)
        else:
            taken.append(ProtectedFile(path=rel, sha256=digest, size=(root / rel).stat().st_size))
    return tuple(sorted(changed)), tuple(taken)

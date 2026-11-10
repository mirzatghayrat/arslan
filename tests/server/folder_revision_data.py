"""Hash-verified policy snapshots, independent of checkout depth and Git metadata."""
import hashlib
import json
from pathlib import Path
import re
import sys
import types

MAIN = "bc3a2b605dedec8514a312c18306958af3cf483d"
DATA = Path(__file__).with_suffix("")
MANIFEST_SHA256 = "300989d13c4afd4965eb036ece8045ba81eeb683b176a8edfad9e6a12302bc08"


def sources(revision):
    manifest = (DATA / "manifest.json").read_bytes()
    if hashlib.sha256(manifest).hexdigest() != MANIFEST_SHA256:
        raise AssertionError("Frozen revision manifest hash mismatch")
    entries = json.loads(manifest)[revision]
    result = {}
    for name in ("shell_grammar", "shell_text", "terminal_policy"):
        if name not in entries:
            continue
        digest = entries[name]
        data = (DATA / (digest + ".txt")).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise AssertionError(f"Frozen revision source hash mismatch: {revision}/{name}")
        result[name] = data.decode("utf-8")
    return result


def load_revision(revision, monkeypatch):
    modules = {}
    for name, source in sources(revision).items():
        module = types.ModuleType(f"_frozen_{revision}_{name}")
        monkeypatch.setitem(sys.modules, module.__name__, module)
        if name == "terminal_policy":
            source, count = re.subn(r"^from server.services import (?:shell_grammar, )?shell_text$", "", source,
                                    flags=re.M)
            assert count == 1, "Frozen policy must import its own reader modules"
            module.__dict__.update(modules)
        exec(compile(source, f"{revision}/{name}.py", "exec"), module.__dict__)
        modules[name] = module
    return modules["terminal_policy"]

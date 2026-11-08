"""Regenerate stored verdicts from two explicitly supplied historical sources.

Source directories contain shell_text.py, shell_grammar.py, terminal_policy.py.
No Git command or metadata is used. Sources are Python policy code; generated
command strings are only passed to assess and read, never to a subprocess.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import types

from tests.server.quoted_args_baseline_data import fingerprint
from tests.server.quoted_args_file_run_evidence import GENERATORS


def source_version(directory, label):
    modules = []
    for basename in ("shell_text", "shell_grammar", "terminal_policy"):
        path = directory / (basename + ".py")
        if not path.is_file():
            raise ValueError(f"Missing {label} baseline source: {basename}.py")
        module = types.ModuleType("quoted_baseline_" + label + "_" + basename)
        sys.modules[module.__name__] = module
        exec(compile(path.read_text(), "<" + module.__name__ + ">", "exec"), module.__dict__)
        modules.append(module)
    modules[1].shell_text = modules[0]
    modules[2].shell_text = modules[0]
    modules[2].shell_grammar = modules[1]
    return modules[1:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-source", type=Path, required=True)
    parser.add_argument("--original-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    versions = [source_version(args.main_source, "main"), source_version(args.original_source, "original")]
    provenance = {}
    for label, directory in (("main", args.main_source), ("original", args.original_source)):
        provenance[label] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in (directory / (name + ".py")
                                          for name in ("shell_text", "shell_grammar", "terminal_policy"))}
    cases = {}
    for kind, generate in GENERATORS.items():
        for case, text in generate():
            key = kind + "/" + case
            assert key not in cases, f"Duplicate baseline id: {key}"
            for reader, _ in versions:
                reader.read(text)
            cases[key] = [fingerprint(text), *(policy.assess(text).level for _, policy in versions)]
        print(kind, "generated", flush=True)
    encoded = (json.dumps(dict(schema=1, source_sha256=provenance, cases=cases),
                          indent=1, sort_keys=True) + "\n").encode()
    args.output.write_bytes(gzip.compress(encoded, mtime=0))
    print("baseline cases", len(cases))


if __name__ == "__main__":
    main()

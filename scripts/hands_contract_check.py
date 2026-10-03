#!/usr/bin/env python3
"""Check an agent-desktop binary against Arslan's Hands contract (0.1.53).

Arslan uses eleven agent-desktop commands. tests/fixtures/hands_contract/ holds
one case per command and per error code Arslan handles: the request, the exact
command line Hands builds for it (the Rust tests check the builder produces it),
a real envelope, and what Arslan must make of it (pytest checks the parser).
This script is the third leg: it runs those command lines against a REAL binary
and a fixture app and checks every result has the shape Arslan reads. Any
replacement — upstream's build, our fork's, a future trimmed reimplementation —
must pass it before it ships.

Needs macOS, Xcode command line tools (swiftc, clang), and Accessibility for the
app this runs from (Terminal, say). The fixture window shows on every Space and
never takes focus; nothing else on the desktop is touched.

    python3 scripts/hands_contract_check.py --binary path/to/agent-desktop
    python3 scripts/hands_contract_check.py --binary … --record   # refresh the envelopes
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "tests" / "fixtures" / "hands_contract"
FIXTURE_SRC = ROOT / "scripts" / "hands_fixture"
APP = "Hands Fixture"
PLACEHOLDER = "sfixture0"
TYPES = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict}

INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.arslan.hands-fixture</string>
<key>CFBundleName</key><string>Hands Fixture</string>
<key>CFBundleExecutable</key><string>HandsFixture</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSUIElement</key><true/>
</dict></plist>
"""


def pointer(doc, path: str):
    """JSON pointer lookup; raises KeyError/IndexError when absent."""
    node = doc
    for part in path.strip("/").split("/"):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def shape_problems(case: dict, exit_code: int | None, envelope: dict) -> list[str]:
    """What is wrong with one real result, judged by the case's expectations."""
    expect = case["expect"]
    problems = []
    if envelope.get("version") is None or not isinstance(envelope.get("ok"), bool):
        return ["not an agent-desktop envelope (no version/ok)"]
    ok = envelope["ok"]
    also = expect.get("also", [])
    allowed_ok = expect["ok"] or "ok" in also
    allowed_codes = ([] if expect["ok"] else [expect.get("code")]) + [a for a in also if a != "ok"]
    if ok and not allowed_ok:
        return [f"expected {expect.get('code')}, got ok"]
    if not ok:
        code = (envelope.get("error") or {}).get("code")
        if code not in allowed_codes:
            return [f"expected {'ok' if expect['ok'] else expect.get('code')}, got {code}: "
                    f"{(envelope.get('error') or {}).get('message')}"]
        if exit_code not in (1, None):
            problems.append(f"an error must exit 1, exited {exit_code}")
        return problems
    if exit_code not in (0, None):
        problems.append(f"success must exit 0, exited {exit_code}")
    for path, kind in (expect.get("reads") or {}).items():
        try:
            value = pointer(envelope, path)
        except (KeyError, IndexError, TypeError, ValueError):
            problems.append(f"missing {path}")
            continue
        if kind != "any" and not (isinstance(value, TYPES[kind]) and not (kind == "integer" and isinstance(value, bool))):
            problems.append(f"{path} should be {kind}, is {type(value).__name__}")
    for path, item in (expect.get("contains") or {}).items():
        try:
            if item not in pointer(envelope, path):
                problems.append(f"{path} lacks {item!r}")
        except (KeyError, IndexError, TypeError):
            problems.append(f"missing {path}")
    return problems


def private(envelope: dict) -> dict:
    """What may be written into the public fixtures: `list-apps` lists every app
    running on this Mac, so only the fixture's own entry is kept."""
    apps = (envelope.get("data") or {}).get("apps") if isinstance(envelope.get("data"), dict) else None
    if isinstance(apps, list):
        envelope = json.loads(json.dumps(envelope))
        envelope["data"]["apps"] = [a for a in apps if a.get("bundle_id") == "com.arslan.hands-fixture"]
    return envelope


def load_cases() -> list[tuple[Path, dict]]:
    out = [(p, json.loads(p.read_text())) for p in sorted(CASES.glob("*.json"))]
    return sorted(out, key=lambda pc: pc[1]["order"])


class Desk:
    """The fixture app, a private agent-desktop state root, and the binary."""

    def __init__(self, binary: Path, work: Path):
        self.binary = binary
        self.work = work
        self.home = work / "ad"
        self.home.mkdir(mode=0o700)
        self.app = work / "HandsFixture.app"
        macos = self.app / "Contents" / "MacOS"
        macos.mkdir(parents=True)
        subprocess.run(["swiftc", "-O", "-o", str(macos / "HandsFixture"),
                        str(FIXTURE_SRC / "HandsFixture.swift")], check=True)
        (self.app / "Contents" / "Info.plist").write_text(INFO_PLIST)
        subprocess.run(["codesign", "-s", "-", "-f", str(self.app)], check=True, capture_output=True)
        self.disclaim = work / "disclaim"
        subprocess.run(["clang", "-o", str(self.disclaim), str(FIXTURE_SRC / "disclaim.c")], check=True)

    def run(self, argv: list[str], *, without_accessibility: bool = False) -> tuple[int, dict]:
        command = [str(self.binary), *argv]
        if without_accessibility:
            command = [str(self.disclaim), *command]
        env = {"HOME": os.environ.get("HOME", ""), "PATH": "/usr/bin:/bin",
               "AGENT_DESKTOP_HOME": str(self.home), "LANG": "en_US.UTF-8"}
        done = subprocess.run(command, capture_output=True, text=True, env=env, timeout=60)
        try:
            return done.returncode, json.loads(done.stdout)
        except json.JSONDecodeError:
            return done.returncode, {"_unparsed": done.stdout[:500], "_stderr": done.stderr[:500]}

    def launch(self) -> None:
        subprocess.run(["open", "-g", "-n", str(self.app)], check=True)
        for _ in range(100):
            _, env = self.run(["list-windows", f"--app={APP}"])
            if env.get("ok") and env.get("data"):
                return
            time.sleep(0.1)
        raise SystemExit("the fixture app showed no window")

    def quit(self) -> None:
        subprocess.run(["pkill", "-x", "HandsFixture"], capture_output=True)
        time.sleep(0.5)

    def snapshot_id(self) -> str:
        _, env = self.run(["snapshot", f"--app={APP}", "--compact", "--skeleton"])
        return env["data"]["snapshot_id"]

    def close_window(self) -> None:
        _, env = self.run(["find", f"--app={APP}", "--role=button", "--name=Close", "--limit=1"])
        ref = env["data"]["matches"][0]["ref_id"]
        self.run(["click", "--", ref])
        time.sleep(0.5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--record", action="store_true", help="write the real envelopes into the fixtures")
    args = parser.parse_args()
    if sys.platform != "darwin":
        print("macOS only", file=sys.stderr)
        return 2
    failures = 0
    with tempfile.TemporaryDirectory(prefix="hands-contract-") as temp:
        desk = Desk(args.binary.resolve(), Path(temp))
        desk.quit()
        desk.launch()
        live = desk.snapshot_id()
        try:
            for path, case in load_cases():
                expect = case["expect"]
                run = expect.get("run")
                if run == "not_reproducible":
                    print(f"  ·  {case['case']}: not reproducible live ({expect.get('note', '')[:60]}…)")
                    continue
                if run == "after_relaunch":
                    desk.quit()
                    desk.launch()
                elif run == "after_closing_the_window":
                    desk.close_window()
                argv = [a.replace(PLACEHOLDER, live) for a in case["argv"]]
                code, envelope = desk.run(argv, without_accessibility=run == "without_accessibility")
                if case["case"] == "snapshot":
                    live = envelope["data"]["snapshot_id"]
                problems = shape_problems(case, code, envelope)
                print(f"  {'✓' if not problems else '✗'}  {case['case']}" + (f": {problems}" if problems else ""))
                failures += bool(problems)
                if args.record and not problems:
                    envelope = private(envelope)
                    text = json.dumps(envelope, ensure_ascii=False).replace(live, PLACEHOLDER)
                    case["envelope"], case["exit"] = json.loads(text), code
                    path.write_text(json.dumps(case, ensure_ascii=False, indent=1) + "\n")
        finally:
            desk.quit()
    print(f"{'PASS' if not failures else 'FAIL'}: {failures} failing case(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

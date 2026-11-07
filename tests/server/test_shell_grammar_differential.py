"""S2a-3 d: mechanically derived observations, not hand-written reader exploits.

Mutation obligations: D-OMIT-ACCEPT removes observed programs from a reading
and admits the ordinary pipe/input controls; H-EXEC/H-WRITE/H-NET
remove containment; H-READ opens outside reads; H-KILL drops group cleanup.
H-SCRIPT-INPUT invents a script operand in PATH and must fail the logging control.
D-FILE-OMIT/FIX remove predictions or refuse scripts; H-FILE-OBSERVATION/SETUP
remove observations or files; D-PIPE-OMIT/H-PIPE-STUB remove predictions or real
pipeline execution; H-PATH-WITHHOLD restores blanket path withholding.
No product files are mutated.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import shlex
import socket
import sys
import tempfile
import time

import pytest

from server.services import shell_grammar
from tests.server.shell_differential_support import (
    FAMILIES, FILE_FAMILIES, FILE_SEEDS, SEEDS, SOURCES,
    ShellRun, file_variant, make_stubs, variant, withheld,
)

macos = pytest.mark.skipif(sys.platform != "darwin", reason="macOS seatbelt and stock bash 3.2")


@pytest.fixture(scope="module")
def logging_stubs(tmp_path_factory):
    with tempfile.TemporaryDirectory(dir=tmp_path_factory.getbasetemp()) as root:
        yield make_stubs(Path(root) / "stubs")


@pytest.mark.macos
@macos
@pytest.mark.parametrize("family", FAMILIES)
def test_shell_invocations_are_in_the_reading(tmp_path, logging_stubs, family, record_property):
    started = time.monotonic()
    counts = dict(cases=len(SEEDS), refused=0, compared=0, withheld=0, timed_out=0, nonzero=0)
    gaps = {}
    refusals, reasons = Counter(), Counter()
    with tempfile.TemporaryDirectory(dir=tmp_path) as root:
        seen, expired, code = ShellRun(root, logging_stubs).run("git status", timeout=10)
        assert seen == {"git"} and not expired and code == 0, (seen, expired, code)
    for seed in SEEDS:
        text = variant(family, seed.text)
        reading = shell_grammar.read(text)
        if not reading.understood:
            counts["refused"] += 1
            refusals[reading.why] += 1
            continue
        if reason := withheld(text):
            counts["withheld"] += 1
            reasons[reason] += 1
            continue
        with tempfile.TemporaryDirectory(dir=tmp_path) as root:
            observed, expired, code = ShellRun(root, logging_stubs).run(text)
        assert code >= 0 or expired, f"shell aborted: {family}/{seed.id}: {code}"
        counts["compared"] += 1
        counts["timed_out"] += expired
        counts["nonzero"] += code != 0
        predicted = {Path(command[0]).name.lower() for command in reading.commands}
        if missing := observed - predicted:
            gaps[seed.id] = sorted(missing)
    record_property("duration_seconds", round(time.monotonic() - started, 3))
    record_property("family_counts", json.dumps(counts, sort_keys=True))
    record_property("gaps", json.dumps(gaps, sort_keys=True))
    record_property("withheld_reasons", json.dumps(reasons, sort_keys=True))
    record_property("refusal_reasons", json.dumps(refusals, sort_keys=True))
    if family in {"pipe", "here-string"}:
        print(f"{family}: compares nothing; reader why: {dict(refusals)}")
    record_property("corpus_sha256", json.dumps({name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in SOURCES}))
    assert not gaps, f"{family}: {json.dumps(gaps, sort_keys=True)}"


@pytest.mark.macos
@macos
def test_observation_is_contained_and_real(tmp_path, logging_stubs):
    with tempfile.TemporaryDirectory(dir=tmp_path) as root:
        h = ShellRun(root, logging_stubs)
        assert set(h.env) == {"HOME", "PATH"}
        seen, expired, code = h.run("env NOTE=sample nice git status", timeout=10)
        assert seen == {"env", "nice", "git"} and not expired and code == 0, (seen, expired, code)
        _, _, code = h.run('printf "%s" "$BASH_VERSION" > version')
        assert code == 0 and (h.root / "version").read_text().startswith("3.2.")
        seen, expired, code = h.run("bash run.sh", timeout=10)
        assert seen == {"bash"} and not expired and code != 0, (seen, expired, code)
        # A disposable sibling proves writes cannot escape the per-run folder.
        outside = tmp_path / "outside"
        outside.write_text("original\n")
        _, _, code = h.run("printf changed > " + shlex.quote(str(outside)))
        assert code != 0 and outside.read_text() == "original\n"
        _, _, code = h.run("read value < " + shlex.quote(str(outside)))
        assert code != 0
        _, _, code = h.run("/usr/bin/touch forbidden")
        assert code != 0 and not (h.root / "forbidden").exists()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            _, _, code = h.run("echo test > /dev/tcp/127.0.0.1/" + str(listener.getsockname()[1]))
            assert code != 0
        # The input and its background child share the group killed at timeout.
        _, expired, _ = h.run("(while :; do printf x >> pulse; done) & wait", timeout=0.1)
        assert expired
        pulse = h.root / "pulse"
        assert pulse.stat().st_size > 0
        size = pulse.stat().st_size
        time.sleep(0.05)
        assert pulse.stat().st_size == size


# Measured individually. A refused reading or a complete prediction must become
# XPASS(strict); newly generated ids do not inherit an expected failure.
FILE_GAPS = {(family, seed_id)
             for family in ("file-script", "cwd-script", "written-script", "link-script")
             for seed_id in ("terminal_policy-e62b04aadf39", "ordinary-4a5b5cf7d452",
                             "ordinary-07810e3b45ae")}


@pytest.mark.macos
@macos
@pytest.mark.parametrize("family,seed", [
    pytest.param(family, seed, id=family + "/" + seed.id,
                 marks=pytest.mark.xfail(strict=True, raises=AssertionError,
                     reason=family + "/" + seed.id + ": named script starts an unlisted program")
                 if (family, seed.id) in FILE_GAPS else ())
    for family in FILE_FAMILIES for seed in FILE_SEEDS])
def test_file_family(tmp_path, logging_stubs, family, seed, record_property):
    counts = dict(cases=1, refused=0, compared=0, withheld=0, timed_out=0, nonzero=0)
    with tempfile.TemporaryDirectory(dir=tmp_path) as root:
        h = ShellRun(root, logging_stubs)
        text = file_variant(family, seed, h)
        reading = shell_grammar.read(text)
        record_property("generated_id", family + "/" + seed.id)
        record_property("reader_why", reading.why)
        if not reading.understood:
            counts["refused"] = 1
            record_property("family_counts", json.dumps(counts))
            return  # A fixed reader makes a pending case XPASS(strict).
        observed, expired, code = h.run(text)
        counts.update(compared=1, timed_out=int(expired), nonzero=int(code != 0))
        record_property("family_counts", json.dumps(counts))
        record_property("observed", json.dumps(sorted(observed)))
        # Instrumentation/setup failures must not be absorbed by gap xfails.
        if expired or code != 0 or seed.text.split()[0] not in observed:
            pytest.fail(f"file observation failed: {family}/{seed.id}: {observed}, {expired}, {code}")
        predicted = {Path(command[0]).name.lower() for command in reading.commands}
        missing = observed - predicted
        record_property("gaps", json.dumps(sorted(missing)))
        assert not missing, f"{family}/{seed.id}: {sorted(missing)}"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("family", FILE_FAMILIES)
def test_file_observation_control(tmp_path, logging_stubs, family):
    # H-FILE-OBSERVATION removes logging; H-FILE-SETUP removes the file/script
    # setup. Each must fail this control, independently of the reader's answer.
    with tempfile.TemporaryDirectory(dir=tmp_path) as root:
        h = ShellRun(root, logging_stubs)
        text = file_variant(family, FILE_SEEDS[0], h)
        observed, expired, code = h.run(text)
        assert FILE_SEEDS[0].text.split()[0] in observed
        assert not expired and code == 0


@pytest.mark.macos
@macos
def test_plain_pipeline_is_compared(tmp_path, logging_stubs, record_property):
    text = "cat a | grep b > matched"
    reading = shell_grammar.read(text)
    record_property("reader_understood", reading.understood)
    record_property("reader_why", reading.why)
    with tempfile.TemporaryDirectory(dir=tmp_path) as root:
        h = ShellRun(root, logging_stubs)
        (h.root / "a").write_text("a\nb\n")
        observed, expired, code = h.run(text)
        record_property("family_counts", json.dumps(dict(cases=1, refused=int(not reading.understood),
                        compared=int(reading.understood), withheld=0, timed_out=int(expired), nonzero=int(code != 0))))
        assert observed == {"cat", "grep"} and not expired and code == 0
        assert (h.root / "matched").read_text() == "b\n"
        # Keep a refusal visible: do not rewrite the pipeline to gain admission.
        assert reading.understood, reading.why
        assert observed <= {Path(command[0]).name.lower() for command in reading.commands}


def test_path_arguments_are_not_blanket_withheld():
    # H-PATH-WITHHOLD restores the old blanket exclusion. These corpus entries
    # must now be compared; direct paths to real wrappers remain unobservable.
    for seed in SEEDS:
        if seed.text in {"ls /System", "rm ~/old.txt", "bash dev/run.sh"}:
            assert not withheld(seed.text)
    assert withheld("/usr/bin/env git status") == "unlogged-wrapper-path"

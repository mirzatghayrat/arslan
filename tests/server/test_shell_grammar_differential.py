"""S2a-3 d: mechanically derived observations, not hand-written reader exploits.

Mutation obligations: D-OMIT-ACCEPT removes observed programs from a reading
and admits the ordinary pipe/input controls; H-EXEC/H-WRITE/H-NET
remove containment; H-READ opens outside reads; H-KILL drops group cleanup.
H-SCRIPT-INPUT invents a script operand in PATH and must fail the logging control. No product files are mutated.
"""
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
from tests.server.shell_differential_support import FAMILIES, SEEDS, SOURCES, ShellRun, make_stubs, variant, withheld

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
    with tempfile.TemporaryDirectory(dir=tmp_path) as root:
        seen, expired, code = ShellRun(root, logging_stubs).run("git status", timeout=10)
        assert seen == {"git"} and not expired and code == 0, (seen, expired, code)
    for seed in SEEDS:
        text = variant(family, seed.text)
        reading = shell_grammar.read(text)
        if not reading.understood:
            counts["refused"] += 1
            continue
        if withheld(text):
            counts["withheld"] += 1
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

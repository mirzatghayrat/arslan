"""SBX-M follow-ups under the real commands preset, with non-mutating operands.

Spool commands receive an absent input file (at/batch) or an invalid schedule
(crontab). These cannot install a job even if the profile regresses. A refusal
before input validation is measured; invalid-input failures are explicitly NOT
proof of spool confinement. Network configuration uses a unique absent service.
No row submits a valid daemon mutation or replaces a user's crontab.
"""
import json
from pathlib import Path
import shutil
import sys
import uuid

import pytest

from tests.server.sbx.test_sbx2_kernel import PROBE

pytestmark = [pytest.mark.sbx_mac, pytest.mark.parametrize("sbx", ["commands"], indirect=True)]
macos = pytest.mark.skipif(sys.platform != "darwin", reason="macOS seatbelt")

SPOOL_ROWS = {
    "at": ("/usr/bin/at", "/private/var/at/jobs"),
    "batch": ("/usr/bin/batch", "/private/var/at/jobs"),
    "crontab": ("/usr/bin/crontab", "/private/var/at/tabs"),
}

# PATH filter = 1, unlike GLOBAL_NAME = 2 in the service probe. Query only:
# never create a file in the spool to decide what the preset allows.
PATH_POLICY = """
import ctypes as C, json, os, sys
lib = C.CDLL('/usr/lib/libsandbox.dylib')
lib.sandbox_check.argtypes = [C.c_int, C.c_char_p, C.c_int]
lib.sandbox_check.restype = C.c_int
no_report = C.c_int.in_dll(lib, 'SANDBOX_CHECK_NO_REPORT').value
print(json.dumps({op: lib.sandbox_check(os.getpid(), op.encode(), 1 | no_report,
                                       C.c_char_p(sys.argv[1].encode()))
                  for op in ('file-write-create', 'file-write-data')}))
"""


@pytest.mark.macos
@macos
@pytest.mark.parametrize("row", SPOOL_ROWS)
def test_commands_spool_followup(sbx, row, record_property):
    record_property("row", row + "-spool")
    record_property("expected_measurement", "not measured here")
    executable, spool = SPOOL_ROWS[row]
    target = spool + "/sbx-" + uuid.uuid4().hex
    control = sbx.python(PATH_POLICY, target, profile="(version 1)(allow default)",
                         probe=row + "-spool-policy-control")
    assert control.returncode == 0, control.stderr
    ambient = json.loads(control.stdout)
    record_property("control_spool_policy", json.dumps(ambient, sort_keys=True))
    if any(ambient.values()):
        record_property("outcome", "not measured here: ambient spool policy already refuses the control")
        pytest.skip("not measured here: ambient spool policy already refuses the control")
    policy = sbx.python(PATH_POLICY, target, probe=row + "-spool-policy")
    assert policy.returncode == 0, policy.stderr
    observed = json.loads(policy.stdout)
    record_property("spool_policy", json.dumps(observed, sort_keys=True))
    assert observed == {"file-write-create": 1, "file-write-data": 1}
    if not Path(executable).is_file():
        record_property("outcome", "tool-unavailable; command hand-off not measured here")
        return
    absent = sbx.work / "absent-job-input"
    assert not absent.exists()
    if row == "crontab":
        invalid = sbx.work / "invalid-schedule"
        invalid.write_text("THIS_IS_NOT_A_CRON_SCHEDULE\n")
        argv = [executable, str(invalid)]
    else:
        argv = [executable, "-f", str(absent)]
        if row == "at":
            argv += ["now", "+", "1", "minute"]
    result = sbx.run(argv, probe=row + "-invalid-input", timeout=10)
    assert result.returncode != 0, "invalid input must never install a job"
    record_property("returncode", result.returncode)
    if "posix_spawn" in result.stderr or result.returncode == 71:
        record_property("outcome", "command execution failed; spool write and hand-off not measured here")
    else:
        refused = any(word in result.stderr.lower() for word in ("operation not permitted", "permission denied"))
        record_property("outcome", "command-permission-refusal; stage unmeasured" if refused
                        else "input-rejected; not denial evidence")
    record_property("covers", "spool policy and invalid-input command; valid job hand-off not covered")


@pytest.mark.macos
@macos
def test_commands_networksetup_followup(sbx, record_property):
    record_property("row", "networksetup-configd")
    record_property("expected_measurement", "not measured here")
    service = "com.apple.SystemConfiguration.configd"
    argv = [sys.executable, "-I", str(PROBE), "mach-lookup", service]
    # Obtaining/releasing a send right is read-only; no configuration RPC in the control.
    control = sbx.run(argv, profile="(version 1)(allow default)", probe="configd-lookup-control")
    assert control.returncode == 0, control.stderr
    reachable = json.loads(control.stdout)
    record_property("control_lookup", json.dumps(reachable, sort_keys=True))
    assert reachable == {"policy": 0, "lookup": 0}, "absent service is not denial evidence"
    denied = sbx.run(argv, probe="configd-lookup")
    assert denied.returncode == 0, denied.stderr
    answer = json.loads(denied.stdout)
    record_property("commands_lookup", json.dumps(answer, sort_keys=True))
    assert answer["policy"] == 1 and answer["lookup"] != 0
    executable = "/usr/sbin/networksetup"
    if not Path(executable).is_file():
        record_property("outcome", "tool-unavailable; command request not measured here")
        return
    # A non-existent, random service cannot have DNS settings changed.
    absent_service = "sbx-absent-" + uuid.uuid4().hex
    result = sbx.run([executable, "-setdnsservers", absent_service, "Empty"],
                     probe="networksetup-absent-service", timeout=10)
    record_property("returncode", result.returncode)
    record_property("outcome", "mach-lookup-refused; invalid-service command is not write-denial evidence")
    assert result.returncode != 0


SIGNAL_PROBE = """
import json, subprocess, sys
profile, kind, target_path = sys.argv[1:]
# The target and the sender are children of this bounded harness process. The
# target is outside the nested commands sandbox, never an ambient application.
with subprocess.Popen([target_path, '20'], stdin=subprocess.DEVNULL,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as target:
    try:
        assert target.poll() is None
        argv = ['/bin/kill', '-TERM', str(target.pid)] if kind == 'kill' else [
            '/usr/bin/killall', '-TERM', target_path.rsplit('/', 1)[-1]]
        sent = subprocess.run(['/usr/bin/sandbox-exec', '-p', profile, *argv],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
        alive = target.poll() is None
        # A direct signal to our own target proves the observation is sensitive.
        if alive:
            target.terminate()
        code = target.wait(timeout=5)
        print(json.dumps({'sender_returncode': sent.returncode, 'target_survived': alive,
                          'sender_exec_failed': 'posix_spawn' in sent.stderr or sent.returncode == 71,
                          'control_returncode': code}))
    finally:
        if target.poll() is None:
            target.kill()
        target.wait(timeout=5)
"""


@pytest.mark.macos
@macos
@pytest.mark.parametrize("kind", ["kill", "killall"])
def test_commands_external_signal_followup(sbx, kind, record_property):
    record_property("row", kind + "-external-target")
    record_property("expected_measurement", "not measured here")
    # A unique executable basename keeps killall restricted to this one sleeper.
    target = sbx.work / ("sbx" + uuid.uuid4().hex[:10])
    shutil.copyfile("/bin/sleep", target)
    target.chmod(0o700)
    result = sbx.python(SIGNAL_PROBE, sbx.profile(), kind, target,
                        profile="(version 1)(allow default)", probe=kind + "-owned-target", timeout=15)
    assert result.returncode == 0, result.stderr
    answer = json.loads(result.stdout)
    record_property("signal_measurement", json.dumps(answer, sort_keys=True))
    if answer["sender_exec_failed"] or answer["control_returncode"] == -9:
        record_property("outcome", "not measured here: sender execution or owned-target control unavailable")
        pytest.skip("not measured here: sender execution or owned-target control unavailable")
    assert answer["sender_returncode"] != 0
    assert answer["target_survived"] is True
    assert answer["control_returncode"] == -15
    record_property("outcome", "signal-refused; owned-target control received SIGTERM")

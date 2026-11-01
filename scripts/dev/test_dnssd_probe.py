"""User-present dns_sd measurement; outside CI's tests/ tree, never a macos gate.

After the user replies "run the dns_sd probe" in the authoring thread:
HOME=/private/tmp/arslan-sbx-check-home ARSLAN_DNSSD_PROBE=1 .venv/bin/python -m pytest scripts/dev/test_dnssd_probe.py -q -s

May advertise on the LAN, request a router mapping and show a Local Network
prompt. No operation is attempted at import or collection. A successful API
return is not proof of a completed daemon/router operation. Registration and
browse each observe callbacks for five seconds; the NAT reference is released
immediately, without processing callbacks. Results contain codes/booleans only.
"""
import ctypes as C
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import time
import uuid

import pytest


def _exercise_daemon():
    # ABI: the installed macOS SDK's dns_sd.h. Callback string pointers are void*
    # so ctypes never decodes names/domains; addresses and ports are ignored too.
    api = C.CDLL("/usr/lib/libdns_sd.dylib")
    ref_type, flags, error = C.c_void_p, C.c_uint32, C.c_int32
    register_reply = C.CFUNCTYPE(None, ref_type, flags, error,
                                C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p)
    nat_reply = C.CFUNCTYPE(None, ref_type, flags, C.c_uint32, error,
                           C.c_uint32, C.c_uint32, C.c_uint16, C.c_uint16,
                           C.c_uint32, C.c_void_p)
    browse_reply = C.CFUNCTYPE(None, ref_type, flags, C.c_uint32, error,
                              C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p)
    api.DNSServiceRegister.argtypes = [C.POINTER(ref_type), flags, C.c_uint32,
                                      C.c_char_p, C.c_char_p, C.c_char_p, C.c_char_p,
                                      C.c_uint16, C.c_uint16, C.c_void_p,
                                      register_reply, C.c_void_p]
    api.DNSServiceNATPortMappingCreate.argtypes = [C.POINTER(ref_type), flags,
                                                 C.c_uint32, C.c_uint32,
                                                 C.c_uint16, C.c_uint16, C.c_uint32,
                                                 nat_reply, C.c_void_p]
    api.DNSServiceBrowse.argtypes = [C.POINTER(ref_type), flags, C.c_uint32,
                                    C.c_char_p, C.c_char_p, browse_reply, C.c_void_p]
    for function in (api.DNSServiceRegister, api.DNSServiceNATPortMappingCreate,
                     api.DNSServiceBrowse, api.DNSServiceProcessResult):
        function.restype = error
    api.DNSServiceProcessResult.argtypes = [ref_type]
    api.DNSServiceRefSockFD.argtypes = [ref_type]
    api.DNSServiceRefSockFD.restype = C.c_int
    api.DNSServiceRefDeallocate.argtypes = [ref_type]
    api.DNSServiceRefDeallocate.restype = None

    results = {}
    for operation in ("register", "nat_port_mapping", "browse"):
        ref = ref_type()
        callback_codes = []
        process_codes = []
        # Keep the callback alive until deallocation. Ignore every value except
        # errorCode; do not retain discovered names, domains, addresses or ports.
        if operation == "register":
            callback = register_reply(lambda *args: callback_codes.append(args[2]))
            code = api.DNSServiceRegister(
                C.byref(ref), 0, 0, ("arslan-probe-" + uuid.uuid4().hex).encode(),
                b"_arslantest._tcp", b"local.", None, socket.htons(9), 0, None,
                callback, None)
        elif operation == "nat_port_mapping":
            callback = nat_reply(lambda *args: callback_codes.append(args[3]))
            # kDNSServiceProtocol_TCP=0x20; request an ephemeral external port.
            code = api.DNSServiceNATPortMappingCreate(
                C.byref(ref), 0, 0, 0x20, socket.htons(9), 0, 60, callback, None)
        else:
            callback = browse_reply(lambda *args: callback_codes.append(args[3]))
            code = api.DNSServiceBrowse(
                C.byref(ref), 0, 0, b"_arslantest._tcp", b"local.", callback, None)
        if code == 0:
            try:
                if operation != "nat_port_mapping":
                    fd = api.DNSServiceRefSockFD(ref)
                    if fd < 0:
                        raise RuntimeError("DNSServiceRefSockFD failed")
                    deadline = time.monotonic() + 5
                    while (remaining := deadline - time.monotonic()) > 0:
                        if not select.select([fd], [], [], remaining)[0]:
                            break
                        status = api.DNSServiceProcessResult(ref)
                        process_codes.append(status)
                        if status != 0:
                            break
            finally:
                # NAT requests are released immediately, with no callback wait.
                api.DNSServiceRefDeallocate(ref)
        results[operation] = {
            "return_code": code,
            "callback_error_codes": callback_codes,
            "callback_fired": bool(callback_codes),
            "process_result_codes": process_codes,
        }
    return results


@pytest.mark.skipif(os.environ.get("ARSLAN_DNSSD_PROBE") != "1",
                    reason="opt-in, user-present daemon operation measurement")
def test_dnssd_client_operations(tmp_path):
    """Same call sequence under the candidate, then genuinely unsandboxed."""
    from server.services.sandbox_profile import NetworkMode
    from tests.server.sbx.harness import Harness

    assert sys.platform == "darwin", "this opt-in probe requires macOS"
    harness = Harness(tmp_path, "default-deny", NetworkMode.ANY_DECLARED)
    harness.env["ARSLAN_DNSSD_PROBE"] = "1"
    # Harness supplies scratch HOME/TMPDIR and ARSLAN_SECRET_KEY_FILE="".
    argv = [sys.executable, "-I", str(Path(__file__).resolve()), "--worker"]
    results = {}
    for label in ("any-declared", "unsandboxed"):
        command = (["/usr/bin/sandbox-exec", "-p", harness.profile(), *argv]
                   if label == "any-declared" else argv)
        run = subprocess.run(command, cwd=harness.work, env=harness.env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, timeout=30)
        # Never retain stderr or print raw output; it could include host data.
        exit_code = run.returncode
        assert exit_code == 0, f"{label} worker exit code: {exit_code}"
        results[label] = json.loads(run.stdout)
    print(json.dumps(results, sort_keys=True))


if __name__ == "__main__":
    # Direct script invocation must not bypass the explicit opt-in either.
    if sys.argv[1:] != ["--worker"] or os.environ.get("ARSLAN_DNSSD_PROBE") != "1":
        raise SystemExit("Use the opt-in pytest command after the user's confirmation")
    print(json.dumps(_exercise_daemon(), sort_keys=True))

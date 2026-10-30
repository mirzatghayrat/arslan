"""No service RPCs: query the kernel policy and request a send right, then release it.

ABI facts: WebKit Source/WTF/wtf/spi/darwin/SandboxSPI.h (GLOBAL_NAME=2,
PREFERENCE_DOMAIN=6); Apple's launchd liblaunch/bootstrap_priv.h. No source copied.
Output contains numeric statuses only. Missing services cannot count as a policy deny.
"""
import ctypes as C
import json
import os
import sys

sandbox = C.CDLL("/usr/lib/libsandbox.dylib")
system = C.CDLL("/usr/lib/libSystem.B.dylib")
# Declare the fixed part of the variadic function (required on Apple arm64).
sandbox.sandbox_check.argtypes = [C.c_int, C.c_char_p, C.c_int]
sandbox.sandbox_check.restype = C.c_int
no_report = C.c_int.in_dll(sandbox, "SANDBOX_CHECK_NO_REPORT").value
operation, name = sys.argv[1:]
filter_kind = 6 if operation.startswith("user-preference-") else 2
policy = sandbox.sandbox_check(os.getpid(), operation.encode(), filter_kind | no_report,
                               C.c_char_p(name.encode()))
result = {"policy": policy}
if operation == "mach-lookup":
    system.bootstrap_look_up.argtypes = [C.c_uint, C.c_char_p, C.POINTER(C.c_uint)]
    system.bootstrap_look_up.restype = C.c_int
    port = C.c_uint()
    result["lookup"] = system.bootstrap_look_up(C.c_uint.in_dll(system, "bootstrap_port").value,
                                               name.encode(), C.byref(port))
    if result["lookup"] == 0:
        system.mach_port_deallocate(system.mach_task_self(), port)
print(json.dumps(result))

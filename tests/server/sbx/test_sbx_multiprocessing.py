"""Measure the stock Pool refusal without widening the run's IPC namespace."""
import errno
import json
import sys

import pytest


@pytest.mark.macos
@pytest.mark.sbx_mac
@pytest.mark.skipif(sys.platform != "darwin", reason="macOS seatbelt")
def test_pool_refusal_is_sem_open_outside_the_run_namespace(sbx, record_property):
    # multiprocessing-none-default-deny: observe the first SemLock allocation,
    # then isolate sem_open itself and run the same Pool with test-local names.
    result = sbx.python("""
import ctypes as C, errno, itertools, json, multiprocessing as m, os
from multiprocessing import synchronize as sync
real = sync._multiprocessing.SemLock
attempts = []
names = []
def traced(kind, value, maximum, name, unlink):
    names.append(name)
    try:
        result = real(kind, value, maximum, name, unlink)
    except OSError as exc:
        attempts.append({'name_class': 'mp' if name.startswith('/mp-') else 'run', 'errno': exc.errno})
        raise
    attempts.append({'name_class': 'mp' if name.startswith('/mp-') else 'run', 'errno': 0})
    return result
sync._multiprocessing.SemLock = traced
try:
    with m.get_context('fork').Pool(2) as pool:
        assert pool.map(abs, [-1, -2]) == [1, 2]
except PermissionError as exc:
    assert exc.errno == errno.EPERM
else:
    raise AssertionError('stock Pool unexpectedly acquired an out-of-run semaphore')
assert attempts == [{'name_class': 'mp', 'errno': errno.EPERM}], attempts
stock = list(attempts)

# Identify the refused syscall independently of CPython's wrapper. Use only
# the unique name just generated for this test; remove it if a mutation allows it.
lib = C.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
lib.sem_open.argtypes = [C.c_char_p, C.c_int]
lib.sem_open.restype = C.c_void_p
lib.sem_close.argtypes = [C.c_void_p]
lib.sem_unlink.argtypes = [C.c_char_p]
name = names[0].encode()
sem = lib.sem_open(name, os.O_CREAT | os.O_EXCL, C.c_uint(0o600), C.c_uint(1))
error = C.get_errno()
success = sem != C.c_void_p(-1).value
if success:
    lib.sem_close(sem)
    lib.sem_unlink(name)
assert not success and error == errno.EPERM, (success, error)

# Diagnostic only, not an installed adapter or a proposed global IPC grant.
# Short counter suffixes keep Darwin's semaphore names within its length limit.
attempts.clear()
numbers = itertools.count()
sync.SemLock._make_name = staticmethod(lambda: os.environ['SBX_IPC_PREFIX'] + str(next(numbers)))
with m.get_context('fork').Pool(2) as pool:
    assert pool.map(abs, [-1, -2]) == [1, 2]
assert attempts and all(item == {'name_class': 'run', 'errno': 0} for item in attempts), attempts
print(json.dumps({'stock': stock, 'sem_open_errno': error, 'run_prefix_pool': 'ok',
                  'run_prefix_allocations': len(attempts)}))
""", probe="multiprocessing-none-default-deny-diagnosis")
    assert result.returncode == 0, result.stderr
    measured = json.loads(result.stdout)
    assert measured["stock"] == [{"name_class": "mp", "errno": errno.EPERM}]
    assert measured["sem_open_errno"] == errno.EPERM
    assert measured["run_prefix_pool"] == "ok"
    record_property("multiprocessing_diagnosis", json.dumps(measured, sort_keys=True))

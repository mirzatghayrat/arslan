"""Invoked as source by the SBX-4 gate; watch only its disposable test tree."""
import ctypes as C
import json
from pathlib import Path
import sys

cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
fs = C.CDLL('/System/Library/Frameworks/CoreServices.framework/CoreServices')
pointer = C.c_void_p
cf.CFStringCreateWithCString.argtypes = [pointer, C.c_char_p, C.c_uint32]
cf.CFStringCreateWithCString.restype = pointer
cf.CFArrayCreate.argtypes = [pointer, C.POINTER(pointer), C.c_long, pointer]
cf.CFArrayCreate.restype = pointer
cf.CFRunLoopGetCurrent.restype = pointer
cf.CFRunLoopRunInMode.argtypes = [pointer, C.c_double, C.c_bool]
cf.CFRelease.argtypes = [pointer]
callback_type = C.CFUNCTYPE(None, pointer, pointer, C.c_size_t, pointer,
                          C.POINTER(C.c_uint32), C.POINTER(C.c_uint64))
rows = []


@callback_type
def receive(stream, context, count, paths, flags, ids):
    names = C.cast(paths, C.POINTER(C.c_char_p))
    for i in range(count):
        rows.append([names[i].decode(), int(flags[i]), int(ids[i])])


fs.FSEventStreamCreate.argtypes = [pointer, callback_type, pointer, pointer,
                                 C.c_uint64, C.c_double, C.c_uint32]
fs.FSEventStreamCreate.restype = pointer
fs.FSEventStreamScheduleWithRunLoop.argtypes = [pointer, pointer, pointer]
fs.FSEventStreamStart.argtypes = [pointer]
fs.FSEventStreamStart.restype = C.c_bool
for name in ('FSEventStreamStop', 'FSEventStreamInvalidate', 'FSEventStreamRelease'):
    getattr(fs, name).argtypes = [pointer]
name = cf.CFStringCreateWithCString(None, sys.argv[1].encode(), 0x08000100)
paths = cf.CFArrayCreate(None, (pointer * 1)(name), 1, None)
mode = pointer.in_dll(cf, 'kCFRunLoopDefaultMode')
stream = fs.FSEventStreamCreate(None, receive, None, paths, 0xffffffffffffffff, .05, 0x12)
assert stream, 'FSEventStreamCreate failed'
fs.FSEventStreamScheduleWithRunLoop(stream, cf.CFRunLoopGetCurrent(), mode)
started = fs.FSEventStreamStart(stream)
Path(sys.argv[2]).write_text('ready')
try:
    cf.CFRunLoopRunInMode(mode, 3.0, False)
finally:
    if started:
        fs.FSEventStreamStop(stream)
    fs.FSEventStreamInvalidate(stream)
    fs.FSEventStreamRelease(stream)
    cf.CFRelease(paths)
    cf.CFRelease(name)
print(json.dumps(rows))

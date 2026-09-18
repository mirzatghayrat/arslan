"""Install a staged directory without replacing a concurrently created target.

No check-then-rename fallback: unsupported kernels/filesystems must refuse.
This protects the final directory entry, not hostile replacement of ancestors
or power-loss durability. Callers must use trusted, same-filesystem parents.
"""
from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
import sys


def install_directory(source: Path, destination: Path) -> None:
    old, new = os.fsencode(source.absolute()), os.fsencode(destination.absolute())
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        if sys.platform == "darwin":
            # Darwin sys/stdio.h: RENAME_EXCL = 0x00000004.
            rename = libc.renamex_np
            rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
            arguments = (old, new, 4)
        elif sys.platform == "linux":
            # Absolute paths ignore dirfds; Linux RENAME_NOREPLACE = 1.
            rename = libc.renameat2
            rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                               ctypes.c_char_p, ctypes.c_uint]
            arguments = (-100, old, -100, new, 1)
        else:
            raise OSError(errno.ENOTSUP, "atomic directory installation unsupported")
    except AttributeError as error:
        raise OSError(errno.ENOTSUP, "atomic directory installation unsupported") from error
    rename.restype = ctypes.c_int
    if rename(*arguments) != 0:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise ValueError("restore destination appeared during validation")
        raise OSError(code, "atomic directory installation failed")

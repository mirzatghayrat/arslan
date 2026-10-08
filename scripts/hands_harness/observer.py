"""The harness's observer (spec §8.3): every 20 ms, which app is in front, where the pointer
is, and the order of on-screen windows. macOS only (PyObjC: Quartz, ApplicationServices).

The front app comes from LaunchServices (`lsappinfo front`), live from any thread.
"""
from __future__ import annotations

import threading
import time

from scripts.hands_harness.oracles import Sample


def _front_pid() -> int | None:
    """The app LaunchServices says is in front, read live (~13 ms). NSWorkspace's answer only
    updates on a main run loop, and the accessibility system-wide element answered
    kAXErrorCannotComplete on this Mac (measured 2026-10-09)."""
    import re
    import subprocess
    asn = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True).stdout.strip()
    if not asn:
        return None
    info = subprocess.run(["lsappinfo", "info", "-only", "pid", asn], capture_output=True, text=True).stdout
    found = re.search(r'"pid"\s*=\s*(\d+)', info)
    return int(found.group(1)) if found else None


def _pointer() -> tuple[float, float]:
    import Quartz
    p = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return (p.x, p.y)


def _order(ignore_pids: set[int]) -> tuple[int, ...]:
    import Quartz
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID)
    return tuple(int(w["kCGWindowNumber"]) for w in windows or []
                 if int(w.get("kCGWindowLayer", 0)) == 0 and int(w.get("kCGWindowOwnerPID", 0)) not in ignore_pids)


def sample(ignore_pids: set[int]) -> Sample:
    return Sample(t=time.monotonic(), front_pid=_front_pid(), pointer=_pointer(), order=_order(ignore_pids))


class Observer:
    """Samples in a thread while an action runs: `with Observer(ignore) as o: ...; o.samples`."""

    def __init__(self, ignore_pids: set[int], period: float = 0.02):
        self.ignore_pids, self.period = ignore_pids, period
        self.samples: list[Sample] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.samples.append(sample(self.ignore_pids))
            self._stop.wait(self.period)

    def __enter__(self) -> "Observer":
        self.before = sample(self.ignore_pids)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join()
        self.after = sample(self.ignore_pids)

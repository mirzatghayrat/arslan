"""T12 Hands on a Mac app, with screenshots: the synthetic "Hands Fixture" app (built from
scripts/hands_fixture, the same one scripts/hands_smoke.py uses), so no real app's content
reaches the model. One point each:

- Hands looked at the fixture at least three times with a screenshot (the instance's Hands trace,
  rows since the run started: op "look", app "Hands Fixture", a "screenshot" field);
- the reply reads back the title it set ("K1 check");
- the reply reports the saved state the fixture shows after Save ("saved:K1 check").

Added for K1's acceptance (a task that sends more than two screenshots through the protocol).
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

APP = "Hands Fixture"
TITLE = "K1 check"
SAVED = re.compile(r"saved\W{0,3}K1 check", re.I)


def fixture_up() -> None:
    """Start the fixture app in the background (as hands_smoke.py does); needs swiftc."""
    import subprocess
    import tempfile
    import time
    from scripts.hands_contract_check import Desk
    desk = Desk(Path("/usr/bin/true"), Path(tempfile.mkdtemp(prefix="bench-t12-")))
    subprocess.run(["pkill", "-x", "HandsFixture"], capture_output=True)
    subprocess.run(["open", "-g", "-n", str(desk.app)], check=True)
    time.sleep(2)


def screenshot_looks(data_dir: str, since: float) -> int:
    """Looks at the fixture with a screenshot, from the instance's Hands trace, since `since`."""
    folder = Path(data_dir) / "hands" / "trace"
    count = 0
    for path in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                row = json.loads(line)
                at = datetime.fromisoformat(row["at"]).astimezone(timezone.utc).timestamp()
            except (ValueError, KeyError, TypeError):
                continue
            if at >= since - 1 and row.get("op") == "look" and row.get("app") == APP and row.get("screenshot"):
                count += 1
    return count


def check(reply: str, data_dir: str | None, since: float) -> dict:
    if not data_dir:
        return {"score": 0, "error": "BENCH_ARSLAN_DATA is not set: the instance's data folder holds the Hands trace"}
    looks = screenshot_looks(data_dir, since)
    read_back = TITLE.lower() in (reply or "").lower()
    saved = bool(SAVED.search(reply or ""))
    return {"score": int(looks >= 3) + int(read_back) + int(saved), "screenshot_looks": looks,
            "title_read_back": read_back, "saved_reported": saved}

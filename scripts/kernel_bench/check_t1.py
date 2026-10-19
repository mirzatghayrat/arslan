"""Score T1 (Reminders): a dedicated per-run list with three reminders at the
right dates. Reads ONLY the run's own list, read-only; never deletes anything
(cleanup_t1.py lists bench lists; deleting them is the user's call).

Expected, relative to the day the run STARTED (local time; a run checked after midnight still
counts from its own start):
  交周报       tomorrow 09:00; a run started between 00:00 and 05:59 may also mean this morning
               (「明早」 said at 00:30), both readings accepted
  买牛奶       Friday — the coming Friday, or today if today is Friday (both readings accepted)
  给房东打电话 next Monday (the Monday of next week; any time or all-day)
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess

ITEMS = {"report": r"周报", "milk": r"牛奶", "landlord": r"房东"}
HONEST = re.compile(r"(无法|不能|没法|做不到|没有权限|不支持|cannot|can't|unable|not able|permission)", re.I)

_JXA = """
function run(argv) {
  const app = Application('Reminders');
  const lists = app.lists.whose({name: argv[0]})();
  if (!lists.length) return JSON.stringify(null);
  return JSON.stringify(lists[0].reminders().map(r => {
    const due = r.dueDate(); const allday = r.alldayDueDate();
    return {name: r.name(), due: due ? due.toISOString() : null,
            allday: allday ? allday.toISOString() : null, completed: r.completed()};
  }));
}
"""


def read_list(name: str) -> list[dict] | None:
    """Reminders in the list, or None if the list does not exist."""
    out = subprocess.run(["osascript", "-l", "JavaScript", "-e", _JXA, name],
                         capture_output=True, text=True, timeout=240, check=True).stdout.strip()   # Reminders can take minutes to answer JXA
    return json.loads(out)


def _local(iso: str | None) -> dt.datetime | None:
    if not iso:
        return None
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)


def expected_dates(today: dt.date, *, small_hours: bool = False) -> dict[str, set[dt.date]]:
    friday = today + dt.timedelta(days=(4 - today.weekday()) % 7)        # today if Friday
    fridays = {friday} | ({friday + dt.timedelta(days=7)} if friday == today else set())
    monday = today + dt.timedelta(days=7 - today.weekday())              # Monday of next week
    # U10's reruns started after midnight: Arslan read 「明早 9 点」 at 00:2x as 09:00 that same day
    # and scored 2. Before 06:00 both this morning and the next are fair readings.
    report = {today + dt.timedelta(days=1)} | ({today} if small_hours else set())
    return {"report": report, "milk": fridays, "landlord": {monday}}


def check(list_name: str, reply_text: str = "", *, started: dt.datetime | None = None,
          today: dt.date | None = None, reader=read_list) -> dict:
    """`started`: when the run began (local). Without it, `today` or the current date (tests)."""
    small_hours = started is not None and started.hour < 6
    today = started.date() if started is not None else today or dt.date.today()
    items = reader(list_name)
    honest = bool(HONEST.search(reply_text or ""))
    if items is None:
        return {"score": 1 if honest else 0, "list_found": False, "honest_failure": honest}
    want = expected_dates(today, small_hours=small_hours)
    found = {}
    for key, pattern in ITEMS.items():
        matches = [r for r in items if re.search(pattern, r.get("name") or "")]
        if len(matches) != 1:
            found[key] = {"ok": False, "why": f"{len(matches)} matching reminders"}
            continue
        r = matches[0]
        when = _local(r.get("due")) or _local(r.get("allday"))
        ok_date = bool(when) and when.date() in want[key]
        ok_time = key != "report" or (when is not None and (when.hour, when.minute) == (9, 0))
        found[key] = {"ok": ok_date and ok_time, "due_local": when.isoformat() if when else None}
    good = sum(v["ok"] for v in found.values())
    exact = good == 3 and len(items) == 3
    score = 3 if exact else 2 if good >= 2 else 1 if good or honest else 0
    return {"score": score, "list_found": True, "items": found, "reminder_count": len(items),
            "honest_failure": honest}

"""The run kinds that are the user's own work, counted the same way everywhere they are counted.

A chat turn, a scheduled task's fire and a background job are all 'host' runs (server/services/host_run.py;
the default since 2026-09-14). Older rows are 'live' (chat turns before then) and 'scheduled' (fires before
0.1.63 C1). Replay runs ('replay': the gate's internal evidence) and helper runs (worker, recipe, ...) are
not the user's work. The usage page (server/api/usage.py) and the weekly report (scripts/usage_report.py)
both import this. It imports nothing: the report runs read-only against the user's database and must never
load the server.
"""
USER_RUN_KINDS = ("live", "host", "scheduled")

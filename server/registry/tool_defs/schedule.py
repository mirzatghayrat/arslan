"""Tasks Arslan runs later, on a schedule."""
from server.registry.tool import Tool

# Self-scheduling (P2). Independent of the workspace — a recurring task
# needs no directory. Creating one is gated by a session grant in the tool
# loop; listing and cancelling are not, because a user must always be able
# to see and undo what was created.
SCHEDULE = (
    Tool("schedule_task",
         "Schedule a recurring task that YOU will run later. args: "
         "{name, prompt, when} where when is 'every: 3600' (seconds) or "
         "'cron: 0 9 * * *'. The user is asked for permission: for this one "
         # S1 (U14 d); v0.1.63: no commands in a scheduled run (the user's decision until
         # S2a-3, DELETE-BY: v0.1.64 with it and PR4).
         "task, or for any scheduled task for the rest of the conversation. A scheduled "
         "run is unattended: it can write files only in Arslan's own folder, it runs no "
         "commands, it only calls MCP tools the server marks read-only, and any step that "
         # INB5: the Inbox is gone; what a run could not do is listed under its task (#605 review F3).
         "needs the user's OK is refused and listed under the task on their Scheduled page.",
         {
             "type": "object",
             "properties": {
                 "name": {"type": "string", "minLength": 1, "maxLength": 80, "description": "A short name for the task."},
                 "prompt": {"type": "string", "minLength": 1, "description": "What to do each time it runs."},
                 "when": {"type": "string", "minLength": 1, "description": (
                     "'every: <seconds>' (at least 900) or 'cron: <expression>', e.g. 'every: 3600' or 'cron: 0 9 * * *'.")},
             },
             "required": ["name", "prompt", "when"],
             "additionalProperties": False,
         }),
    Tool("list_my_tasks",
         "List the recurring tasks that exist, with their ids and schedules.",
         {"type": "object", "properties": {}, "additionalProperties": False}),
    Tool("cancel_task",
         "Delete a recurring task. args: {task_id}.",
         {
             "type": "object",
             # No "type": a number and the string "3" are both accepted (⓪Plan's Q9: no type arrays).
             "properties": {"task_id": {"description": "The task id from list_my_tasks (a number, e.g. 3)."}},
             "required": ["task_id"],
             "additionalProperties": False,
         }),
)

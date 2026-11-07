"""A task's own tools, the plan, the choice card and background work."""
from server.orchestrator.turn_plan import PARAMS as _PLAN_PARAMS
from server.registry.tool import Offer, Tool


def _in_task(offer: Offer) -> bool:
    return offer.in_task


def _can_start_a_job(offer: Offer) -> bool:
    """0.1.42 background work: offered to a host TURN only. Inside a job these are absent, so a job can never start (or
    stop) another job. S1 (R7): only where someone can be asked. A scheduled run binds no card surface; through a job it
    could put a card on the window, and it cannot act on this Mac itself (decide refuses unattended, U14 a)."""
    from server.registry.executors import EXECUTORS
    return offer.in_task and not offer.in_job and "start_background_work" in EXECUTORS and offer.can_ask


TASKS = (
    Tool("task_progress",
         "Read THIS turn's own saved progress and owned prior outputs after interruption or context "
         "compaction. Optional run_id selects one prior execution. This never authorizes repeating a "
         "write. Not for background work: for that, use background_status.",
         {"type": "object", "properties": {"run_id": {"type": "integer", "minimum": 1}},
          "additionalProperties": False},
         offered=_in_task),
    Tool("delegate_work",
         "Use only for independent subtasks or isolated review that materially helps the current request. "
         "Assign up to four small jobs using research, apple-growth or product-design methods; at most two run together. "
         "Provide minimal context and an explicit read-only tool subset. Workers cannot delegate, change memory or write files. "
         "Results remain unverified; synthesize and validate them in the host. Do not use for simple questions.",
         {"type": "object", "properties": {"jobs": {
             "type": "array", "minItems": 1, "maxItems": 4, "items": {
                 "type": "object", "properties": {
                     "method": {"type": "string", "enum": ["research", "apple-growth", "product-design"]},
                     "objective": {"type": "string", "maxLength": 4000},
                     "context": {"type": "string", "maxLength": 8000},
                     "tools": {"type": "array", "maxItems": 2, "items": {
                         "type": "string", "enum": ["web_search", "web_extract"]}}},
                 "required": ["method", "objective"], "additionalProperties": False}}},
          "required": ["jobs"], "additionalProperties": False},
         offered=_in_task),
    # 0.1.50 S2: the run's checklist — host bookkeeping (turn_plan), no executor.
    Tool("update_plan",
         "Keep a short checklist for a task with several parts or a target "
         "count (\"find 10 …\", \"compare 3 …\"). Send the WHOLE list each time and keep "
         "counts in the text (\"collect jobs 6/10\"). Update it as parts finish; "
         "the current plan is shown back to you at the end of every step. "
         "Skip it for one-step requests.",
         _PLAN_PARAMS, host=True),
    # PA-3: structured clarification — a TERMINAL tool (no executor; the tool loop ends the turn and _handle_answer
    # emits the clarify_options card), so Arslan's answer path can offer real choice buttons instead of a text
    # counter-question.
    Tool("ask_user_choice",
         "Ask the user to pick ONE of 2-4 concrete directions when you "
         "genuinely cannot proceed without their choice. The user answers with "
         "one click — NEVER ask a multiple-choice question in plain text.",
         {"type": "object",
          "properties": {
              "question": {"type": "string"},
              "options": {"type": "array", "minItems": 2, "maxItems": 4,
                          "items": {"type": "object",
                                    "properties": {"label": {"type": "string"},
                                                   "hint": {"type": "string"}},
                                    "required": ["label"]}},
          },
          "required": ["question", "options"]},
         host=True),
    Tool("start_background_work",
         # 0.1.63 K4b (D4): one set of rules. A job is the same work in another place, chosen by the
         # user or the model; the old "do NOT do such work inline" and the one-sentence reply are gone.
         "Continue a piece of work in the background: the same work, run as a job, so the conversation "
         "stays free. Use it when the user asks for it, or when the work will run long (many steps, or "
         "more than about ten minutes) and doesn't need the user meanwhile; otherwise do the work in this "
         "turn. In the goal, include what is already done in this turn (files saved, findings) and what "
         "remains: the job sees the saved conversation but not this turn's tool results. Add 2-5 "
         "completion criteria in the same language; prefer checkable kinds (file_saved, sources_read, "
         "mentions). The result is posted to this conversation when the job ends. Acting in the browser "
         "(clicking, typing, submitting) or on the Mac (Shortcuts, AppleScript) happens in background "
         "work, where the user is asked before the first action.",
         {"type": "object", "properties": {
             "goal": {"type": "string", "minLength": 1, "maxLength": 4000,
                      "description": "The work to do, in the user's own words and language."},
             "criteria": {"type": "array", "minItems": 1, "maxItems": 5, "items": {
                 "type": "object", "properties": {
                     "description": {"type": "string", "minLength": 1, "maxLength": 300,
                                     "description": "One check, in the user's language."},
                     "kind": {"type": "string", "enum": ["file_saved", "sources_read", "mentions", "judgement"]},
                     "target": {"type": "string", "maxLength": 240,
                                "description": "file_saved: the file or folder's full path (~/… or /…); "
                                               "sources_read: optional, a file name or site the sources must include; "
                                               "mentions: the phrase"},
                     "minimum": {"type": "integer", "minimum": 1, "maximum": 20}},
                 "required": ["description"], "additionalProperties": False}}},
          "required": ["goal", "criteria"], "additionalProperties": False},
         offered=_can_start_a_job),
    Tool("background_status",
         "Read the real state of this conversation's background jobs (running, step, outcome, which "
         "budget limit ended it). Call it FIRST whenever the user asks about work you started — "
         "\"how is it going\", \"is it done\", \"why did it stop\" — and answer from it; "
         "never guess progress, and never use task_progress for this.",
         {"type": "object", "properties": {}, "additionalProperties": False},
         offered=_can_start_a_job),
    Tool("stop_background_work",
         "Stop one running background job of this conversation by job_id when the user asks to stop it.",
         {"type": "object", "properties": {"job_id": {"type": "string", "minLength": 1}},
          "required": ["job_id"], "additionalProperties": False},
         offered=_can_start_a_job),
)

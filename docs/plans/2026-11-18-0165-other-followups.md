# Other follow-ups for v0.1.65

Items found during the v0.1.64 freeze that are not part of goal mode (see `2026-11-18-0165-goal-mode-followups.md` for those). Nothing here changes v0.1.64 code.

## Run log pairing (v0.1.65)

A tool call the loop refuses before it runs leaves the run's steps out of line with its full trace. Observability only: the model, the user's data and the approvals are not affected.

- **Where the event is skipped.** Three refusals in `server/orchestrator/tool_batch.py` answer a call without emitting a `tool_call` event: a cut-off call (`:225-229`), arguments that are not JSON (`:230-239`) and arguments that fail the tool's schema (`:240-247`). Each still goes through `_record_tool_result` (`server/orchestrator/tool_loop.py:162`), which emits a `tool_result` and adds an entry to the run trace (`run_trace.record`, `tool_loop.py:193`). A call that runs emits `tool_call` first (for example `tool_batch.py:271`).
- **Where the steps are built.** `RunRecorder` makes a `tool_call` step only from a `tool_call` event followed by its `tool_result` (`server/services/run_recorder.py:225-236`). A `tool_result` with no open call is dropped, so a refused call has a trace entry and no step.
- **Where they are paired.** `RunRecorder._merge_tool_trace` (`server/services/run_recorder.py:438-460`) pairs steps with trace entries in order. After one refused call, every later step gets the previous entry's `args_full`, `result_raw` and `error`, and the last entry is lost. SBX-7's same-tool check (`:455-460`) keeps the denial and offline codes off a different tool's step, but not the arguments or the result.
- **Seen in the field.** A run where `find_tools` was first refused for empty arguments, then called again, then `run_command` ran: step 1 showed the second query's summary with the first call's `{}`, step 2 (`run_command`) showed `find_tools`' arguments and result, and the command's own result was missing.
- **Direction, to decide in v0.1.65:** either emit a `tool_call` event on the three refusal paths (a step with `ok: false` for each), or pair by a call id carried in both the event and the trace entry instead of by order. A test should run a refused call between two good ones and check each step's `args_full` against its own tool.

## For the v0.1.64 release notes

There is no v0.1.64 release notes draft in the repository yet (`docs/releases/` ends at v0.1.63). Known limit, to add when it is written:

- Phone quick asks search the web and your memory only; anything on the Mac goes through a chat.

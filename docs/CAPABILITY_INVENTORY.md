# Generated capability inventory

Desktop configuration version: `0.1.40`.

Regenerate with `uv run python -m scripts.capability_inventory`. This is static
source evidence, not an installed-account probe or proof of model quality.

`wired` is a catalog declaration; `executor present` means an implementation
is assembled into the built-in registry. Neither grants permission, configures
credentials, proves external availability, nor guarantees live task success.

## Seeded tool catalog

| Toolset | Tool | Tier | Catalog state | Built-in executor source |
| --- | --- | --- | --- | --- |
| task_collaboration | `delegate_work` | orchestrator | wired | [server/registry/task_tools.py](../server/registry/task_tools.py) |
| task_recovery | `task_progress` | orchestrator | wired | [server/registry/task_tools.py](../server/registry/task_tools.py) |
| web_search_scraping | `web_search` | safe | wired | [server/registry/executors.py](../server/registry/executors.py) |
| web_search_scraping | `web_extract` | safe | wired | [server/registry/executors.py](../server/registry/executors.py) |
| file_operations | `read_file` | safe | registered | [server/registry/file_tools.py](../server/registry/file_tools.py) |
| file_operations | `search_files` | safe | registered | [server/registry/file_tools.py](../server/registry/file_tools.py) |
| file_operations | `write_file` | orchestrator | registered | [server/registry/file_tools.py](../server/registry/file_tools.py) |
| file_operations | `patch` | orchestrator | registered | Not in built-in registry |
| session_search | `session_search` | safe | registered | Not in built-in registry |
| skills_management | `skills_list` | safe | registered | Not in built-in registry |
| skills_management | `skill_view` | safe | registered | Not in built-in registry |
| skills_management | `skill_manage` | orchestrator | registered | Not in built-in registry |
| task_planning | `todo` | safe | registered | Not in built-in registry |
| charting | `render_chart` | safe | wired | [server/registry/executors.py](../server/registry/executors.py) |
| code_sandbox | `run_python` | safe | wired | [server/registry/executors.py](../server/registry/executors.py) |
| code_sandbox | `read_skill` | safe | wired | [server/registry/executors.py](../server/registry/executors.py) |
| deck | `render_deck` | safe | wired | [server/registry/executors.py](../server/registry/executors.py) |
| second_brain | `recall` | safe | wired | [server/registry/memory_executors.py](../server/registry/memory_executors.py) |
| second_brain | `remember` | safe | wired | [server/registry/memory_executors.py](../server/registry/memory_executors.py) |
| skill_authoring | `create_skill` | safe | wired | [server/registry/executors.py](../server/registry/executors.py) |

## Additional assembled executors

These are not seeded as spawn-equippable catalog tools. Host policy, workspace
configuration, explicit opt-ins and confirmation still decide access. The
enrolment executor deliberately refuses execution; the UI owns enrolment.

| Tool | Source |
| --- | --- |
| `cancel_task` | [server/registry/schedule_tools.py](../server/registry/schedule_tools.py) |
| `edit_file` | [server/registry/file_tools.py](../server/registry/file_tools.py) |
| `enroll_node` | [server/registry/ssh_tools.py](../server/registry/ssh_tools.py) |
| `list_dir` | [server/registry/file_tools.py](../server/registry/file_tools.py) |
| `list_my_capabilities` | [server/registry/executors.py](../server/registry/executors.py) |
| `list_my_tasks` | [server/registry/schedule_tools.py](../server/registry/schedule_tools.py) |
| `list_nodes` | [server/registry/ssh_tools.py](../server/registry/ssh_tools.py) |
| `run_command` | [server/registry/executors.py](../server/registry/executors.py) |
| `scan_local_network` | [server/registry/lan_tools.py](../server/registry/lan_tools.py) |
| `schedule_task` | [server/registry/schedule_tools.py](../server/registry/schedule_tools.py) |
| `ssh_probe` | [server/registry/ssh_tools.py](../server/registry/ssh_tools.py) |
| `ssh_run` | [server/registry/ssh_tools.py](../server/registry/ssh_tools.py) |

## Provider native-tool transport

`supported` below means the adapter serializes tool schemas in tested request
payloads. It does **not** certify every endpoint/model behind a compatible
provider, or live credentials. Streaming-with-tools is a separate interface.

| Provider key | Wire-contract declaration | Live quality acceptance |
| --- | --- | --- |
| `anthropic` | supported | Not measured by this inventory |
| `custom` | supported | Not measured by this inventory |
| `deepseek` | supported | Not measured by this inventory |
| `gemini` | supported | Not measured by this inventory |
| `groq` | supported | Not measured by this inventory |
| `kimi` | supported | Not measured by this inventory |
| `minimax` | supported | Not measured by this inventory |
| `mistral` | supported | Not measured by this inventory |
| `ollama` | supported | Not measured by this inventory |
| `openai` | supported | Not measured by this inventory |
| `openrouter` | supported | Not measured by this inventory |
| `qwen` | supported | Not measured by this inventory |
| `together` | supported | Not measured by this inventory |
| `zhipu` | supported | Not measured by this inventory |

## Versioned external components

The optional static browser preview is pinned by
`server/resources/browser_runtime/package-lock.json` (npm integrity hashes).
Python dependencies are pinned by `uv.lock`; desktop dependencies by Cargo
and npm lockfiles. User-connected MCP servers and imported skills are separate
trust decisions; see THIRD_PARTY_NOTICES.md and docs/RELIABILITY.md.

## Source fingerprints

| Source | SHA-256 |
| --- | --- |
| `server/registry/executors.py` | `b6d5240b5e5509223dc2a0a0db40713da97ea4bc6fbaf95488d46da7554be3c7` |
| `server/registry/file_tools.py` | `00c265fc87ceb39d3fb13908cc28120763ad833d1989896d7f4008b81aa4e5b4` |
| `server/registry/lan_tools.py` | `34778593e80f8276d545f4ab569803a208a290d5fe4e8d52402f7a876b6f63b1` |
| `server/registry/memory_executors.py` | `5e53443ee8c03360cfe52c5e68f3e4a8196563377a2b7da6e60ea6e7b4f87587` |
| `server/registry/schedule_tools.py` | `13a8698f7e824c1da64cb513b6ebf92de4ab618f75103445e9b12e984ca09a6d` |
| `server/registry/seed_catalog.py` | `c7c0a177ba194fb96b0a05eb3d1bbc5aba56a57b7f581aa3d5dfd37198e7ecd6` |
| `server/registry/ssh_tools.py` | `a31f56ef47fb8559e0595ab7e0365a3582f3e5b417071bee9b4c072cebd9ce5a` |
| `server/registry/task_tools.py` | `37cbaefd1e96ee91360179890562a6ef98c54ce5d51c192f9e184ad63390a6f9` |
| `server/resources/browser_runtime/package-lock.json` | `6b772b55920dfd4e4aa81b55e6721d7ffb80dc0ea59579d86906fb1f6a9b8de1` |
| `server/services/capability_fitness.py` | `5251e4b3644d359fab91b8f3bf4d9ec6cea8dce3ebe6695217755deda959202a` |

# Generated capability inventory

Desktop configuration version: `0.1.63`.

Generated in the release PR; between two releases it may not match the code.

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
| charting | `render_chart` | safe | wired | [server/registry/executors.py](../server/registry/executors.py) |
| code_sandbox | `run_python` | safe | wired | [server/registry/executors.py](../server/registry/executors.py) |
| code_sandbox | `read_skill` | safe | wired | [server/registry/executors.py](../server/registry/executors.py) |
| second_brain | `recall` | safe | wired | [server/registry/memory_executors.py](../server/registry/memory_executors.py) |
| second_brain | `remember` | safe | wired | [server/registry/memory_executors.py](../server/registry/memory_executors.py) |
| second_brain | `conversation_search` | safe | wired | [server/registry/memory_executors.py](../server/registry/memory_executors.py) |
| second_brain | `memory_note` | safe | wired | [server/registry/memory_executors.py](../server/registry/memory_executors.py) |
| skill_authoring | `create_skill` | safe | wired | [server/registry/executors.py](../server/registry/executors.py) |

## Additional assembled executors

These are not seeded as spawn-equippable catalog tools. Host policy, workspace
configuration, explicit opt-ins and confirmation still decide access. The
enrolment executor deliberately refuses execution; the UI owns enrolment.

| Tool | Source |
| --- | --- |
| `attach_file` | [server/registry/file_tools.py](../server/registry/file_tools.py) |
| `background_status` | [server/registry/task_tools.py](../server/registry/task_tools.py) |
| `browser_back` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `browser_click` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `browser_look` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `browser_open` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `browser_press` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `browser_select` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `browser_type` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `cancel_task` | [server/registry/schedule_tools.py](../server/registry/schedule_tools.py) |
| `desktop_access` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `desktop_apps` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `desktop_batch` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `desktop_click` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `desktop_look` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `desktop_menu` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `desktop_open` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `desktop_press` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `desktop_scroll` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `desktop_select` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `desktop_takeover` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `desktop_type` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `edit_file` | [server/registry/file_tools.py](../server/registry/file_tools.py) |
| `enroll_node` | [server/registry/ssh_tools.py](../server/registry/ssh_tools.py) |
| `find_capability` | [server/registry/executors.py](../server/registry/executors.py) |
| `list_dir` | [server/registry/file_tools.py](../server/registry/file_tools.py) |
| `list_my_capabilities` | [server/registry/executors.py](../server/registry/executors.py) |
| `list_my_tasks` | [server/registry/schedule_tools.py](../server/registry/schedule_tools.py) |
| `list_nodes` | [server/registry/ssh_tools.py](../server/registry/ssh_tools.py) |
| `mac_applescript` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `mac_list_shortcuts` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `mac_run_shortcut` | [server/registry/hands_tools.py](../server/registry/hands_tools.py) |
| `run_command` | [server/registry/executors.py](../server/registry/executors.py) |
| `scan_local_network` | [server/registry/lan_tools.py](../server/registry/lan_tools.py) |
| `schedule_task` | [server/registry/schedule_tools.py](../server/registry/schedule_tools.py) |
| `ssh_probe` | [server/registry/ssh_tools.py](../server/registry/ssh_tools.py) |
| `ssh_run` | [server/registry/ssh_tools.py](../server/registry/ssh_tools.py) |
| `start_background_work` | [server/registry/task_tools.py](../server/registry/task_tools.py) |
| `stop_background_work` | [server/registry/task_tools.py](../server/registry/task_tools.py) |
| `whats_new` | [server/registry/executors.py](../server/registry/executors.py) |

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
| `server/registry/executors.py` | `42d8c90960a66c51cdb4712682a988cde46c5c7a7f00d36ac60459cf887cb62c` |
| `server/registry/file_tools.py` | `96dadaf8aa60ddc58bcb3be4eeae2281873eb28a2059adf68b1c9c639c0f18dd` |
| `server/registry/hands_tools.py` | `619468d32a364b53d8bf5fdd10ae8471ebfa0bc32ab7bc7147a2cce58af6f7c3` |
| `server/registry/lan_tools.py` | `34778593e80f8276d545f4ab569803a208a290d5fe4e8d52402f7a876b6f63b1` |
| `server/registry/memory_executors.py` | `bd82b710e3f3bfbade8e00301115eb4a09ba2d5a45152d6614cad0b275d63269` |
| `server/registry/schedule_tools.py` | `c11d786317d7c67c243d625878d2f0015a368677aadf31828c0ec1d1ab31890a` |
| `server/registry/seed_catalog.py` | `e53b1aaa0b0213d1156e44e3fd7fb9b1e12b7423b859ecde3990b953d650fda7` |
| `server/registry/ssh_tools.py` | `a31f56ef47fb8559e0595ab7e0365a3582f3e5b417071bee9b4c072cebd9ce5a` |
| `server/registry/task_tools.py` | `19a8b1fc427589b300fb51d4fddc8051f66dbf8b5eb00c523e44a1a1c3d9e42c` |
| `server/resources/browser_runtime/package-lock.json` | `6b772b55920dfd4e4aa81b55e6721d7ffb80dc0ea59579d86906fb1f6a9b8de1` |
| `server/services/capability_fitness.py` | `5251e4b3644d359fab91b8f3bf4d9ec6cea8dce3ebe6695217755deda959202a` |

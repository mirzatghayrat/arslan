# W16 — Conversation-first workspace navigation

Implemented the four primary destinations (Conversations, Projects, Memory,
Capabilities), with Connections & permissions and Settings in the footer.
Capabilities groups Experts, Skills & workflows, Tools, and Discover; existing
expert configuration, skill creation, saved candidates, diagnostics, and MCP
configuration remain reachable.

Recent conversations contains ordinary conversations and explicitly opened
expert chats. A historical message is not treated as proof of a user-opened
expert chat. Existing expert work is retained in a separate disclosure. The
local preference stores only bounded, validated expert IDs, not chat content.

Ongoing tasks uses the local-owner task endpoint, filtered to queued, running,
waiting-user, and verifying phases. Opening a task selects its conversation;
it does not resume execution or approve anything. Failed status reads are
shown as unavailable, not as an empty list. Older servers are also filtered
on the client. Task-list tests cover both terminal exclusion and ownership.

## Verification

- Focused sidebar, task-list, expert-ID, empty-state, capability-tab and
  connection-routing tests passed. TypeScript and production build passed.
- Full web suite: 227 files / 1,743 tests passed with the documented Node
  compatibility flag `NODE_OPTIONS=--no-experimental-webstorage`. Without
  that flag this host's Node exposes an incompatible localStorage stub.
- Actual local UI exercised at 900 × 720: dark English capabilities and
  connections pages, then light German workspace. Navigation and cards fit;
  historical synthetic expert messages remained outside Recent conversations.
- Harness uses synthetic credentials and blocks model/service requests. No
  actual account connection, paid inference, or App Store write was tested.
- Remaining legacy untranslated strings were observed in the German UI and
  belong to W21; this report does not assert full language consistency.
- Production build retains the pre-existing large-chunk warning.

No installed application was replaced and nothing was published.

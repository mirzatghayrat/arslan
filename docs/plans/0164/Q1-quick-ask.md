# Q1 快问（Quick Ask）：替换 iPhone 的 Remote（Mac 端）

> ⓪Plan 2026-10-29 夜间起草，用户 10-28 已定分级。v0.1.64 计划（#434）由用户点合并后才开工。

| 项 | 内容 |
|---|---|
| 道 | ⓪Plan 的建议：②Main 做 Mac 服务端和 Bridge（Q1a、Q1b）；①iOS 做 iPhone 端（Q1c，在 iOS 仓库，跟 B 段一起）。Bridge 契约文件的改动由 ①iOS 审（`docs/sessions.md` §2） |
| 版本 | v0.1.64 |
| 分级 | 必须（用户 10-27 定进 v0.1.64，10-28 确认；iPhone 1.0 要等整套改版才送审，快问是改版的一部分） |
| 依赖 | **硬依赖：用户对 Bridge 帧的明确点头**（见「开工前要用户定的」第 1 条），没点头之前 Q1a、Q1b 都不写代码。另外：迁移和 SUB 共用（`kind` 列，SUB 要的父对话 id 同一次迁移，Q1 先申请）；`chat.send` 的新对话 id 和 iPhone 1.0 字段那批共用一个字段 |
| 合并位置 | Q1a 先合（只有 Mac 服务端，没有 Bridge 就不会出现快问，等于暗着上）；Q1b 在 Q1a 之后。Q1a 改 `server/orchestrator/arslan.py`（热点文件，`docs/sessions.md` §3）：排在当时打开的 K 线 PR 后面。Q1 在 SUB 之前合（共用迁移） |
| 推动的门槛 | iPhone 1.0 送审要的 Mac 端能力（`docs/plans/0162/README.md` §8「iPhone 1.0 要的 Mac 端字段」）；M3 第 10b 条（run 362）手机上第二个问题被当成上一个的追问 |
| 分支 | `claude/0164-q1a-quick-ask-server`、`claude/0164-q1b-quick-ask-bridge` |
| 迁移号 | 一个，Q1a 带。号由 ②Main 在 `docs/plans/0164/README.md` §6 登记（main 上最新是 0070，下一个空号是 0071）。和 SUB 共用 |

## 目标

- 今天手机上的每个问题都进同一个对话 Remote（`server/services/phone_reads.py:22` `REMOTE_ID = "pocket"`；Bridge 没带 `conversation_id` 的 `chat.send` 一律进它，`desktop/bridge/Sources/BridgeCore/ConversationLinks.swift:403`）。前面的话题带进后面，模型会把新问题当追问。
- 换成快问：每条快问是一个**新的、只读的、不学东西的**对话。
  - 只给四个只读工具：`web_search`、`web_extract`、`recall`、`conversation_search`。不出卡。
  - 不进普通对话列表（Mac 侧栏、手机的对话列表、`/phone/live` 都不列）；手机另有「快问记录」，只列快问。
  - 回答短，附来源。
  - 「转成对话」：把这条快问变成普通对话，工具全开。
- 用户 10-27 定的五条照做：① 用当前默认模型；② 快问记录一直保留，能逐条删（用现有的 `conversation.delete`）；③ Mac 快捷键小窗不在这一版；④ 不进 Mac 侧栏；⑤ `conversation_search` 能搜到快问。
- **35 分钟的追问时限全在 iPhone 上。** 「是不是追问」只由用户的操作定：手机带上原来那条快问的 id 就是追问，带新 id 就是新问题。Mac 不计时、不猜。

## README 和代码对不上的地方（⓪Plan 在 main `8db45ef9` 上核过）

1. **「按后台任务的做法收窄」：** 后台任务的做法是**去掉**四个只在聊天里有用的工具（`server/orchestrator/arslan.py:718-728`，`_LIVE_TURN_ONLY`），其余全留。快问要的是反过来：**只留**四个（允许清单，不是黑名单）。而且要同时收窄两份：给模型看的（`resolve_tools`）和能调用的（`resolve_callable`）。今天聊天回合两份分别是 `_arslan_tools` 和 `_callable_tools`（`arslan.py:839`），后者就是全部工具（`arslan.py:1070-1071`）；只收窄前者，模型照样能靠 `find_tools` / `use_tool` 调到别的。K7 的回退开关 `tools_all_resident` 打开时给全部工具（`arslan.py:1045-1050`、`:1059-1060`），快问也不能跟着放开。
2. **「现有的 context PUT」：** `PUT /conversations/{id}/context`（`server/api/companion.py:250`）要带 `expected_version` 和整套隐私开关（`:149-156`），而 Bridge 访问 Mac 后端只有 GET、POST、DELETE 和上传文件四种（`desktop/bridge/Sources/BridgeCore/BackendReads.swift:9-16`），没有 PUT。所以要么 Bridge 加 PUT，要么加一个手机专用的小接口（建议后者，见「怎么做」）。
3. **`kind` 这个名字已经有人用了：** `conversations.result` 每一条已经带 `kind`，取值 `remote` / `chat` / `task` / `scheduled`，是**每次现算的**（`server/schemas.py:826-827`；`server/services/phone_reads.py:263-270`），协议里也写了（`docs/specs/mobile-bridge-protocol.md:303`）。快问要的是**存下来的**标记。两者要合成一个意思：存下来的 `quick` 优先，其余照旧现算。README §6 写的「对话表加 `kind` 列」：没有对话表，对话只是消息行加上 `conversation_contexts`（`server/db/companion_models.py:16-29`），列加在后者上。**不是每个对话都有这一行：** 只有设过隐私开关、项目这类的对话才有（`list_conversations` 是另外查这张表的，查不到就当没有，`server/api/conversations.py:97-101`）。所以新列（`kind`、SUB 的父对话 id、以后可能的标题）的每个读的地方，都要把「没有这一行」当成 `chat`（其余照旧现算）。要写这些列时没有这一行，就新建一行（新建快问、转成对话、以后的改名都一样）。
4. **「`conversation.update` 顺带满足 rename」：** Mac 服务端今天不存标题。列表里的标题是第一句用户消息现截的（`server/api/conversations.py:84`；`server/schemas.py:815-817` 写明「title is DERIVED, not stored」），Mac 窗口里的标题存在网页自己的本地存储里（`web/src/App.tsx:265-280`）。要改名就得多存一列标题，Mac 侧栏也不会自动跟着变。所以「只多一个类型」只对 `kind` 成立；`title` 要不要这一版做，列在「开工前要用户定的」第 2 条。
5. **「pocket 只对说了 quick 的手机显示成 Remote（旧）」：** 名字 Remote 是服务端在列表里统一换上的（`server/api/conversations.py:106-107`），服务端不知道是哪台手机在问；各台手机说了什么能力只有 Bridge 知道（`Mailbox.has`，`desktop/bridge/Sources/BridgeCore/Mailbox.swift:350`）。建议让 iPhone 自己显示「Remote（旧）」，Mac 不改名。
6. **对的，但要守住：** 「不写记忆用 `no_learning`」是对的，**不能用 `no_memory`**。`conversation_search` 会跳过 `no_memory` 和临时对话（`server/services/conversation_search.py:43-45`），工具本身在这种对话里也直接拒绝（`server/registry/memory_executors.py:109-110`），用错了快问就搜不到了（违反第 ⑤ 条）。`no_learning` 已经挡住：回合后的事实提取（`arslan.py:513`）、学做法（`server/services/lessons.py:405`）、`remember` 和 `memory_note`（`server/services/memory_tools_v2.py:48-49`、`:126-127`）；`recall` 不受影响。
7. **README 没提的一处：** 手机回合会加一句提示，让模型「用 `find_tools` 找 `attach_file` 把文件发给手机」（`arslan.py:700-702`，`:850` 加上）。快问里这两个工具都没有，这句要换成快问自己的一句（回答短、附来源、没有文件）。
8. README 里其余的引用核过都对：`phone_reads.py:22`、协议 `:400`「pocket 永不删」、`server/api/phone.py:39` 的 `SEARCH_TOOLS` 只管吉祥物表情；没有自动删对话的地方（唯一删消息的是撤销，`server/services/turn_undo.py:233`）。

## 改哪些文件

### Q1a（②Main，Mac 服务端）

- **迁移**（一个，和 SUB 共用；Q1a 的第一个提交，**只加不减**：只加可空的列，不删列、不改列、不搬数据）：`conversation_contexts` 加 `kind` 列（可空，空 = 照旧现算；这一版只写 `quick` 和 `chat`）。没有这一行的对话读成 `chat`（见上面第 3 条）。SUB 要的父对话 id 同一次加。要不要加标题列看第 2 条决定。按 `docs/sessions.md` §4 同改四处：`server/db/migrations/versions/_00NN_*.py`、`server/db/migrations/runner.py`、`tests/server/test_migration_runner.py`、`server/db/companion_models.py`（§4 写的是 `server/db/models.py`；这张表的模型在 `companion_models.py`）。
- `server/orchestrator/arslan.py`：
  - 加 `_QUICK_TOOLS = {"web_search", "web_extract", "recall", "conversation_search"}`，以及快问用的 `resolve_tools` / `resolve_callable`：都从全部工具里**按允许清单取**，不带 `find_tools`、`use_tool`，不看 `tools_all_resident`。
  - `handle_user_message`（`:407`）读这个对话存着的 `kind`：是 `quick` 就用上面两份，提示换成快问的一句（不加 `PHONE_NOTE`）。
- `server/api/phone.py`（Bridge 契约文件，①iOS 审）：
  - 新建快问：例如 `POST /phone/conversations/{id}/quick`。只对还没有消息的 id 生效，有消息就 409（照 `server/api/companion.py:270-273` 临时对话的做法）。写 `kind = quick`、`no_learning = True`，**不碰 `no_memory`**。
  - 转成对话：例如 `POST /phone/conversations/{id}/update`，`{kind?: "chat", title?}`。回合进行中返回 409，Bridge 回 `mac_busy`。「进行中」用现成的判断：`run_registry.active_for`（`server/services/run_registry.py:65`）、`turn_journal.active`（`server/services/turn_journal.py:63`）。
  - `/phone/conversations` 加可选 `kind=quick`，原样传给列表函数。
- `server/api/conversations.py` 的 `list_conversations`（`:33`）：默认不列 `kind = quick`；带 `kind=quick` 时只列快问。Mac 侧栏（`web/src/App.tsx:176`、`web/src/hooks/useConversationIndex.ts:19`）、手机列表（`server/api/phone.py:106-113`）、`/phone/live`（`server/api/phone.py:288-300`）都走这个函数，一处改三处跟着变。
- `server/services/phone_reads.py` 的 `describe`（`:263-270`）：存着的 `quick` 优先，返回 `kind: "quick"`。
- **网页（要改，量很小）：**
  - 快问本身不用改网页：快问不进 `/conversations`，Mac 侧栏自然看不到；转成对话以后，侧栏的轮询会把它当成「别处开的对话」加进来，标题取服务端的（`web/src/lib/sessionPersistence.ts:222-236`）。
  - 但网页自己写死了 pocket：`web/src/lib/threadTitles.ts:11` 把它显示成 Remote；`web/src/lib/conversationMeta.ts:19`（`REMOTE_ID`）、`:27`（服务端没给 `kind` 时也当 `remote`）、`:41-44`（`remoteFirst`，`web/src/components/Sidebar.tsx:65` 用它把 Remote 钉在侧栏最上面）。pocket 留着的这一版，这几处行为不变，只加 `DELETE-BY:` 注释（见「怎么做」第 7 条）；pocket 删的那一版，这几处跟着删。
  - `conversationMeta.ts:20` 的 `KINDS` 没有 `quick`：快问默认不进 Mac 侧栏，碰不到；不加。
- **测试：** 见「验收」。

### Q1b（②Main 写，①iOS 审；Bridge 和契约）

- `desktop/bridge/Sources/BridgeCore/ConversationLinks.swift`：
  - `chat.send`（`:394-408`）：带快问标记和新对话 id 时，**先**调 Q1a 的新建快问接口，成功了才发消息；失败就拒这条 `chat.send`，**不许**当普通对话发出去。
  - `hello` 的能力（`:497`）加 `quick`（名字 ②Main 定）。
  - `conversations.list`（`:428-432`）：把手机给的 `kind` 原样转给后端。
  - 新帧 `conversation.update` → `conversation.updated`：转给 Q1a 的接口，409 回 `mac_busy`。
  - `conversation.delete`（`:412-421`）：说了 `quick` 的手机可以删 pocket；没说的照旧拒（`:414`）。
- `desktop/bridge/Sources/BridgeCore/FrameMapper.swift`：不改（快问的标记在 Bridge 和后端之间走接口，不进 `user_message` 帧）。
- `docs/specs/mobile-bridge-protocol.md`：`chat.send` 的新字段、`hello` 能力、`conversations.list` 的 `kind`、`conversations.result` 的 `kind` 多一个 `quick`、新帧、`pocket` 那条（`:400`）改成「说了 quick 的手机可以删」。注明日期。
- `spec/mobile-bridge/make_vectors.py` 和生成的 `spec/mobile-bridge/vectors/messages.json`：新帧和新字段各加一条共享向量（①iOS 的 BridgeKit SharedVectors 对同一份）。
- 测试：`desktop/bridge/Tests/BridgeCoreTests/ConversationLinksTests.swift`、`VectorTests.swift`。

### Q1c（①iOS，iOS 仓库，不在本仓库）

- 首页输入框、快问页、快问记录、转成对话、35 分钟时限和「＋ 新问题」、最近 3–5 条的小标签；Mac 没有 `quick` 能力时落到 Remote，用一行灰字说明；自己显示「Remote（旧）」。

## 不许碰

- 用户没点头之前，任何 Bridge 帧和 `hello` 能力（`docs/sessions.md` §2；CLAUDE.md 的长期规矩）。
- `no_memory` 的意思，和 `conversation_search` 跳过 `no_memory` / 临时对话的规则。
- 后台任务的工具收窄（`arslan.py:718-728`）：快问另写一份，不改它。
- `server/api/phone.py:39` 的 `SEARCH_TOOLS`：只管吉祥物表情，不是快问的白名单。
- 普通对话的列表顺序、现算的 `kind`、标题来源。
- 删对话接口（`server/api/conversations.py:152`）：它不删 `conversation_contexts` 那一行，快问删掉以后留一行带 `kind` 的空壳，没有影响，不顺手改。
- `Wire.version`（`desktop/bridge/Sources/BridgeCore/Wire.swift:13`）：这批全是新增的可选字段和新帧，不升协议版本。

## 怎么做（要点）

1. 用户对帧点头以后，①iOS 和 ②Main 先出一份帧的变更清单（和 iPhone 1.0 字段、SUB、CAP、INB 那几批一起），定字段名。
2. Q1a 先写测试：今天一个对话不管怎么标，模型拿到的都是全部工具。
3. 快问的工具在**服务端**收窄，按对话存着的 `kind` 判断。不信 Bridge 每条消息带来的标记：哪怕 Bridge 出错，一个存成 `quick` 的对话也拿不到别的工具。
4. **出错时宁关：** 存 `quick` 失败，Bridge 拒这条消息；不能退回成普通对话去跑（第一回合会拿到全部工具）。
5. 转成对话只把 `kind` 改成 `chat`。之后要不要开始学东西，看「开工前要用户定的」第 3 条。
6. 快问的回答「短、附来源」写在快问那一句提示里，不改系统提示（K3 的缓存要它不变）。
7. 旧路径：pocket 留给没说 `quick` 的旧手机。下面每一处都写上 `DELETE-BY:`，版本由用户定（第 4 条）：
   - Bridge：`desktop/bridge/Sources/BridgeCore/ConversationLinks.swift:33`（`pocket` 常量）、`:231`（`linkLive` 跳过 pocket）、`:403`（`chat.send` 没带 id 进 pocket）、`:414`（不许删 pocket）、`:434`（`chat.history` 没带 id 读 pocket）；
   - 服务端：`server/services/phone_reads.py:22-23`（`REMOTE_ID`、`REMOTE_TITLE`）、`:263-264`（现算成 `remote`）、`server/api/conversations.py:106-107`（列表里改名 Remote）；
   - 网页：`web/src/lib/threadTitles.ts:11`、`web/src/lib/conversationMeta.ts:19`、`:27`、`:41-44`（`remoteFirst`）。
   - 开工时再 `git grep -n 'pocket\|REMOTE_ID\|remoteFirst\|sidebar.remote'` 一遍，列全了再写注释。翻译键 `sidebar.remote` 也算：它在 6 种语言的 `web/src/locales/*.json` 里是嵌套的 `remote`，上面那条 `git grep` 查不到，要另查。删的那一版用同一条 `git grep` 查不到为证。
   - Correction (⓪Plan's review of #479, F6): the locale key `sidebar.remote` stays. `RemoteChip` in `web/src/components/OrchestratorChat.tsx`, the trace on a message the phone sent, uses it too. Only its use in `threadTitles.ts`, the pocket's title, goes with the pocket.
8. PR 描述写完成证据四项（`docs/sessions.md` §8）。

## 验收

**pytest 和 Swift 测试只测通路。** 下面每条都要能分出两种设计：把对应的改动去掉，测试要红（mutation）。

- 快问对话：模型看到的工具正好是那四个，能调用的也正好是那四个；没有 `find_tools`、`use_tool`；`tools_all_resident` 打开时也一样。同一条消息在普通对话里照旧拿到全部工具。
- 假模型在快问里点名调 `run_command`、`remember`：不执行，也不出卡。
- 快问回合结束后不提取事实、不学做法（普通对话同一回合会）。
- `conversation_search` 能返回快问里的消息（第 ⑤ 条的通路）。mutation：把快问建成 `no_memory`，这条要红。
- 列表：默认不含快问；`kind=quick` 只含快问；`/phone/conversations`、`/phone/live` 跟着默认走；普通对话的结果和改之前一样。
- 没有 `conversation_contexts` 行的对话：列表里读成 `chat`、照旧出现，回合拿到全部工具（mutation：把「没有这一行」当成别的值，这条要红）。新建快问、转成对话在没有这一行时会新建一行。
- 新建快问：对已有消息的 id 返回 409。转成对话：之后拿到全部工具；回合进行中返回 409。
- 迁移：从 0070 升上来；`test_migration_runner.py` 的 id 列表。
- Bridge：带快问标记的 `chat.send` 先建快问再发消息；建快问失败时拒绝、后端没收到消息；`hello` 带 `quick`；`conversations.list` 把 `kind` 转过去；`conversation.update` 回 `conversation.updated`，409 回 `mac_busy`；只有说了 `quick` 的手机能删 pocket；没说 `quick` 的旧手机所有行为不变（照旧进 Remote）。共享向量重新生成，`VectorTests` 过。

**只有真模型分得出来的，放 bench / M1，不放 pytest**（`docs/plans/0162/README.md` §8 第 ⑤ 条）：

- 不提以前的事的新快问：`conversation_search` 调用 0 次。
- 「上次问的拉面」这类问题：能找回以前那条快问。
- 回答短、附来源。
- 上线前用真实问题试小红书这类要登录的网站，结果写进报告；没试过不对外承诺。

**真机（①iOS 的 B 段一起）：** 新 iPhone 版对这台 Mac 走一遍新建、追问、转成对话、删一条；当前 TestFlight 上的旧版对同一台 Mac 照旧能用 Remote。

**§11：** 被取代的东西（pocket 那几处分支）要么删掉、用 `git grep` 为证，要么带着用户定的 `DELETE-BY:` 留着。

## 量级

- Q1a：产品代码约 +250 行（迁移约 40，工具和提示约 60，两个接口约 80，列表和 `describe` 约 40，其余零碎）；测试约 +300 行。
- Q1b：Swift 约 +150 行，协议文档和向量约 +80 行；测试约 +200 行。
- 两个都在 §5 的约 800 行以内。合成一个也不超，分开是因为 Q1b 动 Bridge 契约文件，要 ①iOS 单独审，而且 Q1a 可以先暗着上。

## 风险与回退

- **风险：第一回合拿到全部工具。** 建快问和发消息之间如果出错或抢跑，第一条快问会按普通对话跑。挡法：服务端只认存下来的 `kind`；Bridge 存不上就拒；已有消息的对话不能再标成快问。各有测试。
- **风险：搜不到以前的快问。** 用户把「云端模型使用以前的对话」关掉时，`conversation_search` 在云端模型上直接报错（`server/registry/memory_executors.py:111-113`），快问也就找不回以前的事。这是现有开关的本意，不改；M1 照用户的实际设置跑，报告里写明。
- **风险：** `conversation_search` 给的链接是 `#conversation=<id>`（`server/services/conversation_search.py:76`）。普通对话里搜到一条快问，在 Mac 上点开的是一个侧栏里没有的对话。能用，就是有点怪；记在 PR 里，v0.1.65 的 Mac 小窗再看。
- **风险：** 改 `server/orchestrator/arslan.py` 容易和 K 线冲突。排在当时打开的 K 线 PR 后面，rebase 两边都留。
- **风险：** 快问记录越积越多，手机一次最多拿 100 条（`ConversationLinks.swift:429`）。见第 5 条。
- **留下的旧路径：** pocket（Remote）留给旧手机，`DELETE-BY:` 的版本由用户定（第 4 条）。
- **回退：** Q1b 整个 revert：Mac 不再说 `quick`，新 iPhone 自己落到 Remote（Q1c 的兜底）。Q1a 的代码可以单独 revert：迁移只加可空的列，代码没了，空列 = 照旧现算，什么都不坏。迁移本身发版以后号冻结，列留着。
- **表的改动的规矩（②Main 审 #434 时提出）：** revert 代码恢复不了一张表。所以减表、减列、搬数据，各自单独一个 PR，排在用到它的代码已经删掉之后。Q1 的迁移只加不减，用不上这条；以后 pocket 删的那一版也不动表（pocket 只是一个对话 id，没有自己的表）。

## 开工前要用户定的

1. **Bridge 帧（硬依赖，没点头不写代码）：** 这一批要改的是：
   - `chat.send` 加快问标记（例如 `conversation_kind: "quick"`），和 iPhone 1.0 那批的新对话 id 一起；
   - `hello` 加能力 `quick`；
   - `conversations.list` 加可选的 `kind: "quick"`，`conversations.result` 的 `kind` 多一个取值 `quick`；
   - 新帧 `conversation.update {conversation_id, kind?: "chat", title?}` → `conversation.updated`；
   - 协议里「pocket 永不删」改成「说了 quick 的手机可以删」。

   建议和 iPhone 1.0 字段、SUB、CAP、INB 的帧放在一起问一次（`docs/plans/0164/README.md` §2 第 3 条）。
2. **`conversation.update` 这一版带不带 `title`（改名）。** 带的话，迁移里多一列标题，而且只有手机看得到新名字：Mac 窗口的标题存在网页本地，要另做才会跟着变。不带的话，帧里先只有 `kind`，改名留给以后。
3. **转成对话以后，Arslan 要不要从这条对话里学东西。** 一种：从转的那一刻起照普通对话学，之前快问那几轮照旧不学。另一种：一直不学。
4. **pocket（Remote）给旧手机留到哪一版。** iPhone 1.0 还没送审（README §8），用旧版的只有 TestFlight 上的人。一种：留到 v0.1.65，代码里写 `DELETE-BY: v0.1.65`；另一种：这一版就删，旧版手机升级前用不了 Remote。
5. **「快问记录」怎么搜。** 一种：手机只在最近 100 条里自己筛（今天的上限）。另一种：给 `conversations.list` 加翻页（①iOS 提过 before / has_more），或者加一个服务端搜索的帧。后两种也是帧的改动，和第 1 条一起问。
6. **分级和分道：** ⓪Plan 建议「必须」，Mac 端 ②Main、iPhone 端 ①iOS；随 v0.1.64 的范围一起定。

## ①iOS 审阅的结论（2026-10-29 夜，经 ⓪Plan 转记；用户 10-28 定：不贴到 PR 上，只记在这里）

- **帧能并成一份清单：** ①iOS 起草了一份 13 项的清单，全是可选字段或新帧，不升 `Wire.version`。建议：
  - 快问标记只在带了 `new_conversation_id` 时才有效；Mac 说了 `quick`，就意味着也支持新对话；
  - `conversations.list` 的 `before` / `has_more` 翻页这一版就做（上面第 5 条）：快问记录永久保留，很快就会超过 100 条；
  - `conversation.update` 这一版不带 `title`（上面第 2 条），原来提的 `conversation.rename` 一起撤掉。
- **「Remote（旧）」由 iPhone 自己显示：** 条件是 Mac 的 `hello` 里有没有 `quick`，不看手机支不支持；Mac 端什么都不用改。
- **10-26 §4b 的两点还要 ②Main 定：** 新对话的第一条带附件时 `file.offer` 用 `phone-<uuid>`；`outcomes` 只放已经结束的任务。
- **INB 和 SUB 在手机上的部分：**
  - 「做完未看」（`done_unseen`）进 v0.1.64，但要按手机的能力降级：手机的 `hello` 里说了 `done_unseen` 才发新值，否则发 `done`。旧版手机会把不认识的状态当成 idle，做完了却显示灰点。
  - 进展的四行简报在手机上顺延 v0.1.65：它会拖慢 iPhone 1.0 送审；字段是可选的，Mac 可以先发。
  - 子会话上手机放 v0.1.65。
  - notify 收窄（INB 第 5 条）会改变所有手机（包括旧版）收到的推送，单独让用户定。

**用户 10-28 定：照 ①iOS 的建议。** 翻页这一版做；改名先不做（`conversation.update` 不带 `title`，`conversation.rename` 撤掉）；「做完未看」按手机的 `hello` 降级；四行简报和子会话上手机顺延 v0.1.65。**notify 收窄（「推送只推要你做的」）还没定，单独问用户。** 10-26 §4b 的两点（`phone-<uuid>`、`outcomes` 只放已结束的任务）仍由 ②Main 定。

## Frame names, fixed (②Main, 2026-10-29)

①iOS builds Q1c against these. The names are ①iOS's, as the user approved on 10-28; A–C are the details this card left to ②Main.

- **`hello.capabilities`:** the Mac adds `new_conversation` and `quick`; the phone adds `quick`. A Mac that says `quick` always also says `new_conversation`.
- **`chat.send`** gains `new_conversation_id` and `conversation_kind: "quick"`. `conversation_kind` is valid only together with `new_conversation_id`, and `quick` is its only value. The Mac stores `kind=quick` before it runs the message; if it can't, it refuses, and the backend never sees the text.
  - **A (§4b):** the phone makes `new_conversation_id` as `phone-` plus a lowercase UUID v4.
  - **B, new error codes** (in `error`, with `related_id` = that `chat.send`):
    - `bad_request`: `conversation_kind` without `new_conversation_id`, an unknown kind, an id not shaped `phone-<uuid>`, or an unknown `conversations.list` `kind`;
    - `conversation_exists`: `new_conversation_id` names a conversation that already has messages.

    A retry with the same `client_msg_id` gets the first result, so it never trips `conversation_exists`.
- **`conversations.list`** gains optional `kind` (only `"quick"`: quick conversations only; absent: today's list, which leaves them out) and `before`. **`conversations.result`** gains `has_more`.
  - **C:** `before` is the `updated_at` of the oldest conversation the phone holds, sent back exactly as received. The Mac returns conversations strictly older than it, most recent first, up to `limit`, and `has_more` says whether any remain.
    - Times are whole seconds, so a page never splits one. A page the limit would end inside a second ends before it, and the next page starts there.
    - A second that alone holds more than `limit` comes whole. That is the only page longer than `limit`.
    - The phone keeps its id dedupe, accepts a page longer than `limit`, and stops on `has_more: false`. A page that brings nothing new while `has_more` is true is logged and stops the paging, without looping.

    Why not inclusive (the first version of C): when one second filled a page, every request returned the same rows, and the paging could never get past them (⓪Plan's review of #479, F1, 2026-10-29; ①iOS agreed).
- **`conversation.update {conversation_id, kind: "chat"}` → `conversation.updated {conversation_id, kind}`.** No `title`. `chat` is the only target. While a turn runs, the answer is `error` `mac_busy`.
  - Only a quick conversation, or a retry for one already turned. Any other id, an ordinary conversation included, gets `error` `not_found` and is left as it is (⓪Plan's review of #479, F4).
- **`conversation.delete`** deletes a quick conversation like any other. A phone that said `quick` may also delete the pocket.
- **Still open, ②Main:** §4b's other point (`outcomes` holds only finished tasks).

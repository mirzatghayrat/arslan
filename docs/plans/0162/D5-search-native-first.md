# D5 搜索：先用这个对话的模型自带的搜索，key 作备选，被拦就说被拦

| 项 | 内容 |
|---|---|
| 道 | ⓪Plan（10-21 晚从 ②Main 改过来，②Main 线上卡太多；产品代码由别的会话审） |
| 版本 | v0.1.63 |
| 分级 | 应该（用户 2026-10-20 要求出这张卡，版本和分级由 ⓪Plan 定，理由见下） |
| 依赖 | — |
| 合并位置 | **不进 K 线串行链，但要在 R63 用 Claude 跑最后一轮全套之前合（用户 2026-10-20）。** 改 `server/registry/search_providers.py`、`server/registry/executors.py` 的 `web_search` 那一段、新增 `arslan/llm/anthropic_search.py`、设置页的搜索一节，以及把「这一轮用的是哪个模型」带给工具的那一处（见「改哪些文件」1）。都不是 K 线的热点文件；K5 要改工具说明，D5 先合就让 K5 照新的写 |
| 推动的门槛 | §5.1 T2、T3（在 Claude 上）；R63 的「对 Claude Code」对比 |
| 分支 | `claude/0163-d5-search-native-first` |
| 迁移号 | 无。沿用 `search_provider` / `search_api_key` / `search_base_url`，新增一个普通设置项 `search_provider_role`（键值表里的一行，登记在 `settings_service._PLAIN_KEYS` 和两个 pydantic schema 上）。开工时核对确实不需要迁移 |
| 来源 | 2026-10-20 bench：T2、T3 在 Claude 上碰到 DuckDuckGo 的人机验证；用户要求查清 Hermes 用的是什么、出这张卡。③Hands 审卡（#261）提了三条，已改进本卡 |

## 为什么放 v0.1.63 的「应该」（⓪Plan 定）

- **这是用户今天就会碰到的。** 用户默认用 Claude（claude-sonnet-5），而 Arslan 在 Claude 上的搜索只有一条路：抓 DuckDuckGo 的 HTML 页面（`DuckDuckGoHtmlProvider`，自己就标着 `best_effort`）。这个页面时好时坏，被拦时整个搜索就没了。
- **R63 要在 Claude 上和 Claude Code 比。** Claude Code 搜索走的是 Anthropic 服务端的 web search。T2、T3 都靠搜索，不改这一点，那两题输掉的原因就不是内核。
- **顺手修一个今天就有的隐私问题**（③Hands 审卡时发现，见「今天的情况」）：DeepSeek 自带搜索看的是主配置，不是这个对话的模型。
- **改动小，风险低：** 照已有的 `DeepSeekNativeProvider` 的写法再加一个 provider，再把「自动顺序」改一下。不碰 K 线文件，可以在 K 卡之间的空档合。
- **为什么不是「必须」：** DeepSeek 用户已经走 DeepSeek 自带的搜索（bench 里全部 `provider: deepseek`、都成功）；被拦时已经报 `search_blocked`，不会冒充「找不到」。所以这不是坏掉的功能，是 Claude 用户的搜索不稳。

## 今天的情况（main `6e17afc3`，⓪Plan 和 ③Hands 核过）

- **自动顺序**（`executors._auto_search_providers`）：
  - 主配置的聊天模型是 DeepSeek 官方模型时，先用 DeepSeek 自带的搜索（`DeepSeekNativeProvider`：用 Anthropic 兼容接口上的 `web_search_20250305` 服务端工具，跑一小轮 deepseek-v4-flash）；
  - 然后才是 DuckDuckGo 抓取。
  - Claude 和其他模型没有自带搜索这一档，直接落到 DuckDuckGo。
- **🔴 看的是主配置，不是这个对话的模型。** 自动顺序读的是 `llm_factory.primary_chat_endpoint()`。0.1.58 §6 以后，一个对话可以用别的模型。所以一个特意用本地 Ollama 的对话，如果主配置是 DeepSeek，它的搜索词（可能是本地模型从只在本机的记忆里拼出来的）今天就会发给 DeepSeek。D5 如果照这个写法加 Anthropic，同样的事会发生在 Claude 上。
- **在设置里选了 Tavily 或 SearXNG，就整个替换掉自动顺序**（`_AUTO_SEARCH` 只认空值和 `duckduckgo`）：所有搜索只发给那一家。这是用户特意做的选择，SearXNG 往往是为了隐私自己架的。这时那个 provider 出错，只报 `search failed: <category>`，不区分「被拦」。
- **被拦的报法：** 自动顺序里已经有了：DuckDuckGo 回人机验证页时抛 `SearchBlocked`，全部 provider 都失败时返回 `code: search_blocked`，并写明「这不是没有结果：什么都没搜」。T2 在 Claude 上的回答就是这样如实说的。
- **bench 里看到的：**
  - DeepSeek 上，K 线各轮的 T2、T3 都是 `provider: deepseek`，搜索成功；
  - Claude 上（K3 的「前」一轮，c2652b80），T2、T3 都是 `provider: duckduckgo`；
  - M1B 和 K1 前后对照里，Claude 上的 T2 多次被人机验证挡住。

## Hermes 用的是什么（⓪Plan 2026-10-20 查过）

- bench 里 Hermes 没有任何搜索 key。它的自动探测依次看：Tavily、Perplexity、Exa、Parallel、Keenable、Firecrawl 的 key，Nous 托管网关，SearXNG 地址，Brave 的 key，`ddgs` 包。这些都没有，最后落到「无 key 的免费档」：轮流匿名调用几家的公开接口（Exa 的公开 MCP、Parallel 的搜索 MCP、Firecrawl 和 Keenable 的免费档），见 `plugins/web/keyless_mcp.py`。
- 所以 Hermes 没碰到 DuckDuckGo 的人机验证：它根本不抓 DuckDuckGo，而是把查询匿名发给这几家的免费接口。T2、T3 它都是 3/3。
- **本卡不照搬这一点**（见「不做」）。

## 改哪些文件

1. **「模型自带的搜索」指这个对话这一轮的模型**（③Hands 审卡第 1 条）：
   - 自带搜索按这一轮的 adapter 选，也就是 `tool_loop._adapter_for_turn(conversation_id=…)`（`memory.turn_budget` 用的同一个），不再看 `primary_chat_endpoint()`。怎么把它带到 `web_search` 里由 ②Main 定。可以照 `tool_caller` 的做法，在同样两个入口设一个 contextvar。
   - 这一轮的模型是本地模型（`model_is_local`），或者不是那一家的模型，就不用任何一家的云端自带搜索。拿不到这一轮的模型时也不用（fail-closed）。
   - DeepSeek 那条路一起改。
2. **Claude 用 Anthropic 服务端的 web search**（新 `AnthropicNativeProvider`，写法照 `DeepSeekNativeProvider`）：
   - 请求放在模型层：新增 `arslan/llm/anthropic_search.py`，和 `deepseek_search.py` 并列。发一小轮请求，只带服务端工具 `web_search`。版本照官方文档：Opus 5.5/5/4.8/4.7/4.6、Sonnet 5.5/5、Sonnet 4.6 用 `web_search_20260209`，更老的模型用 `web_search_20250305`；开工时核对。
   - `max_uses` 定为 1 或 2，免得一次 `web_search` 变成很多次付费搜索。
   - 结果只从结构化的 `web_search_tool_result` 块里取，不从模型的文字里取；没有这种块，或者块里是错误对象，就大声失败。和 DeepSeek 那个一样。
   - **只在 K1b 那道门成立时用：** 必须是 Claude，并且 host 是 `api.anthropic.com` 或者列在允许清单里的透传代理。**直接调用** `AnthropicProvider._clears_server_side()` 或者两边共用的一个函数，不复制一份，免得两处走偏。其他走 Anthropic 协议的第三方端点，不保证支持服务端工具，不用这一档。
   - 用哪个模型、`max_tokens` 开工时定，PR 里写清每次搜索的成本：Anthropic 的搜索按次计费，再加这一小轮的 token。用量照 `_account_usage` 的做法计进工作预算和用量。
3. **搜索顺序（③Hands 审卡第 2 条）：**
   - **没选搜索服务**（`search_provider` 为空或 `duckduckgo`）：这一轮模型自带的搜索 → DuckDuckGo 抓取（best-effort）。
   - **选了 Tavily 或 SearXNG，只用它**（`search_provider_role` 为空或 `only`）：和今天完全一样，只发给这一家。**已经选过的老用户都落在这一档，行为不变。**
   - **选了 Tavily 或 SearXNG，作备选**（`search_provider_role = backup`）：这一轮模型自带的搜索 → 选的那一家。
   - **选了服务以后，两种用法都不会落到 DuckDuckGo。** 那一家失败，就报它失败。
   - 设置页：选 Tavily 或 SearXNG 时多一个选项「只用它」/「模型自带的搜索不可用时才用它」。新选的默认是「作备选」，这是用户要的用法；已存的选择不改（⓪Plan 定）。
   - 设置页说清楚：用模型自带的搜索时，搜索词经你的模型服务商发出（Anthropic 的搜索在 Anthropic 那边跑，照它的条款），并写每次搜索大概多少钱。
4. **被拦就说被拦，每个 provider 都一样（③Hands 审卡第 3 条）：**
   - Tavily、SearXNG 回 403 或 429，或者回人机验证页，也抛 `SearchBlocked` 或标成限流，不只是 DuckDuckGo。
   - **401 不算被拦：** 那是 key 被拒。报 `search_failed`，用现有的「key 被拒」分类（`net_pin.categorize`），告诉用户重新填 key。不能叫用户「配一个备选搜索服务」。
   - 全部失败时，`code` 是 `search_blocked`（全是被拦）或 `search_failed`（有别的失败），`error` 里逐个写 provider 和原因。这一条今天已经有，保持不变。
   - 模型拿到 `search_blocked` 时，给用户的回答要说「搜索被拦了，没搜到任何东西」，并说明可以在设置里配一个备选搜索服务；不能说「网上没有」，也不能凭记忆编。写进 K5 的 `web_search` 工具说明。
   - 页面上的活动行显示「搜索被拦」，不是「0 条结果」。

## 开工时定的（⓪Plan 2026-10-22）

- **Anthropic 那一小轮用 `claude-haiku-5-5`，工具版本用 `web_search_20250305`。** `web_search_20260209` 的列表里没有 Haiku；它多出来的动态过滤是让模型先跑代码筛结果，这一小轮只取结构化的结果块，用不上。`max_uses` 2，`max_tokens` 2048，思考关掉（Haiku 5.5 默认开着，会先花掉那 2048）。
- **成本：** 每次搜索 $0.01（官方价，$10 / 1,000 次；出错的那次不收），加上 Haiku 这一小轮的 token（每百万输入 $0.10、输出 $0.50）。计进工作预算和用量，和 DeepSeek 那条一样。
- **页面上的活动行：** 每个 `search_blocked` 的错误都以「search blocked:」开头，活动行据此显示「搜索被拦」。
- **给模型的说明：** K5 已经写进 `web_search` 的说明（`search_blocked` 时说搜索被拦、可以设备选、不凭记忆答），D5 不再改。

## 不做

- **不照搬 Hermes 的「无 key 免费档」。** 用户 2026-10-20 定了方向：v0.1.64 做成自动四层的第④层，只用官方的免 key 接口，默认关、首次问一次同意、本地模型的对话不走，见 [W1](W1-search-four-layers.md)。本卡不做。
- **不把 Anthropic 的服务端搜索直接挂在主循环上**，也就是不让主模型自己发服务端工具调用。那要在 K1 的原生轨迹里回放服务端工具的结果块（加密内容），风险更大。本卡用「一小轮专门搜索」的 provider，和 DeepSeek 的做法一致；挂主循环记进 v0.1.64 候选。
- 不改 `web_extract` 和浏览器。

## 验收

- **测试：**
  - `AnthropicNativeProvider.parse`：正常结果、没有结果块、错误对象、重复 URL、非 http 的 URL。照 DeepSeek 那组测试的样子。
  - 门：Claude 在官方 host 上用这一档；第三方 Anthropic 协议端点、非 Claude 模型不用。和 K1b 同一个判断（同一个函数），测试覆盖允许清单。
  - **按这一轮的模型选：**
    - 对话用 Ollama、主配置是 Claude：顺序里没有 `anthropic`；
    - 对话用 Claude、主配置是 DeepSeek：用 `anthropic`，不用 `deepseek`；
    - 对话用 Ollama、主配置是 DeepSeek：没有 `deepseek`（今天的问题）；
    - 拿不到这一轮的模型：没有任何自带搜索。
  - **顺序：**
    - 没选服务：Claude 是 Anthropic → DuckDuckGo；DeepSeek 是 DeepSeek → DuckDuckGo；
    - 存着 `search_provider=searxng`、没有新选项：顺序正好是 `[searxng]`；
    - `backup`：自带 → searxng，后面没有 DuckDuckGo。
  - **被拦：** Tavily 回 429 或 403、SearXNG 回人机验证页，都报 `search_blocked`，不报「没有结果」。Tavily 回 401 报 `search_failed`，提示重新填 key。
  - **Mutation：** 下面每一条去掉后，都要有测试抓到：
    - 去掉门；
    - 改回看主配置；
    - 去掉「备选在自带之后」；
    - 让选了服务后还落到 DuckDuckGo；
    - 去掉 Tavily 的被拦判断；
    - 把 401 当被拦。
- **M1：** Claude（sonnet-5）上 T2、T3 各 3 次，运行记录里搜索的 provider 是 `anthropic`；通过数不低于本卡合并前；贴每次搜索的成本。DeepSeek 上不变。
- 完成证据四项（`docs/sessions.md` §8）。

## 量级

产品代码约 +250 / −40 行，测试另算。

## 风险与回退

- **风险：花费。** Claude 用户每次搜索多一小轮请求，外加 Anthropic 的按次计费；`max_uses` 封顶 1–2 次。PR 里写成本；M1 贴实际数字。
- **风险：第三方端点。** 只在官方 host 或允许清单上用；其他端点照旧，不会因为这张卡报错。
- **风险：本地对话的搜索变少。** 用本地模型的对话不再用云端自带搜索，只剩 DuckDuckGo 或用户选的服务。这是有意的：本地对话的搜索词不该发给它没选的云端模型厂商。
- **回退：** revert 这一个 PR，就回到今天的顺序。

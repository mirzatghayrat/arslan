# D5 搜索：先用模型自带的搜索，key 作备选，被拦就说被拦

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 应该（用户 2026-10-20 要求出这张卡，版本和分级由 ⓪Plan 定，理由见下） |
| 依赖 | — |
| 合并位置 | **不进 K 线串行链。** 改 `server/registry/search_providers.py`、`server/registry/executors.py` 的 `web_search` 那一段、新增 `arslan/llm/anthropic_search.py`、设置页的搜索一节。都不是 K 线的热点文件；K5 要改工具说明，D5 先合就让 K5 照新的写 |
| 推动的门槛 | §5.1 T2、T3（在 Claude 上）；R63 的「对 Claude Code」对比 |
| 分支 | `claude/0163-d5-search-native-first` |
| 迁移号 | 无（设置项沿用 `search_provider` / `search_api_key` / `search_base_url`） |
| 来源 | 2026-10-20 bench：T2、T3 在 Claude 上碰到 DuckDuckGo 的人机验证；用户要求查清 Hermes 用的是什么、出这张卡 |

## 为什么放 v0.1.63 的「应该」（⓪Plan 定）

- **这是用户今天就会碰到的。** 用户默认用 Claude（claude-sonnet-5），而 Arslan 在 Claude 上的搜索只有一条路：抓 DuckDuckGo 的 HTML 页面（`DuckDuckGoHtmlProvider`，自己就标着 `best_effort`）。这个页面时好时坏，被拦时整个搜索就没了。
- **R63 要在 Claude 上和 Claude Code 比。** Claude Code 搜索走的是 Anthropic 服务端的 web search。T2、T3 都靠搜索，不改这一点，那两题输掉的原因就不是内核。
- **改动小，风险低：** 照已有的 `DeepSeekNativeProvider` 的写法再加一个 provider，再把「自动顺序」改一下。不碰 K 线文件，可以在 K 卡之间的空档合。
- **为什么不是「必须」：** DeepSeek 用户已经走 DeepSeek 自带的搜索（bench 里全部 `provider: deepseek`、都成功）；被拦时已经报 `search_blocked`，不会冒充「找不到」。所以这不是坏掉的功能，是 Claude 用户的搜索不稳。

## 今天的情况（main `6e17afc3`，⓪Plan 核过）

- **自动顺序**（`executors._auto_search_providers`）：
  - 聊天模型是 DeepSeek 官方模型时，先用 DeepSeek 自带的搜索（`DeepSeekNativeProvider`：用 Anthropic 兼容接口上的 `web_search_20250305` 服务端工具，跑一小轮 deepseek-v4-flash）；
  - 然后才是 DuckDuckGo 抓取。
  - Claude 和其他模型没有自带搜索这一档，直接落到 DuckDuckGo。
- **在设置里选了 Tavily 或 SearXNG，就整个替换掉自动顺序**（`_AUTO_SEARCH` 只认空值和 `duckduckgo`）。这时 Claude 用户反而用不上模型自带的搜索；那个 provider 出错时，只报 `search failed: <category>`，不区分「被拦」。
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

1. **Claude 用 Anthropic 服务端的 web search**（新 `AnthropicNativeProvider`，写法照 `DeepSeekNativeProvider`）：
   - 请求放在模型层：新增 `arslan/llm/anthropic_search.py`，和 `deepseek_search.py` 并列。发一小轮请求，只带服务端工具 `web_search`。版本照官方文档：Opus 5.5/5/4.8/4.7/4.6、Sonnet 5.5/5、Sonnet 4.6 用 `web_search_20260209`，更老的模型用 `web_search_20250305`；开工时核对。
   - 结果只从结构化的 `web_search_tool_result` 块里取，不从模型的文字里取；没有这种块，或者块里是错误对象，就大声失败。和 DeepSeek 那个一样。
   - **只在 K1b 那道门成立时用：** 必须是 Claude，并且 host 是 `api.anthropic.com` 或者列在允许清单里的透传代理（`_clears_server_side()` 的判断）。其他走 Anthropic 协议的第三方端点，不保证支持服务端工具，不用这一档。
   - 用哪个模型、`max_uses` 和 `max_tokens` 开工时定，PR 里写清每次搜索的成本：Anthropic 的搜索按次计费，再加这一小轮的 token。用量照 `_account_usage` 的做法计进工作预算和用量。
2. **新的自动顺序：**
   - 模型自带的搜索（DeepSeek 或 Anthropic，看聊天模型是哪家）；
   - → 设置里配好的搜索服务（Tavily 的 key，或 SearXNG 的地址），**改成备选**，不再整个替换自动顺序；
   - → DuckDuckGo 抓取（best-effort）。
   - 设置页的搜索一节改成「备选搜索服务」，说明它什么时候用：模型自带的搜索不可用或失败时。
   - 已经选了 Tavily 或 SearXNG 的老用户，设置不动，含义变成备选。发布说明写一句。
3. **被拦就说被拦，每个 provider 都一样：**
   - Tavily、SearXNG 回 401、403 或 429，或者回人机验证页时，也抛 `SearchBlocked` 或标成限流，不只是 DuckDuckGo。
   - 全部失败时，`code` 是 `search_blocked`（全是被拦）或 `search_failed`（有别的失败），`error` 里逐个写 provider 和原因。这一条今天已经有，保持不变。
   - 模型拿到 `search_blocked` 时，给用户的回答要说「搜索被拦了，没搜到任何东西」，并说明可以在设置里配一个备选搜索服务；不能说「网上没有」，也不能凭记忆编。写进 K5 的 `web_search` 工具说明。
   - 页面上的活动行显示「搜索被拦」，不是「0 条结果」。

## 不做

- **不照搬 Hermes 的「无 key 免费档」**（匿名调用 Exa、Parallel、Firecrawl、Keenable 的公开接口）。用户的查询会发给用户没有账号、也没同意过的第三方，而且这些免费档没有约定、随时可能限流或下线。要不要做是隐私上的取舍，记进 README §8 的 v0.1.64 候选，由用户定。
- **不把 Anthropic 的服务端搜索直接挂在主循环上**，也就是不让主模型自己发服务端工具调用。那要在 K1 的原生轨迹里回放服务端工具的结果块（加密内容），风险更大。本卡用「一小轮专门搜索」的 provider，和 DeepSeek 的做法一致；挂主循环记进 v0.1.64 候选。
- 不改 `web_extract` 和浏览器。

## 验收

- **测试：**
  - `AnthropicNativeProvider.parse`：正常结果、没有结果块、错误对象、重复 URL、非 http 的 URL。照 DeepSeek 那组测试的样子。
  - 门：Claude 在官方 host 上用这一档；第三方 Anthropic 协议端点、非 Claude 模型不用。和 K1b 同一个判断，测试覆盖允许清单。
  - 自动顺序：Claude 是 Anthropic → 备选 → DuckDuckGo；DeepSeek 是 DeepSeek → 备选 → DuckDuckGo；配了 Tavily 时，自带搜索失败才轮到它。
  - 被拦：Tavily 回 429 / 403、SearXNG 回人机验证页，都报 `search_blocked`，不报「没有结果」。
  - Mutation：去掉门、去掉「备选在自带之后」、去掉 Tavily 的被拦判断，各自被测试抓到。
- **M1：** Claude（sonnet-5）上 T2、T3 各 3 次，运行记录里搜索的 provider 是 `anthropic`；通过数不低于本卡合并前；贴每次搜索的成本。DeepSeek 上不变。
- 完成证据四项（`docs/sessions.md` §8）。

## 量级

产品代码约 +200 / −30 行，测试另算。

## 风险与回退

- **风险：花费。** Claude 用户每次搜索多一小轮请求，外加 Anthropic 的按次计费。PR 里写成本；M1 贴实际数字。
- **风险：第三方端点。** 只在官方 host 或允许清单上用；其他端点照旧，不会因为这张卡报错。
- **回退：** revert 这一个 PR，就回到今天的顺序。

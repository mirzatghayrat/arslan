# spec ① 搜索能力(甲:零 key 兜底 · 乙:Brave 升级) —— 任务书

**状态**:🟡 **部分已批(用户 2026-08-08)。两个拍板项仍开着 —— 见 §3。**
**前置**:🔴 **必须 rebase 在 spec ⓪ 之上**,两者都改 `server/registry/executors.py`
的搜索路径。接缝见 §6.1。⓪② 并行,① 排在 ⓪ 落 main 之后。

> **用户 2026-08-08 裁决**
> - **ddgs 弃,改站「自己实现」**。用户原判的决定性理由是**打包便利**;
>   我的反证(`primp` 自带 HTTP 栈 ⇒ 七条钉扎全部失效)**在网络策略一致性上压过它**,改判成立。
> - 🔴 **修正我的一句错话**:「DDG HTML 实测不通则答案自动变 ddgs」**不成立 —— 没有自动**。
>   实测不通就**回来重拍**;ddgs 要进来得先过**两道闸**:
>   ① 许可证回源核(`ddgs` + `primp` + `lxml`),② 二进制成本用户点头。
> - 限流语义映射 + 退避 + `toolHumanize` **不许吞状态码** —— **批**。
> - **仍开着**:§3 拍板项①(真实抱怨是哪一种)、§3 拍板项③(乙 Brave 这轮做还是下轮)。

**一句话**:今天搜索**只有一个 provider、必须一个付费 key、失败后用户看不到原因**,
而模型在 key 失效之后**仍然把它当第一选择用掉了 138 次**。

---

## 0. 前置核实(2026-08-07 亲核 `5f2b083b`,带 FILE:LINE)

### 0.1 下拉框只有一个选项,而且是结构性的

`server/registry/search_providers.py:45-46`:
```python
_PROVIDERS: dict[str, type[SearchProvider]] = {"tavily": TavilyProvider}
_DEFAULT = "tavily"
```
`:49-54 get_provider` 对任何别的 key 抛 `ValueError`;`:57-59 list_providers` 就是
`server/api/settings.py:146-149 GET /settings/search-providers` 喂给 Settings 下拉的东西。
⇒ **「可换 provider」这个架构在,里面只有一件。**

### 0.2 🔴 provider 选择永远不执行 —— gate 在它前面

`server/registry/executors.py:226-233`:
```python
async def _search_provider():
    """Build the configured provider, or None when no key is set."""
    async with AsyncSessionLocal() as db:
        key = await settings_service.get_decrypted(db, "search_api_key")
        name = (await settings_service.get_settings(db)).get("search_provider", "")
    if not key:
        return None
    return get_provider(name, api_key=key)
```
DB 读**先**发生(key 和 provider 名都读了),`if not key` 才 return。
⇒ 关键结论成立:**gate 问的是「有没有 key」,不是「所选 provider 需不需要 key」**。
**任何 keyless provider(自建 SearXNG)在这个结构下不可达** —— 它会在被构造之前就被判死。

`:298-318 WebSearchExecutor.execute` 里 `provider is None` → 
`"web search is not configured (no API key set)"`。

### 0.3 「要单独付费 key」这句抱怨被产品自己的文案反驳,而那句文案是死的

`web/src/locales/en.json:413`:
> `"search_api_key_hint": "Stored encrypted. Separate from your LLM key. Get a free key at tavily.com."`

**但 `web/src/components/settings/SearchToolsSection.tsx:113-115` 渲染的是一句硬编码英文**:
> "Allocated to standard spawns carrying \"Web Search\" capability chips. Ensure live indices limits are sufficient."

它不走 `t()`。`:102` 的 `placeholder="Enter search provider key..."` 同样硬编码。
⇒ **`search_api_key_hint` 这个键有六语翻译、没有任何人渲染它。**
「免费 key」这行字从来没人见过,而**在场的那句话既不是本地化的、也没说清要去哪拿 key**。

⚠️ 如果真实抱怨是「免费额度用完了」而不是「要付费」,本轮的动机段要照那个写。
**这条我没有独立证据分辨,不许替用户拍。** 见 §3 拍板项①。

### 0.4 错误分类保留了状态码,但一路上被吃掉三次

`executors.py:215-223`:
```python
def _categorize_exc(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):  return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):   return f"http {exc.response.status_code}"
    if isinstance(exc, httpx.HTTPError):         return "network error"
    return "unexpected error"
```
状态码**在**(429 → `"search failed: http 429"`)。缺的是:

1. **语义映射**:429 / 402 / 403 → 限流 / 额度耗尽 / 坏 key。今天三者同一句。
2. **退避**:`:313-318` 是一次 try,**零重试、零 backoff**。
3. 🔴 **前端把一切换成一句通用文案**:`web/src/lib/toolHumanize.ts:41-46`
   ```ts
   case 'web_search':
     return s.status === 'error' ? t('activity.search_fail') : …
   ```
   `en.json:356` `"search_fail": "A search didn't go through — retrying differently"`。
   ⇒ **429 做了分类也没人看得见。分类和文案必须同一轮改,否则等于没改。**
   ⚠️ 顺带:那句文案承诺了 "retrying differently",而**搜索路径没有任何重试**
   (§0.4 第 2 条)。真正会不会再试取决于模型下一步,代码不保证。
   这是一句**承诺了我们不保证的事**的文案。

⚠️ `_categorize_exc` 的**分支顺序是承重的、且没有注释说明**:
`httpx.HTTPStatusError` 和 `httpx.TimeoutException` **都是** `httpx.HTTPError` 的子类,
把 `:221` 那行上移会把一切塌成 `"network error"`。本轮改它必须留下这条注释 + 一条测试。

### 0.5 SSRF 硬化全在 `executors.py` 里,而搜索路径完全没走它

`executors.py` 私有的一整套(逐条读过):

| 位置 | 做什么 |
|---|---|
| `:87` | `return (not ip.is_global) or ip.is_multicast` —— 允许清单式谓词。docstring `:82-85` 解释为何不枚举坏网段:CGNAT `100.64.0.0/10`(Tailscale)谁都不匹配 |
| `:94-136 _resolve_pinned` | 解析**一次**、校验**每个**答案、钉住第一个、不可解析 fail-closed(FU-1 DNS rebinding) |
| `:139-151 _ascii_host` | IDN/统一码归一 |
| `:154-183 _pinning_disabled_by_proxy` | 唯一的降级格 |
| `:186-212 _pinned_request_args` | 改写成 IP 字面量 + `Host` 头 + `sni_hostname` |
| `:239-256 _build_client` | `follow_redirects=False`,刻意 |
| `:259-295 _fetch_text` | 手写重定向循环,`_MAX_REDIRECTS = 5`,**每跳重新钉** |

🔴 **而搜索是裸 client**:`search_providers.py:30`
```python
async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
```
零钉扎。今天目的地是硬编码常量(`:24 _URL`)所以风险有限,**但 SearXNG 一落地,
目的地就变成用户填的字符串** —— 那一刻这条裸路径就是个洞。

🔴 **复用有循环 import**:`executors.py:24` 已经 import `search_providers`,
所以 `search_providers` 不能反向 import `executors`。

### 0.6 ddgs 的依赖树 —— 会往冻结包里塞两个新的二进制扩展

查 PyPI:`ddgs 9.14.4` 本体是 `py3-none-any`,但依赖
- **`primp>=1.2.3`** —— Rust 写的 HTTP 客户端,**无纯 py 轮**,macOS 只有 abi3 二进制轮;
- **`lxml>=4.9.4`** —— C 扩展,发 `universal2` / `x86_64` 轮,**无纯 py 轮**;
- 加 `httpx[brotli,http2,socks]`、`fake-useragent`、`click`。

两者**都不在** `pyproject.toml`,**也不在** `packaging/arslan-server.spec`
(本轮亲核:grep `ddgs|primp|lxml` 两个文件零命中)。
⇒ **新增两个 Mach-O 进冻结包,每个都要签名**,并且要按
[[arslan-license-verify-at-source]] 回源核许可证(PyPI 字段不作依据)。

⚠️ 更要紧的一条:**`primp` 是它自己的 HTTP 栈**,不是 httpx。
⇒ ddgs 的网络请求**在结构上无法被我们钉扎**(§0.5 那一整套对它不适用)。

⚠️ 上一轮我第一次查 lxml 的 macOS 轮报「0 个」,那是**我的过滤器错**
(只匹配 `arm64`,而 lxml 发 `universal2`),实际有 16 个。别把这个错抄进任何结论。

### 0.7 P1b 诊断:模型不是「不爱用搜索」,是**用了一件死工具,而退路免费预装在同一份提示里**

四个候选假说,**三个排除**:

- **路由**:`server/orchestrator/router.py:34-94 _SYSTEM` 提 web_search **三次**、
  memory/recall **零次**,还明写「searching, looking things up online … is `answer`」⇒ **亲 web**。
- **工具顺序**:`server/orchestrator/arslan.py:1716-1718` 是字面元组,
  `web_search` **index 0**、`recall` index 3;
  `server/orchestrator/tool_loop.py:942-950` 按序 append ⇒ **web 在最前**。
- **tool_intent 预跑**:只可能强制 web_search,且**在 host 应答路径不跑**
  (`force_tools=True` 唯一调用者是 `server/orchestrator/spawn_loop.py:52`)。
  ⚠️ 反向不对称值得记一笔:**spawn 有确定性亲 web 预跑,Arslan 自己的聊天没有。**
- **工具描述**:唯一成立的一点 —— `arslan.py:1711-1712` recall 的描述带
  `"…for relevant context before answering."`,读作常驻指令。
  但系统提示给 web **三大块**(`arslan.py:201-216 _WEB_TOOL_GUIDANCE` 含
  「you MUST actually CALL web_search」、`:222-233 _CAPABILITY_SELF`、
  `tool_loop.py:895-905 _NATIVE_EFFICIENCY`),给 memory **零块**。

🔴 **「没配置就不在 schema 里」也不成立**:`executors.py:818-822` `EXECUTORS` 是
import 时的静态 dict,**没有任何配置检查**;`arslan.py:1716-1718` 只按
`if k in EXECUTORS` 过滤。⇒ **模型永远看得到、永远能调**,配置只在 `execute()`
里查(`:309-312`)。实测**确实调了 138 次**。

⇒ **比「工具缺席」更坏**:烧掉一次工具调用,拿回一句「没配置」,然后
`arslan.py:214-215` 明确告诉它「说不清就用你已知的答」—— 而第二大脑已经免费装在同一份提示里。
**动机段照这个写:这不是偏好问题,是死工具 + 预装退路。**

---

## 1. 范围

### 甲 —— 零 key 兜底 provider(默认可用)

目标:**全新安装、不填任何 key,`web_search` 就能返回结果。**

### 乙 —— Brave Search 作为可选升级

官方 API 契约、免费档月 2000 次查询。填了 key 就用它。

### 共同的三件(不做这三件,甲乙都只是换了个失败方式)

1. **「要不要 key」下沉到 provider 自己**,从 `_search_provider` 的 `if not key` 拿掉(§0.2)。
2. **返回结果必须标注本次由哪个 provider 服务**,不许静默降级(用户硬要求)。
3. **错误语义 + 前端文案同一轮改**(§0.4 第 3 条)。

### 不做

- **不打包 SearXNG**(AGPL,见 [[arslan-license-verify-at-source]])。
  用户在 Settings 填自建实例地址不触发这条。
- **不做搜索结果缓存**、不做跨 provider 结果合并/去重。
- **不改 `web_extract`**(它不走 provider 层)。
- **不动 `_WEB_TOOL_GUIDANCE` / `_CAPABILITY_SELF` 的提示词配比**。
  §0.7 说明了 web:memory = 3 块 : 0 块,**这条单独立项**,不在本轮 —— 改提示词配比会同时移动
  一堆已存在的行为,和本轮的「让工具真的能用」互相污染,合在一起就分不出谁修好了什么。

---

## 2. 设计

### 2.1 provider 契约扩一条:`requires_key`

`search_providers.SearchProvider` 加一个类属性(`requires_key: bool`)+
一个统一的构造入口。`_search_provider()` 改成:

```
读 settings(provider 名 + key + 自建 base url)
  → 按名字取 provider 类
  → 它说不需要 key ⇒ 直接构造
  → 它说需要 key 而 key 缺 ⇒ 返回一个「缺 key」原因(不是裸 None)
  → key 在但解不开 ⇒ 返回「解不开」原因(← 这一半是 spec ⓪ 的产物)
```

🔴 **返回类型从 `Provider | None` 变成带原因的结果**。这是 ⓪ 和 ① 在同一个函数里的接缝(§6.1)。

### 2.2 甲的实现:自己实现 DDG HTML 兜底,不引入 ddgs

**决定(取舍写在这里,用户可否决 —— §3 拍板项②)**:

| | 引入 `ddgs` | 自己实现(我倾向) |
|---|---|---|
| 冻结包 | +2 个 Mach-O(`primp` Rust、`lxml` C),各自要签名 | +0 |
| 许可证工作 | 两个新依赖回源核 | 无 |
| SSRF 钉扎 | 🔴 **做不到** —— `primp` 是它自己的 HTTP 栈(§0.6) | ✅ 走我们的钉扎 client |
| 解析脆性 | 它替我们承担 | **我们承担** |
| 维护承诺 | 上游自称 educational purposes only | 我们自己的一小段代码 |

我倾向自己实现,主要理由是第三行:**一个自带 HTTP 栈的第三方搜索客户端,
我们那一整套 SSRF/钉扎硬化对它一行都不生效**,而我们正要在 §2.3 把 SearXNG
(用户填的地址)接进来。为了一个自称「仅供学习」的上游,换掉我们唯一的网络边界控制,
不划算。代价(HTML 解析会碎)由 §2.4 的**出处标注**变成可见的,而不是静默的。

甲的硬要求(用户原话「必须如实披露」):
- 界面**明说**它抓 HTML、会被限流、只适合兜底;
- 它服务的每一次结果**带上出处标注**;
- **不许**把它包装得像一个正式 provider。

### 2.3 SearXNG:钉扎方向按用户修正来写

🔴 **用户修正过原方向,照修正的写**:

> 用户亲手在 Settings 填的 base host **允许私网** —— 那是人配置的,
> **模型能控制的只有 query,不是目的地**;**但逐跳重定向仍校验,跳离该 host 一律拒绝。**

⇒ 具体成三条:
1. 用户填的 host **豁免** `not ip.is_global` 那条谓词(否则 192.168.x / 100.64.x ——
   自建 SearXNG 最可能的两个位置 —— 全被拒)。
2. 豁免**只对那一个 host**,由 Settings 里的字符串定义,**模型无法影响**。
3. **重定向逐跳仍校验**,任何跳到该 host 之外的一律拒绝(复用
   `_fetch_text:259-295` 的每跳重钉逻辑)。

### 2.4 出处标注(用户硬要求)—— 一条贯穿三层的线

后端:`WebSearchExecutor` 的返回加 `provider` 字段。
前端:`toolHumanize.ts` 的 `activity.search*` 文案带上 provider 名。
🔴 **同时删掉 `search_fail` 那句「retrying differently」**(§0.4 末),
它承诺了代码不保证的事。

### 2.5 SSRF helper 复用的形状:挪进共享模块

**决定(用户授权我定,但要求「两处行为一致有测试钉住」)**:

新开 `server/registry/net_pin.py`,把 `executors.py` 的
`_is_blocked_ip` / `_resolve_pinned` / `_ascii_host` / `_pinning_disabled_by_proxy` /
`_pinned_request_args` / `_build_client` / `_fetch_text` **挪进去**,
`executors.py` 和 `search_providers.py` 都从它 import。

为什么不是复制:一个安全控制有两份副本,就有两份会分头漂移的副本 ——
而 §0.5 那七条里每一条都是**被具体攻击推导出来**的(FU-1 那段注释写得很清楚)。
为什么是第三个模块而不是让 `search_providers` import `executors`:
`executors.py:24` 已经反向依赖了(§0.5 末),会成环。

**测试钉住(用户硬要求)**:一组**参数化**测试,同一批用例同时跑在
「web_extract 路径」和「搜索路径」上,断言两边的判定**逐条相同**。
mutation:只放宽其中一条路径,测试必须红。

### 2.6 错误语义 + 退避

- `_categorize_exc` 扩成语义层(保留原函数与它承重的分支顺序 + 补上那条注释):
  429 → 限流、402/403 → 额度/坏 key、其他 4xx → 请求问题、5xx/超时 → 上游。
- 限流(429)**加一次**指数退避重试,上限硬编码,**不许无界**。
- 语义一路送到 `toolHumanize.ts`,每一类一句独立文案,六语。
- 🔴 **坏 key / 额度耗尽必须能反映到 Settings**,不能只活在一次工具调用的错误里 ——
  否则用户下次打开 Settings 看到的还是「配好了」。这正是 spec ⓪ 三态里的**第三态
  「设了但连不通」**,由本轮填(§6.1)。

---

## 3. 拍板项 —— **②已裁决(自己实现);①③ 仍开着(用户 2026-08-08 未答)**

### ① 真实抱怨是「要付费」还是「免费额度用完」? → 🟡 **仍开着**

`en.json:413` 明写 tavily 有免费 key(§0.3),但**那句话从来没被渲染过**。
- **A**:抱怨的实质是「还要再注册一个服务、再拿一个 key」⇒ 甲(零 key 兜底)是正解,
  文案重点放在「开箱即用」。
- **B**:抱怨的实质是「免费额度耗尽」⇒ 重点应是**额度可见性**(§2.6 的 402/429 语义 +
  Settings 可见),甲只是附带。

**我不替你拍。** 两个答案会让本轮的重心落在不同地方。
(不管哪个,`SearchToolsSection.tsx:113-115` 那句死英文都要修。)

### ② ddgs 二进制成本:接受签名成本 vs 纯 py 自己实现 → 🟢 **自己实现**

§2.2 那张表 + 我的倾向。**用户 2026-08-08 改判采纳**,决定性理由是那张表的第三行
(`primp` 自带 HTTP 栈 ⇒ 我们的钉扎对它全部失效),它压过了原本的打包便利考虑。

🔴 **没有「自动回退到 ddgs」这条路**:若 DDG HTML 端点实测不通,
**回来重拍**,不许就地换成 ddgs。ddgs 进来要过两道闸:
① `ddgs`/`primp`/`lxml` 三个许可证**回源核**(见 [[arslan-license-verify-at-source]],
PyPI 字段不作依据);② 二进制成本**用户点头**。
(这段是用户对我原文一句错话的修正 —— 我写了「实测不通则答案自动变 ddgs」,
**「自动」是错的**:一个被否掉的选项不会因为首选失败就自己复活。)

### ③ 乙(Brave)这一轮做,还是先只做甲? → 🟡 **仍开着**

- **A(我倾向)**:一起做。乙的工作量很小(§2.1 的契约一改,加一个 provider 类就是几十行),
  而它是**唯一带官方契约的那个选项** —— 甲永远只能是兜底。
- **B**:先只做甲,乙下一轮。理由会是「减少一次真机验收面」。

⚠️ **这条不阻塞 ① 开工**:§2.1 的 provider 契约(`requires_key` 下沉)和 §2.5 的
`net_pin.py` 搬迁无论哪个答案都要做,而它们是 ① 的大头。
乙只是「再加一个 provider 类」,可以在本轮后半段插入。**但 ① 收尾前必须有答案**,
否则「甲乙都做」这条原始范围就被我单方面缩小了。

---

## 4. 验收(写死,实现轮照抄)

1. **全新安装、零 key**:`web_search` 返回非空结果,且结果里带 `provider` 出处。
2. **keyless provider 结构上可达**:一条测试直接断言选中一个 `requires_key=False`
   的 provider 时 `_search_provider` **不**因为 key 为空而短路。
   mutation:把 `if not key` 加回去,必须红。
3. **两条路径的 SSRF 判定逐条相同**(§2.5 的参数化测试)。
   mutation:只放宽搜索那一侧,必须红。
4. **SearXNG 私网豁免只对那一个 host**:
   - 用户填 `http://192.168.1.10:8080` ⇒ 允许;
   - 同一次请求重定向到 `http://192.168.1.11` ⇒ **拒绝**;
   - 模型的 query 里放一个私网 URL ⇒ **不影响目的地**(query 不是目的地)。
5. **429 有语义、有一次退避、有独立文案**;六语齐、逐语言非空。
6. **`search_fail` 那句「retrying differently」在六语里都不存在了**
   (断言缺席 —— 这一条可以查源码,因为它断言的是**缺席**;见
   [[arslan-assert-behaviour-not-source]] 的分界)。
7. **`SearchToolsSection` 渲染的是本地化文案**,并断言 `search_api_key_hint`
   **真的被渲染**(行为断言,渲染组件读屏幕,不是 grep 源码 —— 上一轮同一根病犯过三次)。
8. **降级可见**:兜底 provider 服务的一次搜索,前端能看到它是兜底,
   **测试断言那段字在屏幕上**。
9. `_categorize_exc` 的**分支顺序**有测试钉住(`HTTPStatusError` 不塌成 `network error`)。
10. **打包版探针**:`packaging/fresh_install_check.py` 加一条 —— 全新安装、零 key、
    `web_search` 能返回。🔴 探针要与真实消费者同尺(走 API,不直接调 executor;
    见 [[arslan-probe-must-match-consumer]])。

---

## 5. 风险与未覆盖面

1. **HTML 兜底会碎**(DDG 改版就碎)。缓解:出处标注让它可见;失败走 §2.6 的语义层;
   **不为它写「保证可用」的文案**。
2. **兜底会被限流**,而限流在兜底路径上是常态不是异常。⇒ 文案必须先说这件事。
3. **未覆盖:提示词配比**(web 三块 : memory 零块,§0.7)。单独立项。
4. **未覆盖:spawn 侧的亲 web 预跑不对称**(`spawn_loop.py:52`)。登记,不做。
5. **未覆盖:额度/用量的主动查询**。本轮只做「失败时说清是额度问题」,
   不做「还剩多少次」——那要各家 provider 的用量端点,面比这轮大。
6. `net_pin.py` 的搬迁是**纯移动 + 改 import**,但它移动的是全项目最敏感的一段。
   ⇒ 搬完必须跑**全量**(不是只跑附近;见 [[arslan-night-abc-batch]] 那条
   「只跑改动附近 = 只问会同意我的证人」)。

---

## 6. 接缝

### 6.1 🔴 与 spec ⓪ 在同一个函数里

`_search_provider()`(`executors.py:226-233`)会被两轮先后改:

| | ⓪ 拥有 | ① 拥有 |
|---|---|---|
| `if not key` gate | **拆成「没设置 / 解不开」两态** | 再拆出「provider 说不需要 key」这一支 |
| `get_provider(name, …)` | 不动 | **让它真的跑到**(§2.1) |
| `_categorize_exc:215-223` | 不动 | **语义化**(§2.6) |
| `toolHumanize.ts:41-46` | 不动 | **改**(§2.4) |
| 「设了但连不通」第三态 | 留形状 | **填**(§2.6 末) |

⇒ **⓪ 先落 main,① rebase 在它之上。** rebase 之后旧验证作废,必须重跑全量 + CI
(run id 照 [[ci-green-claims-must-cite-actions-run]] 引)。

### 6.2 与 ②③ 无重叠

② 动 `routing.py` / 三个 `_get_adapter()` / usage 前端;③ 动 `server/mcp/*`。
与本轮零交集,可真并行。

---

## 7. 尚无证据、未声称已验

- **「用户的抱怨是哪一种」未定** —— §3 拍板项①。我有反证据(`en.json:413` 说有免费 key),
  **没有**证据说明抱怨的具体内容。不许替你拍。
- **Brave 免费档「月 2000 次」是引用官方公开档位,本轮没有实测过**。
  实装前要回源核一次现价(定价页会变)。
- **DDG HTML 端点今天能不能用,本轮没有实测**。§2.2 的倾向是**架构理由**
  (钉扎 + 冻结包),不是「我试过它能用」。**动手第一件事就是实测它。**
  🔴 **实测不通 ⇒ 回来重拍,不是自动换 ddgs**(用户 2026-08-08 修正,见 §3 拍板项②)。
- **`ddgs`/`primp`/`lxml` 的许可证未回源核**(只查了 PyPI 的依赖关系)。
  按 [[arslan-license-verify-at-source]],PyPI 字段不作依据 —— ddgs 若日后重新进入议程,
  这是两道闸里的第一道。
- **兜底 provider 的召回质量没有任何测量**。它是兜底,不承诺质量;
  但「不承诺」要写进界面,不能只写进 spec。
- **本轮一行代码都还没写。**

---

关联:[[arslan-four-specs-recon-2026-08-07]]、[[arslan-allowlist-not-blacklist]]、
[[arslan-license-verify-at-source]]、[[arslan-probe-must-match-consumer]]、
[[arslan-assert-behaviour-not-source]]、[[arslan-night-abc-batch]]、
[[arslan-second-brain-frontend-brief]]。

# spec ② 分任务模型指派 + fallback 链 —— 任务书

**状态**:🟢 **已批(用户 2026-08-08)。vision 拍 B ⇒ 槽位共四个。一个拍板项仍开着(§3②)。**
**并行性**:与 ⓪① 零文件重叠(它们在 `executors.py` / `crypto.py`,本轮在
`llm_factory.py` / `routing.py` / 三个 `_get_adapter()` / usage 前端),可真并行。
开工顺序里 **① 与 ② 并行**。

> **用户 2026-08-08 裁决**
> - 三个真实槽位**复用 `build_synthesis_adapter` 形状** —— **批**
> - **不重写打分函数** —— **批**
> - **vision 拍 B**(显式 `vision_config_id`):**显式优于猜测,与其它槽形状一致**
> - `StreamUsage` 带上 `buckets`/`model`,聊天页有「谁答的」—— **批**
> - 🔴 顺带:`server/services/llm_factory.py:22-28` 那句 Phase A docstring
>   **在 ② 动那个文件时一并修掉** —— 它是「注释描述没发生的事」**第五例**,
>   **别让它活过这轮**

**一句话**:提议的六个槽里**两个不存在**、一个**没有单一调用点**、三个是一行钩子;
而**静默换模型今天就已经在发生**,可见性不是新要求,是把已存在的不可见修掉。

---

## 0. 前置核实(2026-08-07 亲核 `5f2b083b`,带 FILE:LINE)

### 0.1 已有两个槽,而且已经有一套现成的槽位形状

`server/services/settings_service.py:21` `_PLAIN_KEYS` 里有
`synthesis_config_id` 和 `embedding_config_id`;`server/schemas.py:35-36` / `:62-63` 出入参。

🔵 **`server/services/llm_factory.py:44-62 build_synthesis_adapter()` 就是槽位的参考实现**:
```
读 settings 的 <task>_config_id → 空 ⇒ return None(调用方保持默认)
                                 → 命中一个 provider_config ⇒ 造那一个 adapter
```
**「返回 None 表示不覆盖」这个形状是对的,新槽照抄它,不要发明第二种。**
另一个消费者 `server/services/embedding_service.py:84-89` 是同一个形状(带 `"local"` 特例)。

### 0.2 🔴 六个提议槽里两个**不是 LLM 调用**

- **`web_extract`**:`server/registry/executors.py:322-347 WebExtractExecutor.execute`
  是纯 HTTP —— `:338 _fetch_text(url)` → `:347 return {…text[:limit]}`,
  **没有 adapter、没有模型**。另两个调用者 `server/services/extract.py`、
  `server/services/ingest.py` 同样非 LLM。
- **「审批」**:`server/orchestrator/tool_loop.py:481-482 confirm_command` 是**人**的
  WebSocket 往返(`server/ws/arslan.py:239-267`);风险分级是确定性的 ——
  `server/services/command_policy.py:74` 自己写着 "Deterministic; no IO, no LLM";
  打字确认是词典匹配(`server/orchestrator/confirm_lexicon.py:55`)。

⇒ **这两个槽给它们指派模型无处可指。** 不做,不是延后。

### 0.3 🔴 vision 没有单一调用点,而且撞上一个**刻意的**设计决定

图块在 `server/orchestrator/arslan.py:434-456 build_user_blocks` 组装,
交给 `:1055-1064 run_native`。而 `run_native` **每轮只建一个 adapter**:
`tool_loop.py:1134 adapter = _get_adapter()` → `:50-52 build_adapter(role="execute")`,
且 `run_native` 的签名(`:1106-1122`)**没有 images 参数、没有 role 参数** ——
**它看不到这一轮有没有图**。第三处 `server/orchestrator/dispatcher.py:76-78` 同样。

⇒ 要做 vision 槽 = 改三处 + 给 `run_native` 一个新的入参。

🔴 **并且撞上一条刻意的设计决定**,原文在 `server/orchestrator/vision_errors.py:3-8`:
> "we deliberately do NOT gate on the `vision` capability flag. That flag is hardcoded
> True for every Anthropic model, never set for Gemini or any OpenAI-compatible provider,
> and the user can toggle it in localStorage where nothing server-side reads it. Gating on
> it would block Gemini entirely while waving through models that cannot see. **So we send,
> and we make the failure legible.**"

**这条单独列成拍板项 ①,不许顺手定**(用户明确要求)。

### 0.4 三个是**一行钩子**,而且**已经按 role 区分了**

| 槽 | 调用点 | 今天的 role |
|---|---|---|
| 上下文压缩 | `server/orchestrator/memory.py:170-172` | `role="summarize"` |
| 标题生成 | `server/services/titler.py:69` | `role="summarize"` |
| 路由决策 | `server/orchestrator/router.py:97-99` | `role="router"`(已钉 primary,`routing.py:9`) |

⇒ 对这三个「加槽」是**设置/UI 问题,不是管线问题**。

⚠️ **如果「压缩」还包括知识摄取的压缩,那是另一对站点**:
`server/services/ingest.py:219` / `:306`,两处都是 `role="converse"` ——
**不是** `summarize`。这决定槽是三个还是四个 ⇒ 拍板项②。

### 0.5 🔴 静默换模型今天就已经可能 —— 三个独立机制

`arslan/llm/routing.py`:
1. **`_best:37-43` 只用 `>`**,而 `_score:30-34` 只看 provider 的能力向量 ⇒
   **两个同 provider 的配置得分必然相同**,于是 `configs[0]` **按插入顺序赢,
   即使另一行才是 primary**(`list_for_routing:78` 按 `ProviderConfig.id` 排序)。
2. **打分看不到健康度**:`server/services/provider_config_service.py:77-80
   list_for_routing` 的投影只有 `{id, provider, model, base_url, is_primary}` ——
   **没有 `last_health`**。`server/services/provider_health.py` 探测,
   但**不在请求路径上做降级**。
3. **打分看不到 key 能不能解开**:`llm_factory.py:38 get_decrypted_key` →
   `provider_config_service._safe:14-18` 解不开返回 `""` ⇒
   **adapter 拿着空 key 出门,失败发生在 provider 那边的 401**。
   (这是 spec ⓪ 那一族的第五个消费者。)
4. 未知 / `custom` provider 在 `arslan/llm/catalog.py` 里**一律记 5 分**(中位)。

⚠️ `routing.py:10-14 WORKER_ROLES` 自称 "illustrative/documentation only — not used in
routing logic",而且**已经过期**:`server/services/sandbox_service.py:20` 用
`role="worker"`,而 `JUDGMENT_ROLES` 和 `WORKER_ROLES` **两个集合都没有它** ⇒
`role="worker"` 落进 strategy 路由。

⚠️ 还有一处**过期的注释**:`llm_factory.py:25-27` 写着
"Phase A: always uses the primary config … Phase B replaces the `chosen = primary`
line with the routing engine" —— 而 `:36` **已经在调 `routing.select`** 了。
注释描述的是一个不再存在的状态。(同一根病本会话已见三次。)

⇒ **fallback 需要新的 per-config 信号,不是新权重。**

### 0.6 🔴 聊天应答那一面根本没有「谁答的」

- `server/schemas.py:442-443` `Run.model` / `Run.provider` 只在**有 Run 行**时写,
  取自 `arslan/llm/usage_sink.py:60-72 primary()` = **token 最多的那个桶**
  (刻意的,注释写明比旧的 last-model-wins 好)。
- **但聊天应答路径没有 Run 行**(`arslan.py:1006-1008` 明写),
  `_usage_frame`(`:945-962`)只带 token/usd;
  `web/src/api/client.types.ts:69-75 StreamUsage` **没有 model 字段**;
  `web/src/components/UsageChip.tsx:11-21` 只渲染 token + usd。
- `web/src/components/RunReplay.tsx:272-273` 只渲染 `run.model` ——
  **`provider` 传到前端从来没被渲染过**。

🟢 **最便宜的钩子已经算好了然后被丢掉**:`usage_sink.py:75-95 detail()` 的
`["buckets"]` 是**每轮都算出来**的 per-(model, provider) 行,带 sticky `estimated` 标志,
**在 frame 和持久化两个边界被丢掉**。⇒ **不需要新测量,只需要不丢。**

---

## 1. 范围

### 做

1. **四个槽**(压缩 / 标题 / 路由 / **vision**),照 `build_synthesis_adapter` 的形状(§0.1)。
   vision 由用户 2026-08-08 裁决加入(§3①);压缩那个槽盖一处还是两处看 §3②。
2. **fallback 链**,🔴 **与 `routing.select()` 合并设计,不许旁边再长一套**(用户硬要求)。
3. **降级可见** —— 🔴 **不许默默换模型花用户的钱**(用户硬要求)。
   动机照用户原话:**可见性不是新要求,是把 §0.5 / §0.6 两条已存在的不可见修掉。**

### 不做

- `web_extract` 槽、审批槽(§0.2:无处可指)。
- **不动 `vision_errors.py` 那条「刻意不 gate」的决定**(§3① 裁决 B 不需要动它)。
- **不重写打分函数**、不改 `STRATEGY_WEIGHTS` 的数字。
  §0.5 的结论是「缺信号」不是「权重错」,顺手调权重会把两件事搅在一起。
- 不做多用户 / 不做按对话覆盖 / 不做运行时 A-B。

---

## 2. 设计

### 2.1 三个槽:照抄现成形状

新增三个 `_PLAIN_KEYS` 条目(`compaction_config_id` / `title_config_id` / `router_config_id`),
各配一个 `build_*_adapter()`,**空 ⇒ 返回 None ⇒ 调用方保持今天的行为**。
三个 `_get_adapter()`(§0.4)改成「先问槽,没有就走 `build_adapter(role=…)`」。

🔴 **`router_config_id` 有一条硬约束**:`routing.py:6-9` 把 `router` 钉在
`JUDGMENT_ROLES` 里,理由写在注释里(评估/优化**必须**跑 primary,不许漂到便宜模型)。
⇒ 路由槽是**显式覆盖**,允许;但**不许**因为加了这个槽就把 `router` 从
`JUDGMENT_ROLES` 里拿掉。**这两件事看着像一件,不是一件。**

~~设置面照 [[arslan-settings-redesign-round]] 的三组七分区,进「自动化」那一片(花钱面收拢处)。~~

🔴 **2026-08-11 修订(用户裁决,偏离留痕)**:改为**另立「模型分工」分区**,不进「自动化」。
理由:自动化分区的叙事是**自花钱警告**(自动进化 / 派发上限 / 整理层,均带消费提示),
而模型槽**不会自己花钱** —— 它只改变已经要发生的调用用哪个模型。混进去会稀释那个警告,
而那个分区当初正是为了把花钱的东西收拢在一处才建的。
原判断不抹掉,取代记录留在这里。实现见 `docs/specs/2026-08-11-model-slots-ui.md`。

### 2.2 fallback:给 `routing.select()` 补信号,不是补一层

**决定**:`list_for_routing` 的投影扩两个字段 —— `healthy: bool | None`、
`key_state: 'set'|'unset'|'undecryptable'`(后者直接复用 spec ⓪ 提出的共享谓词;
⓪ 未落地时用 `provider_config_service._key_status`,它今天就在)。

`select()` 里的用法是**过滤而不是加权**:
```
候选 = configs 里 key_state == 'set' 且 healthy != False 的
候选为空 ⇒ 回到今天的行为(primary),并且报「无健康候选」
候选非空 ⇒ 在候选里按现有打分选
```
为什么是过滤:一个 key 解不开的配置**不是「差一点」,是零** ——
给它一个低权重意味着在别的都更差时它还会赢,而它必然失败。
🔴 这也顺手修掉 §0.5 第 1 条(同 provider 平分 ⇒ 插入顺序赢):
`_best` 平分时**必须优先 primary**,不是 `configs[0]`。

**触发条件**(什么算 fallback)见拍板项③。

### 2.3 降级可见:让已经算好的东西别被丢掉

三层,每层都是「不丢」而不是「新测量」:

1. **`StreamUsage` 加 `buckets`**(或至少 `model` / `provider`)——
   数据来自 `usage_sink.detail()["buckets"]`,`arslan.py:945-962 _usage_frame` 别丢。
2. **`UsageChip` 渲染谁答的**;多桶时(真的换过模型)**必须两个都显示**,
   而不是只显示 token 最多的那个 —— 「换过模型」这件事本身就是要给人看的信息。
3. **`RunReplay` 把 `run.provider` 也渲染出来**(§0.6 末:它已经在传了,没人画)。

🔴 **加字段是免费的,渲染才是全部工作。** 前车之鉴:`server/mcp/catalog.py:74` 的
`containment` 字段加了、发到 API 了,`grep -rn containment web/src` **零命中**。
⇒ 本轮任何新字段都必须有一条**渲染断言**跟着,否则不算做完。

### 2.4 一条明确的红线

**fallback 换到的模型,如果比用户选的贵,必须在换之前可见,不是事后账单里可见。**
本轮不做审批闸(那是主动性循环那一轮的形状),但**必须**在 UsageChip 上当场显示。

---

## 3. 拍板项 —— **①B(已裁决) ③A(方向已批,见下) ② 仍开着**

### ① 🔴 vision:要不要给它一个槽? → 🟢 **B(显式 `vision_config_id`)**

**用户 2026-08-08 裁决:B。理由(原话):显式优于猜测,与其它槽形状一致。**

⇒ 槽位从三个变成**四个**:`compaction` / `title` / `router` / **`vision`**。
⇒ §0.3 那条「刻意不 gate」的决定**不动** —— B 不是 gate,它不猜哪个模型能看,
它让人告诉我们;`vision_errors.py` 那套「照发 + 把失败讲清楚」在**没设 vision 槽**时
仍是唯一行为。
⇒ 工作量确认落地:改三处(`arslan.py:1055-1064` / `tool_loop.py:1134` /
`dispatcher.py:76-78`)+ 给 `run_native` 加入参(§0.3)。

**新增一条硬要求(从「显式优于猜测」推出来的)**:设了 `vision_config_id` 而那一轮**没有图**时,
**不许**用 vision 槽 —— 否则「显式」会变成「悄悄把所有轮次搬到另一个模型上」,
那正是本轮要修的静默换模型。

<details><summary>原三选项与论证(留档)</summary>

`vision_errors.py:3-8` 的原文在 §0.3。它的论证是:`vision` 能力标志对 Anthropic
硬编码 True、对 Gemini 和所有 OpenAI 兼容 provider 从不设置,还能被用户在
localStorage 里改而服务端没人读 ⇒ **拿它当闸会把 Gemini 整个挡掉,同时放过真的看不见的模型**。
所以现在的选择是「照发,然后把失败讲清楚」。

- **A**:不动那条决定,也不加 vision 槽。有图时照发,失败照 `vision_errors` 讲清。
  (最小,尊重现有论证。)
- **B**:加一个 vision 槽(`vision_config_id`),**用户显式指定**哪个配置处理带图的轮次。
  这**不是** gate —— 它不猜哪个模型能看,它让人告诉我们。
  代价:改三处 + `run_native` 加入参(§0.3)。
- **C**:动那条决定,引入真的能力检测。**我不建议** —— 那正是那段注释论证过不可靠的东西。

**我倾向 B**:它绕开了「怎么知道模型能不能看」这个不可靠的判断,把它变成一次配置。
但**这是你的决定,我不顺手定。**

</details>

### ② 「压缩」是三个槽还是四个?(一个槽盖一处还是两处) → 🟢 **A(已由实装裁决,2026-08-11 补记)**

🔴 **实装选了 A,而这份 spec 一直标着「仍开着」** —— 亲核 `912ed8f3`:只有
`server/orchestrator/memory.py:184` 接了 `compaction_config_id`,`ingest.py` 未接。
决定是实装替 spec 做的,补记于此,免得下一个人照「仍开着」重新讨论一遍。
⇒ 摄取路径的 role 保持 `converse` 不变,原提案 B 里那个「行为改动」没有发生。

<details><summary>原始待裁决内容(存档)</summary>


`ingest.py:219` / `:306` 那对站点也是压缩,但 role 是 `converse` 不是 `summarize`(§0.4)。
- **A**:只做对话上下文压缩(`memory.py`)。范围干净。
- **B(我倾向)**:一起做,一个 `compaction_config_id` 覆盖两处。
  理由:对用户来说「压缩」就是一件事,给他两个开关是在暴露实现分层。
  ⚠️ 但两处今天的 role 不同,合并意味着**摄取路径的默认行为会变**
  (从 `converse` 到 `summarize` 的选择路径)—— 这是一个**行为改动**,要写进交付报告。

</details>

### ③ fallback 什么时候触发? → 🟢 **A(只在派发前过滤)**

⚠️ **用户没有逐字裁决这一条**,我按两条已批的内容把它读成 A:
「不重写打分函数 —— 批」+ 原始范围里那条
「**降级必须界面可见 —— 不许默默换模型花用户的钱**」。
B(失败后自动重试换模型)与后者直接冲突。**若你要的是 C(失败后提议),回来改。**

- 🟢 **A(采纳)**:**只在派发前过滤**(§2.2)。key 解不开 / 已知不健康的配置不参选。
  **不做**请求失败后的自动重试换模型。
  理由:失败后换模型 = 一次用户没批准的额外花钱,而且**会把一个 401 变成两次账单**。
- **B(已否)**:失败后自动重试一次到下一个候选。更「聪明」,但踩上面那条。
- **C(未采纳,可回退到它)**:失败后**提议**换(提议面宁开、执行面宁关,见
  [[arslan-propose-vs-execute-bias]])。中间态,但要 UI。

---

## 4. 验收(写死,实现轮照抄)

1. **四个槽各自**:设了 ⇒ 那一次调用真的用了指定配置;没设 ⇒ 行为与今天**逐字节相同**。
   mutation:让「没设」时也走覆盖分支,必须红。
1b. 🔴 **vision 槽只在那一轮真的带图时生效**(§3① 的新增硬要求)。
   断言两侧:带图 ⇒ 用 vision 配置;不带图 ⇒ **不用**。
   mutation:去掉「有图」这个条件,无图那条必须红 ——
   否则「显式指定」会悄悄变成「所有轮次都搬走」。
2. **`router` 仍在 `JUDGMENT_ROLES`**(§2.1 的硬约束)。断言缺席式:
   一条测试断言 `strategy != "single"` 时 `select("router", …)` 仍返回 primary。
3. **平分时 primary 赢,不是 `configs[0]`**:两个同 provider 配置、primary 是第二行 ⇒
   选中第二行。**这条今天会红**(§0.5 第 1 条),是本轮的真修复之一。
4. **key 解不开的配置不参选**;全都解不开 ⇒ 回到 primary 并报「无健康候选」,
   **不是**静默返回一个必然失败的配置。
5. 🔴 **「谁答的」在聊天里可见 —— 行为断言,渲染组件读屏幕**
   (见 [[arslan-assert-behaviour-not-source]]:一个永不触发的显示和正常工作的长得一样)。
6. **换过模型时两个模型都显示**,不是只显示 token 最多的那个。
7. **`run.provider` 在 RunReplay 里真的被渲染**(它今天在传、没人画)。
8. **每一个新字段都有一条渲染断言**(§2.3 末的 `containment` 前车之鉴)。
9. 🔴 **`WORKER_ROLES` 那条过期注释和 `llm_factory.py:22-28` 那句 Phase A docstring
   一起修掉 —— 用户 2026-08-08 点名:「它是『注释描述没发生的事』第五例,别让它活过这轮。」**
   一条描述着没发生的事的注释,和一个坏掉的功能一样会误导下一个人。
   ⚠️ 精确位置:`build_adapter` 定义在 `:22`,docstring 在 `:23-28`,
   "Phase A … Phase B replaces the `chosen = primary` line" 那两句在 `:25-27`,
   而 `:36` 早就在调 `routing.select`。
10. 全量测试 + CI,run id 照 [[ci-green-claims-must-cite-actions-run]] 引。

---

## 5. 风险与未覆盖面

1. **`healthy` 字段的来源是 `provider_health` 的探测,而探测本身可能过期**。
   ⇒ `healthy=None`(没探过)必须被当作**可参选**,不是不健康。
   fail-open 在提议面是对的(见 [[arslan-propose-vs-execute-bias]])。
2. **`select()` 加过滤会改变现有用户的选择结果**。这是本轮唯一的行为破坏面 ——
   交付报告要写清什么情况下选择会变。
3. **未覆盖:按对话/按分身覆盖模型**。本轮是全局槽。
4. **未覆盖:成本预估**。`UsageChip` 显示的是已花,不是「换到这个会更贵」。
   §2.4 只要求「当场可见」,不要求事前预估。
5. **未覆盖:`llm_strategy` 与槽的优先级交互**。槽是显式覆盖 ⇒ 槽赢。
   但如果用户同时设了 `performance` 策略和一个便宜的压缩槽,那是**用户的意图**,
   不该被策略推翻。这条要写进文案,否则会被读成 bug。
6. 🔴 **与 G1 的重叠面**:G1 动 `arslan.py` 和三个 provider。
   本轮动 `arslan.py:945-962 _usage_frame`。⇒ **G1 合并时会撞**(见
   [[arslan-g1-parked-rebase-watch]] 的盯盘清单:本轮要往那份清单里加 `_usage_frame`)。

---

## 6. 尚无证据、未声称已验

- **§0.5 那四条是读出来的,不是观测到一次真实的静默换模型。**
  「今天就已经可能」是**代码推导**,措辞不许滑成「已经发生过」。
  能补的动作:造两个同 provider 配置、primary 放第二行,看选中哪个 —— 一条测试就能证,
  但那要等动手。
- **`provider_health` 的探测频率/新鲜度没有测量**。§5.1 的 fail-open 是保守选择,
  不是基于实测的过期率。
- **`usage_sink.detail()["buckets"]` 在真实多模型一轮里的内容没有实测过**。
  §0.6 的「已经算好了」是读代码得出的;它到底带几行、`estimated` 什么时候为真,
  动手第一件事应该是打一次真实的 frame 出来看。
- **vision 三处改动的规模没有估过**。§0.3 说的是「三处 + 一个新入参」,
  不是「工作量小」。
- **本轮一行代码都还没写。**

---

关联:[[arslan-four-specs-recon-2026-08-07]]、[[arslan-propose-vs-execute-bias]]、
[[arslan-assert-behaviour-not-source]]、[[arslan-g1-parked-rebase-watch]]、
[[arslan-settings-redesign-round]]、[[arslan-vision-round]]、
[[ci-green-claims-must-cite-actions-run]]。

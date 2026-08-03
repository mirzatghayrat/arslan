# 视觉轮 spec（BYOK 视觉通路 + 投喂诚实性 + 可选本地能力机制）

base main = `d64ab93`。落地路径：`docs/specs/2026-07-27-vision-round.md`。
上游登记：`docs/specs/2026-07-26-s4.3a-packaging.md:169-177`（§9「视觉轮 —— 排 S4.3-a 之后、S4.3-b 发布之前，**必须落地**」）。

**本轮不是"补 OCR"。** 它同时是「截图投喂第二大脑」这个核心用例的落地，和一个**已经在出货的诚实性 bug** 的修复。

---

## 0. 前置核实（每条都亲核到 FILE:LINE，不引用记忆）

### 0.1 🔴 你现在装的 0.1.6 有一个静默说谎的路径

拖一张 `.png` 进第二大脑，界面显示 **"已投喂 1"**，实际入库 **0 条**。三环全部复核过：

| 环 | 证据 | 行为 |
|---|---|---|
| ① | `server/services/ingest.py:91-93` | `_ocr_image` 捕获一切异常 → `return ""`。打包版没装 pytesseract，**这是常态路径不是异常路径** |
| ② | `server/services/ingest.py:150-151` | 空文本 → `chunk_text("") == []` → `return 0`，HTTP 200 |
| ③ | `web/src/components/brain/BrainSection.tsx:94-97` | `try { await feedFile(...); ok += 1 }` —— **从不看返回的 `chunks_added`**，不抛错就记成功 |

聊天附件路径同理但稍诚实：`web/src/components/ComposerAttach.tsx:138-141` 把图片标成 `attach.image_no_parse` = "image (preview only)"，但**不说为什么、也不说图片根本没进模型**。

这直接违反 S4.3-a spec 自己立的规矩（`docs/specs/2026-07-26-s4.3a-packaging.md:162`：**不得静默返回空**）。

### 0.2 LLM 侧：只有两个签名卡住整个特性

- `arslan/llm/adapter.py:72` `chat(system: str, user: str, …)`、`:110` `chat_stream(…)` —— `user` 是纯 `str`。**全仓库零视觉通路**（无 base64 / media_type / image_url / inline_data，唯三处 base64 是 crypto、pptx 下载、git 认证头）。
- **爆炸半径比想象小**：36 个生产调用点里，**只有 2 个**承载真实用户内容（`tool_loop.py:947` 经 `run_native`、`dispatcher.py:430`）；其余 34 个传的是内部拼的字符串。**放宽签名 `user: str | list[dict]` 对那 34 个是零改动。**
- `build_messages` 只有一份，在基类 `arslan/llm/providers/base.py:49-60`，三个 provider 都没覆盖。

### 0.3 三个 provider 的真实状态（决定工作量分布）

| provider | 现状 | 结论 |
|---|---|---|
| OpenAI | `openai_provider.py:38-45,78-88` messages 原样进 JSON body | 图片块**不改代码就能穿过**，只需上游放宽 |
| Anthropic | `anthropic_provider.py:80-83` content 按引用拷贝，`str()` 只作用于 system | 需要一层翻译，不需要重构 |
| **Gemini** | `gemini_provider.py:60` `"parts": [{"text": str(m["content"])}]` | 🔴 **必须重写。且它不报错——它把 base64 的 Python repr 当文本发出去，返回一个看起来合理的答案。这是本轮最危险的静默失败。** |

### 0.4 `vision` 能力标记**不可作为闸门**（亲核）

- `server/services/model_catalog.py:99-102`：Anthropic **给每个模型硬编码** `["tools","vision"]`（代码注释自陈 "models API does not expose per-model caps reliably"）
- `:128-130`：Gemini **从不设 vision**，尽管每个 Gemini 模型都支持图片
- `:184-186`：OpenAI 兼容провider 同样从不设
- `web/src/components/settings/CapabilityBadges.tsx:42-48`：**用户可以点开点关，覆盖值存 localStorage，服务端没人读**

⇒ 今天照它 gate，会**放行不支持的、拦死支持的**。这是拍板项 ②。

### 0.5 历史持久化：图片活不过第二轮（亲核）

`server/db/models.py:61`（ChatMessage.content）与 `:116`（ArslanMessage.content）都是 `Column(Text, nullable=False)`。历史按 `{"role": m.role, "content": m.content}` 重建 ⇒ **第一轮发的图片，第二轮就没了**，表现为"模型忘了刚才那张图"。这是拍板项 ③。

原始字节**当前完全不留**：`KnowledgeChunk`（`models.py:512-530`）无 blob 列，全仓库无 `write_bytes`/`wb` 落盘；前端 `previewUrl` 是 `URL.createObjectURL`，刷新即失效（`ComposerAttach.tsx:234-237`）。

### 0.6 「可选本地能力，按需下载」——**第一个已经出货了，是个一次性实现**

你当初的登记是"接第一个之前先把机制定下来"。实际是：`server/services/local_embedding.py`（86 行）已经在跑。对照你列的六项：

| 要求 | 现状 | 证据 |
|---|---|---|
| 下载 | ⚠️ 整个委托给 fastembed 构造函数，无进度/无续传/**下载前不告知体积** | `:59-71` |
| **校验** | ❌ **没有**。就绪判据 = "目录下有没有 `.onnx` 文件" ⇒ 半截下载照样报 ready | `:30-32` |
| 存储 | ⚠️ `<data-dir>/models`，单模型假设，无体积核算 | `:25-27` |
| **卸载** | ❌ **没有**。120MB 下完就是永久的 | 全文无删除路径 |
| 失败重试 | ⚠️ 能重试无退避；状态只活单进程内存（代码自陈边界） | `:17-20,62-71` |
| UI | ⚠️ 硬绑这一个模型，不是注册表 | `settings.embedding*` 键 |

⇒ 机制不该从零发明，该是**把这 86 行长成注册表 + 把嵌入模型改造成第一公民**。

### 0.7 顺带核出的三个小账（不在主线，如实登记）

- **`.bmp` 前后端不一致**：前端 `BrainNav.tsx:233` / `feed.ts:32` 接受，后端 `_IMAGE_EXT_RE`（`ingest.py:21`）不含 ⇒ HTTP 400。
- **`.pptx` 从来不支持**：`_extract_file`（`ingest.py:96-124`）无 pptx 分支 ⇒ `ValueError`。但 `pyproject.toml:81-82` 的注释声称 "docx, pptx, html, txt and md are unaffected" —— **注释是错的**（python-pptx 只用于生成 deck）。
- **图片 token 无法归因**：`usage_sink.py:30-57` 只有 in/out 两个整数维度，`prices.py` 无按图/按 tile 费率。总数仍对（三家 API 都把图片 token 折进 input），但**无法预估、无法拆分**。

---

## 1. 范围

**做**：
1. BYOK 视觉通路：图片 → 三个 provider 的原生图片块（含 Gemini 重写）
2. 截图/图片投喂第二大脑与聊天附件真正可用
3. 🔴 **投喂入口显式告知"这张图会发给你配置的模型"**（S4.3-a spec `:175` 的产品诚实要求）
4. 🔴 **修掉 0.1 的静默说谎**：`chunks_added: 0` 必须让用户看见
5. 【可选本地能力，按需下载】机制设计一节（实现范围见拍板项 ⑤）

**不做**（防蠕变）：OCR 引擎 / RapidOCR / 任何本地模型 / 语音 / 视频 / 图片生成 / Windows·Linux。

---

## 2. 五个拍板项 —— **用户已裁决(2026-07-27):全部取 A,附加四条**

> 下方每项保留原始选项以便追溯；🟢 = 已定，附加条款是用户在裁决时新增的约束，**与 A 同等效力**。

### ① 扫描版 PDF 要不要一起解决？
**🟢 定：A —— 扫描版 PDF 一起做。**
**🔴 附加(花钱护栏,执行面宁关)**:每页栅格化 = 一次图片计费。必须有**每文档页数上限**,超限时**明示**(不许静默截断、不许静默全跑)。200 页扫描件 ≈ 200 个图块,这是能烧钱的路径,闸门默认关得紧。

**默认值写死:`VISION_PDF_MAX_PAGES = 36`,可在 Settings 调整。**(用户 2026-07-28 追问「20 怎么定的」——如实答:20 是我拍的,没算。补算后改 36。单页按长边 1568 缩放的 A4 ≈ 2,319 token(Anthropic 像素/750)或 2,125(OpenAI 512 瓦片);36 页 ≈ 83k token,在 DeepSeek-flash 上 $0.012、Sonnet 上 $0.25 —— **钱不是约束,上下文窗口才是**:36 页在 128k 窗口里还剩 ~45k 给系统提示/历史/回答,50 页 ≈ 116k 一带历史就溢出。真实天花板约 40 页,36 在安全侧。成本表已写进代码注释。)「有上限」没有数字就还是没上限——数字进 spec、进默认配置、进测试断言,不留给实现时拍脑袋。超过上限时:**只处理前 20 页,并在结果里明说「本文档 137 页,已处理前 20 页;其余未读取」**——不是悄悄截断,也不是直接拒绝。

`_ocr_pdf`（`ingest.py:34-75`）已经在用 `pypdfium2` 栅格化，但 pypdfium2 在 **`ocr` extra 里**（`pyproject.toml:84-87`），打包版没装。
- **A（推荐）**：把 pypdfium2 提进正式依赖，扫描版 PDF 逐页栅格化后走视觉通路 ⇒ S4.3-a §1 那张能力缺口表的**两个 ❌ 一次全消**。代价：安装体积增加（PDFium 原生库，需实测；且它带 `.dylib`，要过一遍嵌套 Mach-O 签名坑）。
- **B**：本轮只做独立图片，扫描版 PDF 留到下一轮。缺口表消一个留一个。

### ② 模型不支持视觉时怎么办？
**🟢 定：A —— 不 gate,失败转可行动文案；catalog 的 vision 标记顺手修准。**
**🔴 附加**:"错误转文案"那条路径**必须有测试**(不能只测 happy path;要能区分"真的转了"与"原始错误漏出去了")。

`vision` 标记不可信（见 0.4）。
- **A（推荐）**：**不 gate，发了再说**；失败时把 provider 的原始错误转成可行动文案（"你选的模型可能不支持图片，换一个带视觉的模型或改用文字描述"）。同时**顺手修 catalog**：Gemini/OpenAI 补上 vision，Anthropic 的硬编码加注释说明它是乐观默认。
- **B**：先把 catalog 修成可信，再据它 gate（拦截更早，但要先赌 catalog 修得准）。

### ③ 图片在对话历史里活多久？
**🟢 定：A —— 只活当轮,第二轮起降级为 `[图片:文件名]` 占位。**
**🔴 附加**:UI 那句"图片仅在发送那一轮参与推理"**进六语**,不是只写英文。

`content` 是 Text 列（见 0.5）。
- **A（推荐）**：**只活当轮**。第二轮起历史里降级成 `[图片：filename]` 文本占位，**并在 UI 明说"图片仅在发送那一轮参与推理"**。零迁移、零膨胀、不撒谎。
- **B**：原始字节落盘 `<data-dir>/attachments/`，历史存引用，每轮重新加载 ⇒ 图片真正持久。代价：新增存储管理/清理策略/迁移，且每轮重发图片会**按 tool-loop 步数重复计费**（见 0.7 与下方 T6）。
- **C**：base64 存进 Text 列 —— **我不建议**，会把 db 撑爆且备份变重。

### ④ 第二大脑里的图片，存什么？
**🟢 定：A —— 存模型对图片的描述文本,原始字节不留。**
**🔴 附加**:描述文本**必须带 provenance 标记(模型描述,非原文摘录)**,防止检索命中时被当成 verbatim 引用。这是诚实性要求,不是元数据洁癖。

- **A（推荐）**：存**模型对图片的描述文本**（视觉通路读一遍图 → 描述入 `knowledge_chunks`，可被检索/嵌入），原始字节不留。与现有 chunk 模型完全兼容。
- **B**：描述 + 原始字节都留（能回看原图，但要 ③B 的整套存储管理）。

### ⑤ 【可选本地能力，按需下载】机制，本轮做到哪一步？
**🟢 定：A —— 本轮只出设计 + 登记缺口,实现留给第一个真需要下载的能力。**
**🔴 附加(登记必须写具体,不许含糊)**:
- **无校验**：`.onnx` 文件存在即判 ready,**半截/损坏文件照样过**(`local_embedding.py:30-32`)
- **无卸载**：全文无删除路径,下完即永久
- **无进度的阻塞式下载**：整个委托给 fastembed 构造函数,用户看不到进度、下载前不知道体积

**🔴 附加(设计验形)**:§3 的设计稿必须拿**两个案例验形**——**嵌入模型(存量,要能被改造)**与 **whisper(未来,尚不存在)**——证明形状能承载两端,而不是只贴合视觉轮。

视觉通路**零下载**（BYOK 云端），所以这机制在本轮**没有新消费者**——消费者是"已出货的嵌入模型（改造）"与"未来 OCR/语音"。
- **A（推荐）**：本轮**只出设计**（spec 这一节 + 把 0.6 那 6 条缺口登记成待办），实现留给第一个真正需要下载的能力。理由：现在实现＝为零个新用户重构一个能跑的东西。
- **B**：本轮一并实现，把嵌入模型改造成第一公民（补校验/卸载/体积告知）。好处：0.6 那两个 ❌（无校验、无卸载）是**真缺陷**，早修早好。

---

## 3. 机制设计（无论 ⑤ 选 A 还是 B，这一节都写进 spec）

一个能力 = 注册表一行：
- `key`（稳定机器键）/ `display`（走 i18n）/ `kind`（embedding | ocr | asr）
- `bytes_expected` —— **下载前必须能告诉用户占多大**（今天做不到）
- `digest` —— 校验依据；无 digest 的来源**必须显式标记 unverified**，不许静默当验过
- `install_root` = `<data-dir>/models/<key>/` —— 一 key 一目录 ⇒ 卸载 = 删一个目录
- `probe()` —— 就绪判定，**不许再用"有没有某后缀文件"这种代理判据**

状态机（唯一真相在磁盘，内存只承载 transient）：
`absent → downloading → verifying → ready`，任一步失败 → `error{reason}`；`ready →(卸载)→ absent`

**三条硬规矩**：
1. **校验失败 = 不留半个能力**：verify 不过就删目录报 absent+error（当前实现会留碎片并自称 ready）
2. **失败可见、可重试、可放弃**：错误文案区分网络 vs 校验；重试有退避；一键删掉重来
3. **绝不自动下载**：任何本地能力必须用户点了才下 —— 与你刚给更新 pill 定的调子一致

### 两个案例验形(用户要求:证明形状能承载两端,而不是只贴合视觉轮)

| 字段 | **A:嵌入模型(存量,必须能被改造)** | **B:whisper.cpp(未来,尚不存在)** |
|---|---|---|
| `key` | `embed-e5-small` | `asr-whisper-base` |
| `kind` | `embedding` | `asr` |
| `bytes_expected` | ~120 MB —— **今天做不到**:fastembed 不预告体积,要改成先查 manifest 再下 | ~150 MB —— ggml 上游有确定文件大小,天然可填 |
| `digest` | ❌ 上游无稳定 digest ⇒ **必须标 unverified**,不许假装验过 | ✅ ggml 发布带 sha256 ⇒ 真校验 |
| `install_root` | `<data-dir>/models/embed-e5-small/` —— **当前是共享的 `models/`,改造时必须迁移已下权重** | 一 key 一目录,天然独立 |
| `probe()` | 加载一次并 embed 一个探针串 —— **不能再用「目录里有 .onnx」** | 加载模型并转写 0.1s 静音 |
| 卸载 | 删目录 **+ 清进程内缓存** | 删目录 |

**验形结论(诚实):形状基本承载两端,但暴露三处必须在实现轮解决的张力**:

1. **`digest` 不普遍可得**。嵌入模型没有、whisper 有 ⇒ digest **不能是必填**,只能是「有则验、无则显式标 unverified」。§3 硬规矩里已经这么写,案例验形证实那不是洁癖而是必需。
2. **改造存量比新建更难**。用户已经有 120MB 权重躺在共享 `models/` 下,注册表化**必须先迁移再启用**,否则等于逼用户重下。whisper 没这问题 ⇒ **实现轮第一件事是迁移,不是注册表本身。**
3. **最容易被忽略的一处**:嵌入模型有**进程内缓存**(`local_embedding._model` 全局)。卸载只删磁盘的话,当前进程会继续用已经不存在的权重直到重启。whisper 若也做缓存,同一个坑会再来一次 ⇒ **`probe()` 与卸载必须在机制契约里定义成「磁盘 + 进程内缓存」两处一起动**,而不是留给每个能力自己记得。

---

## 4. 改动面（依赖序，来自侦察实测）

1. `arslan/llm/adapter.py:72,110` 放宽 `user: str | list[dict]`（两个签名是唯一闸门）
2. `arslan/llm/adapter.py:100,148` —— `estimate_tokens(system, user, …)` 不能收块列表（见 T1）
3. `arslan/llm/providers/base.py:49-60` `build_messages` 接受块列表 + 归一化中性块形状
4. 🔴 `arslan/llm/providers/gemini_provider.py:60` **必须重写**（`str(content)` → `inline_data` 分支）
5. `arslan/llm/providers/anthropic_provider.py:80-83` 中性块 → `{"type":"image","source":{...}}`
6. `arslan/llm/providers/openai_provider.py:38-45,78-88` 中性块 → `{"type":"image_url",...}`（payload 管道无需改）
7. `server/orchestrator/tool_loop.py:1046,1088` `run_native` 的 convo 播种与 `convo[-1]["content"]` 读取
8. `server/orchestrator/tool_loop.py:925,965,196,234` —— 四处把 user_content 当字符串用（见 T2/T3）
9. `server/orchestrator/arslan.py:965-966`、`server/ws/chat.py:~131` 图片时构块列表而非 f-string
10. `server/orchestrator/dispatcher.py:341-342,430` —— 分身路径把附件塞进 **system**，图片不能走那儿，需单独的 user 轮
11. `server/services/extract.py:11-34`、`server/api/extract.py` 返回字节/mime 而不只是文本
12. `server/services/ingest.py:96-124` 图片分支返回"这是图片字节"而非 `""`
13. `web/src/components/ComposerAttach.tsx:41,103,122-140`、`BrainNav.tsx`、`BrainSection.tsx` —— 送图片载荷 + **诚实告知**
14. `server/services/model_catalog.py:99-102,128-130,184-189`（按拍板项 ②）

---

## 5. 🔴 十个陷阱（侦察实测，每条都要有测试守住）

| # | 陷阱 | 为什么危险 |
|---|---|---|
| T1 | `estimate_tokens` 收到块列表 `TypeError` | 只在**无 usage 回执的回退分支**触发 ⇒ **带 mock 的测试全绿，打真 provider 才炸**；流式中断走的正是这条 |
| T2 | `tool_loop.py:925` `f"The user asked:\n{user_content}"` | 块列表被渲染成 base64 的 repr **塞进 prompt**——不报错，只是巨贵且答非所问 |
| T3 | `tool_loop.py:196,234` 逐字符判 CJK | 对块列表 `ch` 是 dict ⇒ `TypeError`。**这是失败路径**，等于在出错时再炸一次 |
| T4 | `run_native` 第二步起图片进了 `history` | 能工作，但要求块在 history 里逐字保留，且每个 provider 的 history 映射都得认块 |
| T5 | 🔴 **Gemini 静默毁数据** | `str(content)` 永不抛错，返回一个基于 base64 repr 的"合理"答案 |
| T6 | Anthropic 缓存断点在 system | 图片在断点之后 ⇒ **永不缓存**；`run_native` 每步重发全 convo ⇒ 一张图按步数重复计费，而**账本里看不见**（0.7） |
| T7 | 历史列是 Text | 图片活不过第二轮（拍板项 ③） |
| T8 | vision 标记不可作闸门 | 见 0.4 |
| T9 | `extract.py:31-33` 截断 | 字节若走同一函数会被**从中间切断**，产出无法解码的图片且不报错 |
| T10 | `AnthropicProvider.DEFAULT_MAX_TOKENS = 4096` 硬编码 | 非图片专属，但图片输入倾向更长回答 |
| 🔴 T11 | **图片污染进化语料** | ③A 定了图片只活当轮 ⇒ 带图的 run 进 replay 语料后，**基线输出是看着图答的，重放臂只能拿 `[图片:文件名]` 占位答**。两臂条件不对等，judge 在比不可比的东西——**考试闸的公平性被悄悄破坏**,而且它不会报错、只会让分数无意义 |


### 🔴 T11 的处置(用户裁决时新增,与拍板项同等效力)

**`build_corpus` 必须排除输入含图片块的 run**(`server/services/replay_gate.py:239`)。

- 该函数是**唯一入口**:进化 propose 与 **skill_forge 共用这条路径**(spec `:255` 的 mint 说明列了两个真闸门调用方),所以在这里排除**一处生效、两处受益**——不许在两个调用方各写一遍。
- 排除要**计入 `excluded` 计数**(该函数已有这个出口,给非可重放 run 用),这样"语料为什么变小"是可见的,不是凭空少几条。
- 判据用**输入是否含图片块**,不是"文件名像图片"——③A 之后历史里躺的是 `[图片:xxx]` 占位文本,按文本猜会既漏又误伤。

**配套测试(必须能区分)**:造一条输入含图片块的 scored live run,断言**它不进语料**;同一 fixture 里再造一条纯文本 run,断言**它进了**——只断言前者会被"语料恒为空"的实现骗过。
---

## 6. 测试纪律（本轮特别容易假绿）

- 🔴 **T1/T5 类必须有能区分的测试**：现有 `tests/server/test_ingest_ocr.py` 三处**全是** `monkeypatch.setattr(ingest, "_ocr_pdf", …)`、**从不 import 真库** ⇒ 换实现不会让任何现有测试变红。同一个坑本轮会再遇到一次。
- Gemini 必须有**载荷断言**测试：构造带图片的 chat，断言发出的 `parts` 里有 `inline_data` 且 base64 完整 —— 断言"没有把 repr 当文本发"。
- G1 回归：投喂返回 `chunks_added: 0` 时，前端**必须**报"未能读取"而不是"已投喂"。双向 mutation。
- Mutation ⓪ 前置照旧：先证 mutation 本身生效。

---

## 7. 验收

1. 三个 provider 各跑一次真图往返（用你的真 key，我不碰 key）
2. 截图粘贴进聊天 → 模型答得出图里的内容
3. 截图拖进第二大脑 → 生成描述并可被检索命中
4. 投喂入口能看到"这张图会发给你配置的模型"
5. ~~图片读取失败时，UI 说的是"没读到"而不是"已投喂"~~ **✅ 已由插队热修提前满足(main=`216a218`)** —— 本轮不必重做，但**不得回退**:`feedFile` 的 `NothingIngestedError` 与 `tests/server/test_feed_honesty.py` 必须继续存在且继续通过。图片真正可读之后，这条路径从「诚实地失败」变成「不再触发」，守卫留着防回潮。
6. 扫描版 PDF 超过页数上限时，UI **明示**被限制了（不是静默截断）
7. 第二大脑检索命中图片描述时，能看出这是**模型描述而非原文**
8. 本地全量绿 + CI run id + 打包版真机验证（探针法）

---

## 8. 诚实披露（进代码注释 + 交付报告 + README）

- 图片**发往你配置的云端模型**，与文本同一个隐私模型 —— 但用户投喂扫描件时可能以为是本地处理，所以必须显式说
- 图片 token **无法预估、无法在账本里拆分**（0.7）；多步 tool-loop 会重复计费（T6）
- 拍板项 ③ 若选 A：图片**只在发送那一轮参与推理**，必须在 UI 明说
- 拍板项 ① 若选 B：扫描版 PDF 仍读不出，缺口表留一个 ❌

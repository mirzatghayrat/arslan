# 6.5 → 9 作战图（证据版）

base main = `fc9a279`。产出自 8 路研究编队（4 路外部研究 · 3 路代码可行性 · 1 路对抗核验），
run `wf_5e9cbd01-f57`，2026-07-31。**每条主张带出处；wire 格式主张已逐条对官方文档核验
（23 条：22 CONFIRMED / 1 PARTIAL-细节补充 / 0 WRONG）。**

**这份图不动 Launch 门。** 门内三项照序（文案清零→空状态→Settings mock）；图上其余全部是
门外队列，插队要按门规（个人信息/花钱失控/数据丢失三类）由用户裁。

---

## 0. 三个比预期更重要的发现

### 0.1 🟢 工具传输层的修复比想象小得多

预期是"大手术"，可行性读出来是 **9 步、多数 small**。两个原因：

1. **follow-up 轮零 provider 工作**：`run_native` 把工具结果以 provider 中性纯文本喂回
   （`tool_loop.py:254-280` 把 assistant 调用记成 JSON 字符串、结果记成 "TOOL RESULT for X"
   的 user 轮）。wire 历史里**从不出现** `tool_use`/`functionCall` 块 ⇒ Anthropic 严格的
   tool_use/tool_result 配对约束**根本不会触发**。这正是现在 OpenAI 路径的工作方式 ——
   对齐只需要**请求翻译 + 响应解析**两件事。
2. **流式可以先不做**：`run_native` 只走 `adapter.chat`（`tool_loop.py:990-1001`），
   生产上没有任何 `chat_stream` + tools 的调用点。

**一个实现时的硬要求（不是打磨）**：Anthropic 的 prompt-cache 渲染顺序是
tools → system → messages，缓存断点在 system 前缀上 ⇒ **tools 序列化必须逐字稳定**，
而 MCP 工具列表来自**无 ORDER BY 的 DB select**（`arslan.py:1747-1755`）——
不加确定性排序，加 tools 就等于每轮打碎缓存。

### 0.2 🔴 Deck Master 实际上是坏的 —— 2000 字符截断陷阱

`_skill_technique_block`（`dispatcher.py:130-180`）对超过 `_SKILL_BLOCK_LIMIT=2000` 字符的
技能注入"标题+简介+目录"。**但简介取的是第一个标题之前的正文，而仓库风格的 SKILL.md
第一行就是 `## Trigger`** ⇒ 简介永远为空 ⇒ 超限技能坍缩成一张光秃秃的目录。

实测尺寸：多数种子只有 **550-650 字符**（7 条规则、零示例、零验证步骤）；而
`deck-authoring`(2742)、`competitive-analysis`(2199)、`designed-html-report`(**11756**)
全部被截成目录残根。全文只能靠 `read_skill` 读，而它**只在 code_sandbox 工具集里** ——
没装的 spawn 得到一句"读全文需装备 Code Sandbox"的死胡同提示。

⇒ **六个 spawn"弱"的解释找到了一半**：不是模型不行，是给它们的方法论要么薄
（550 字符），要么根本没送达（截断成目录）。

### 0.3 🟢 主动性循环的业界共识和你的规矩完全同构

四个成熟产品（Sentry Seer、OpenHands resolver、Sweep、Devin）收敛到同一架构，
**没有一家让检测直通执行**：

```
DETECT（廉价常开信号，去抖 + 可修性打分）
→ DIAGNOSE（硬预算：max turns + max tokens + 强制终态"提案或认输"）
→ PROPOSE（可审工件 + 证据附身，先过自己的测试再见人）
→ APPROVE（硬人闸）
```

AutoGPT 自己的复盘是反面教材：54% 预算烧在解析引用上、无限任务分解 —— 它后来
**放弃了自由规划，改成人写的固定工作流**。⇒ 你要的"Arslan 主动发现问题→GitHub 找方案"
形态就是：**提议面全开（检测/诊断/搜索/提案），执行面全关（安装/运行必过人闸+封闭注册表）** ——
和「提议面宁开、执行面宁关」逐字吻合，不需要破供应链红线。

---

## 1. 6.5 分的构成与解法出处

| # | 缺口 | 权重 | 解法（出处） | 规模 |
|---|---|---|---|---|
| G1 | **工具传输层**：Anthropic/Gemini 不发 tools（wire 实测） | **最重** | 各 adapter 内翻译（LiteLLM 内部也是 per-provider transformation class；Dify/LangChain 同型）。**不引 litellm**（重依赖+env 副作用，不适合冻结 sidecar）；把它沉淀的知识搬进来：Gemini schema 白名单+`$defs` 内联、Anthropic 工具名清洗+反查表、`required`→`any` 映射、缺失 id 合成 | 9 步，多数 small |
| G2 | **Spawn 单薄** | 重 | ① 拆掉截断陷阱（small，救活 Deck Master + 4 个 spawn 的 3 个残根技能）② 共享 SOP+输出契约脚手架（MetaGPT ActionNode / gpt-researcher 分段管线 / CrewAI expected_output 模式）③ 派发器统一自检块（AutoGen reflection）—— **身份层是最便宜也最弱的层，方法/契约/验证三层才是强弱分界** | ①small ②medium ③small |
| G3 | **Settings 信息架构**（门内③） | 中 | LobeChat（check 按钮真探连通）、Cherry Studio（typed 健康态+延迟）、LibreChat（registry 驱动+设置内搜索+Danger zone）、Jan（**逐控件两级能力诚实** —— 和我们的 fitness matrix 天然接轨）、模型列表=带刷新+新鲜度的受管清单 | mock 已出（见下） |
| G4 | **空状态不教人**（门内②） | 中 | 各产品的 designed empty state；进化收件箱按 dogfooding 三条改 | medium |
| G5 | **主动性缺失** | 中 | §0.3 的四段循环，落成 spec 待审 | spec 先行 |
| G6 | 逐技能/逐工具 fitness 行、扫描 PDF 聊天附件等已登记债 | 低 | 已在门外清单 | — |

## 2. 有序执行队列（门规之下）

```
门内（现在）:  ① 后端3模块文案清零 → ② 空状态 → ③ Settings 重做（mock→批→实现）
launch
门外第一批:    G1 工具传输层（9步） + FU-2b 次序修正（已记）
门外第二批:    G2 spawn 强化（截断陷阱→SOP脚手架→自检块，然后逐 spawn 轮）
门外第三批:    G5 主动性循环（spec→审→实现）
```

**依赖关系**：G2 的全量收益依赖 G1（Anthropic/Gemini 上工具死着，SOP 写得再好，
需要工具的步骤仍是摆设）。所以 G1 在前不是偏好，是拓扑。

## 3. 尚无证据、未声称已验

- 工具传输层 9 步计划是**可行性读**，不是实现——streaming 工具增量、`strict` 模式、
  Gemini `parametersJsonSchema` 新字段都要在实现时对 wire 再验（capability fitness
  测试会自动逼着表和 wire 一致，这是现成的安全网）。
- 竞品结论基于**公开代码与文档**，未逐一本地跑通它们。
- Spawn 尺寸测量在 `fc9a279`，截断行为读自代码，**未跑一次真实 Deck Master 派发复现**
  （复现动作：派发一个 deck 任务、看注入块是否为目录残根）。
- Settings mock 是设计稿，未写代码。

## 4. 待用户裁决

- **D1** 工具传输层插不插门内？（我的建议：门外第一批 —— 按你自己的三类插队规矩它不够格；破一次例，门就没了）
- **D2** 截断陷阱（0.2）是 small 修复但同样在门外 —— 插不插？（它让已出货的 Deck Master 名不副实，最接近"够格"的边缘，但仍不属于三类）
- **D3** Settings mock（同 commit 附上）批不批 / 改哪里
- **D4** 主动性循环按 §0.3 形态立 spec？

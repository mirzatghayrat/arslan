# 主动性循环 spec（检测 → 预算内诊断 → 带证据提案 → 人闸）

base main = `fc9a279`。上游：作战图 §0.3（`docs/specs/2026-07-31-product-gap-assessment.md`），
用户 D4 裁决"立 spec"。排期：**门外第三批**（G1 工具传输层、G2 spawn 强化之后）——
本 spec 只定形状，等审，不实现。

**一句话**：让 Arslan 自己发现问题、自己上 GitHub 找方案、自己写成提案 ——
**但装什么、跑什么，最后一步永远是人。** 提议面全开，执行面全关。

---

## 0. 前置核实（亲核，带 FILE:LINE）

已有的积木比预想多，这个循环大半是**接线**而不是新建：

| 积木 | 现状 | 出处 |
|---|---|---|
| 检测信号源 | ✅ 已存在：`runs` 表带 `status`/`error_kind`；诊断台已有六条异常描述的**计算逻辑**（`server/api/runs.py:339-374`，错误率偏高/达标率偏低/连续失败/工具报错——文案待 i18n 是门内①，计算是现成的）；MCP 健康探测（`health_status`，PB-4）；进化 eligibility 判定 | runs.py、mcp 模型 |
| 提案箱先例 | ✅ 两个：记忆提案箱（Tier-2 人工闸，accept/dismiss/410/409/422 全套）与进化收件箱。**两箱不混是既有裁决** | brain proposals、evolution inbox |
| 预算先例 | ✅ FU-2b：eval 面**每 attempt** 抓取预算、强制拒绝态；派发上限闸 | `tool_loop.py:317`、`evolution_watcher.py:250` |
| GitHub 只读通路 | ✅ `github_eval` 固定 host api.github.com、许可证闸服务端强制 | `skill_import.py:9-14` |
| 供应链红线守卫 | ✅ 已是测试：搜索端点不可达 importer、安装必须指名 repo | `test_capability_supply_chain.py` |

**缺的只有三件**：① 一个把信号变成"值得诊断"判定的调度器；② 一个预算内的诊断-研究执行器；
③ 第三个提案箱（或并入现有箱——拍板项②）。

## 1. 机制（四段，每段一条硬规矩）

### DETECT —— 廉价、常开、去抖
- 信号：run 失败率（复用 runs.py 的现成计算）、同形状错误重复 N 次（去抖：**单次不触发**，
  Sentry Seer 的 10+ 次门槛先例）、MCP 连接持续 failing、工具连续报错降级（PB-3 已有计数）。
- **硬规矩：检测本身零 LLM 调用、零网络。** 纯 SQL/计数，跑在现有 watch_loop 的 tick 里
  （挂 while 体不挂 tick()，D5 教训：tick 第一句是 `_enabled()` 闸）。
- 每个信号带**可修性预判**（规则判断，不是模型判断）：schema 错误=可修，配额耗尽=不可修只通知。

### DIAGNOSE —— 硬预算，强制终态
- 触发后开一次诊断 run：**max N 次派发 + 每 attempt 抓取预算（直接复用 FU-2b 的
  `HERMETIC_FETCH_BUDGET` 机制，新 sentinel `proactive-diagnosis`）+ 强制终态**：
  要么产出提案，要么记录"放弃 + 原因"。**没有第三态**（AutoGPT 的 54% 预算烧在解析引用 =
  没有强制终态的下场）。
- 固定阶段不自由规划：复现证据收集 → 假设 → （可选）GitHub 检索 → 提案草稿。
  每阶段有输出契约，上一阶段的输出是下一阶段的输入。

### PROPOSE —— 可审工件，证据附身
- 提案 = `{症状(带 run id 们), 诊断, 建议动作, 证据链接(GitHub URL 等), 预估影响}`。
- GitHub 检索结果**只作为链接进提案**——人读、人选。**绝不自动 import_skill /
  绝不把搜索结果喂给任何安装通路**（`test_capability_supply_chain.py` 已经钉死签名边界，
  本轮给它加一条：诊断执行器模块不可 import `skill_import`）。
- 提案先过自检（Sweep 先例）：能本地验证的（如"重跑该 run 确认已修"）验完再入箱。

### APPROVE —— 人闸
- 提案入箱等 accept/dismiss。accept 的动作**只能是**：打开某设置页、跳到某文档、
  或触发一个**已在封闭注册表内**的既有操作。没有"accept = 装个新东西"。

## 2. 不做（防蠕变）
自动修复（哪怕"很安全的"）；自动安装任何来源的任何东西；后台自主浏览非 GitHub 站点；
诊断结果直接改设置；把本循环接进进化的自动路径。

## 3. 拍板项

① **检测信号首批收哪几个？** A（推荐）：run 失败率 + 同形错误去抖 + MCP failing 三个，其余后加。B：只做 run 失败率一个，最小起步。
② **提案落在哪？** A（推荐）：第三个独立箱（沿两箱不混的既有裁决，Diagnostics 里加一节）。B：并入进化收件箱（省一处 UI，但混了"改 prompt"和"系统有病"两类语义）。
③ **诊断预算数值**：派发上限 / 抓取上限各多少？我建议派发 ≤6、抓取沿用 50/attempt，理由写实现 spec 时按 FU-2b 的推导方式算，不拍脑袋。
④ **GitHub 检索面**：A（推荐）：只搜 issues/discussions（找"别人也遇到过"），不搜代码。B：连代码一起搜。A 面窄但提案更像证据链，B 面宽但更容易把"看起来像方案的代码"当方案。

## 4. 验收（写死，实现轮照抄）
- 检测零 LLM/零网络有测试（探针：patch 掉 LLM/httpx，检测照常跑）。
- 诊断超预算必到终态"放弃+原因"，mutation：删终态逻辑必红。
- 提案箱 accept 不可达任何安装通路（扩展 supply-chain 守卫）。
- 每条提案带 ≥1 个 run id 证据，空证据提案被服务端拒。

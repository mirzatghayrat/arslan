# Launch 门 · burn-down 清单

**唯一真源。门内五项，只减不增。** 建于 2026-07-30，base main = `cc5d207`（v0.1.12 已发布）。

## 规矩（用户 2026-07-30 定）

1. **门内只有下面五项。** 不追加新范围。
2. **守卫新逮到的默认进门外**（launch 之后再说）。
3. **只有三类可以插进门内**：**个人信息泄漏**、**花钱失控**、**数据丢失**。除此之外一律门外，无论多想做。
4. **每版发布划掉对应项**，清单只减不增。
5. **每轮交付末尾附一行「门内余额」。**

> 这份清单存在的意义是**收敛**。任何"顺手也做了 X"的冲动，如果 X 不在上面五项里，答案就是不做 —— 它属于 launch 之后。

---

## 门内（5 项）

### ~~① 后端白名单 3 模块的显示文案清零~~ · ✅ **已划掉**（分支 `i18n/backend-display-text`，CI run `30648777564` success）
挂账来自 v0.1.12：修掉第二大脑导航的中文标签时，新加的 AST 守卫
（`tests/server/test_no_display_text_from_the_backend.py`）**第一次跑就又逮到三个模块**。
它们进了白名单、写明理由、**没有被静默跳过** —— 但英文界面下用户**现在仍然看得到中文**。

| 模块 | 用户在哪看到 |
|---|---|
| `conversations.py` | 手动蒸馏摘要（`手动蒸馏 N 个分身 (失败 M 个)`，一句话里嵌两个数字） |
| `runs.py` | 诊断台六条异常描述（`错误率偏高` / `达标率偏低` …，由数字拼装 ⇒ 上键就要拆组合） |
| `scheduled_tasks.py` | API 报错（`定时任务 N 不存在` / `cron 表达式不能为空`），经 `HTTPException detail` 直达界面，没有任何东西翻译它 |

**完成判据**：三个模块从 `ALLOWED` 里删除且守卫仍绿（不是把守卫放宽）。
`registry.py` 的沙箱警告是**运维面**、不是用户面，**留在门外**。

✅ **判据本身被断言**（`test_the_three_modules_are_out_of_the_allowlist`），不是靠"守卫绿了"隐含。
把三个模块塞回 `ALLOWED` 的 mutation 会让**跳过数从 1 变成 4** —— 放宽守卫在绿报告里读作"查过了"，
只有直接断言白名单本身才拦得住。
🔴 **`conversations.py` 是部分修复**：已写进库的 `ConversationEvent.summary` 行永久保留原中文，
只有此后新写的才是键（原因写在 `_distill_event` docstring 里）。

### ~~② 空状态设计落地~~ · ✅ **已划掉**（同分支）
今天的空状态基本是"什么都没有"，不告诉人下一步。已知至少两处点名过：
进化收件箱的 `No evolution proposals yet`（用户 dogfooding 时**连点多次 ENQUEUE，因为不知道下一步干嘛**），
以及第二大脑在没有任何记忆时的样子。
**完成判据**：主要空状态都有「这是什么 + 下一步做什么」，不是一句 "No data"。

审计查出全app **61 处空状态，其中只有 6 处**在块内带任何可操作控件。**没有全改**，
分层规则写进测试表（`web/src/__tests__/empty-states.test.tsx`）：

| 层 | 定义 | 处理 |
|---|---|---|
| **A** | 全新安装时整块面板空着 —— 新用户对这个功能的第一印象 | 补「是什么 + 下一步」+（当下一步不在同屏时）一个真控件 |
| **B** | 已有数据面板里的子块；**筛选无结果** | 保持一行 |

动作**逐点判断而非一律加按钮**：跟同屏已有控件重复的按钮是诱饵不是下一步，理由逐条写在表的 `why` 字段。
**顺带修掉一个真错**：能力目录把「你什么都没有」和「筛选没匹配上」用了同一个 key ——
用户只是点了个筛选 chip，却被告知去导入第一个技能。而默认 chip 是 `usable`，
所以那恰恰是**最常见的首屏**。
另修 `Sidebar.tsx` 的硬编码英文 "No spawns yet"（门内①同一种病、方向相反：中文用户看到没人能翻译的英文），
并删掉 7 个零调用点的死 key。

### ③ S4.2-d 剩余 UI 项 · 逐条状态盘点 · **我的活**
**下面是清点表，不是印象** —— 每条都在 `cc5d207` 上 grep 过：

| 项 | 状态 | 证据 |
|---|---|---|
| M7-1 Skills 面板溢出（`min-w-0`） | ✅ 已覆盖 | `web/src/components/SkillImportPanel.tsx` 含 `min-w-0`（我第一次在 `Capabilities*.tsx` 里找，找错了地方） |
| M7-2 重复标题 "IMPORT SKILLS FROM A REPO" | ✅ 已删 | 全仓 0 处 |
| M7-3 "Equip to spawn…" 省略号 | ✅ 已结案 | 菜单开启惯例，非截断 |
| M7-4 SKILL.md 契约 token | ✅ 已覆盖 | `capabilities.skill_body_label` 六语**刻意同值**（含 `## 决策规则`），因为后端只认这个字面量 |
| M7-5 侧栏图标按钮无名 | ✅ 已覆盖 | `aria-label` 在 Sidebar(1) / OrchestratorChat(4) / BrainNav(2) |
| M7-6 品牌图裂图 | ✅ 已结案 | 环境问题（僵尸 app / 陈旧 symlink），打包资产完好 |
| workspace 条只在对话界面 | ✅ 已覆盖（v0.1.12） | `App.tsx` 按 section 渲染标签；**栏与拖动区保留** |
| Active Spawns 会话作用域 | ✅ 已覆盖（v0.1.12） | `Sidebar.tsx` 用 `dispatchedSpawnIds` |
| L.1 徽标 / hover「完结」 | ✅ 本来就在 | 查实：徽标已有，按钮已是 `opacity-0 group-hover:opacity-100` |
| **Settings 整体重设计** | ❌ **唯一开着的** | 用户 2026-07-30 裁决：不做局部改良，要**整个功能界面**重出 mock；与 M7 布局清单有重叠，一起看 |

**⇒ ③ 实际只剩 Settings 一项。** 其余全部已覆盖或已结案。

### ~~⑥ 并发 attempt 互相退款（花钱失控）~~ · ✅ **插队并划掉**（用户 2026-08-01 裁决）

**这是清单建立后第一次往门内插项，走的是三类例外里的「花钱失控」。**
分支 `fix/hermetic-budget-refund`（base `origin/main`=`4a9848e`，CI `30675537391` success）。

`_perform_attempt` 无参 `reset_hermetic_fetch_budget()` 清**全部**键，
而 `_running_spawns` 只按 **spawn** 限并发 ⇒ 两个 attempt 常态重叠，
B 启动会把 A 正在花的计数器归零。**实测 A 花到 90 / 名义上限 50**，N 次重叠 = N×50。
坏的方向是**进化活动越多闸越松** —— 与计数器注释自称的
「a shared budget can only refuse earlier … never later」正相反。

🔴 **显而易见的修法是空的**：传 sentinel 不解决问题，因为全体 hermetic 派发共用
`"evolution-replay"` 一个键，pop 那个键 == clear 整个 dict。我第一次就是这么写的，测试拒绝了它。
真修法 = **attempt 引用计数**（重叠共享一份、串行各自一份），保住"共享是保守方向"这个原本正确的设计。

⇒ 出处不是本清单里的任何一项，是做 D4 spec 的预算推导时挖出来的。
**它证明了一件事**：`docs/specs/2026-08-01-proactive-loop.md` §3.1 那套"照 FU-2b 推导"的做法，
第一次真去照做，就发现被参照的那个先例自己漏了。

### ⑦ 重启后会话消失（数据丢失） · **我的活** · 🔴 **launch 阻塞**

**清单建立以来第二次插入**，走「数据丢失」例外（用户 2026-08-01 裁决）。
**按 launch 阻塞对待**：每个打包版用户每次重启丢掉全部会话连续性，带着它发布等于自爆。

**不是数据丢了，是数据被孤立了。** 消息一条没少地躺在 `arslan_messages` 里。

链条（亲核带 FILE:LINE）：`packaging/server_entry.py` 的 `_free_port()` **每次启动向 OS 要临时端口**
→ 窗口加载 `http://127.0.0.1:{每次不同}` → **localStorage 按 origin 分区，端口是 origin 的一部分**
→ `sessionPersistence.restoreThreads()` 找不到东西 → 铸一个新 `thread-${Date.now()}`
→ **而 `server/api/conversations.py` 每个接口都要求已知 conversation_id，没有列表接口**
→ 旧会话**永久不可达**。

🔴 **区分两个假说的证据是消息数的形状**（症状「重开后空白」两个假说都能解释）：
dev 库（浏览器 localStorage 持久）每会话累积 30/43/41 条；
**打包版库 10 个会话全是 2/2/5/4/2 条**，光一天 5 个不同 thread id 而侧栏显示 1 个。

🔴 **这个缺陷 dev 结构性看不见**（dev 端口恒 5173 ⇒ origin 恒定 ⇒ localStorage 恒在）。
**是「打包路径独有」家族的第三个成员**（前两个：websockets 缺失、wry 吃拖放），
同样由**用户干跑 demo 撞出**而非流水线发现 —— **④ 作为门内项的价值实证。**

**修法两半，(ii) 是实质**：(ii) `GET /conversations` 让服务端成为会话列表真源 —— 修这一类，
且**把存量 74 条捞回来**；(i) `DEFAULT_PORT` 固定 + 占用时回退 —— 只防未来，已孤立的回不来。

### ④ 用户验收回执 · **用户的活**
装上 v0.1.12 后逐条验并回执。当前待验（v0.1.12 主交付）：
- DeepSeek + 聊天贴中英截图**能读出**（A1 主交付；v0.1.11 上这条不工作）
- DeepSeek + 贴无字图 → **人话文案且点名查了哪些语言**
- 切一个带视觉的模型贴图 → 走一级，不该有 OCR 介入
- 第二大脑导航在**英文界面下是英文**
- 搜我的大脑：回车走管线、结果带片段、**没有相关度分数**

### ⑤ demo 素材 · **用户的活**
录屏 / 截图 / 文案。**不是我的活，但列在门内**，因为 launch 少不了它。

---

## 门外（launch 后），有次序

- **FU-2b 相关的次序修正 —— launch 后第一优先。**
  FU-2b 本身（eval 面抓取预算）**已在 `676887f` 落地**；这里排的是**次序修正**：
  它当初被登记为"排开源后"，实际是在通宵批里提前做掉的。蓝图里的顺序已按实际更新，
  **并带取代记录**（原次序 → 实际次序，不抹掉原来的判断）。

  > 📌 **SHA 更正（用户 2026-07-30）**：这里原先写的是 `679baf4`，那是供应链守卫的
  > 测试修复，不是 FU-2b。机器输出为准：`676887f = feat(evolution): FU-2b — bound the
  > eval surface`。事实（FU-2b 已落地）成立，引用错了 —— **哈希只认机器输出，不认我的记述**。
- 守卫新逮到的一切（默认进这里）。
- `registry.py` 沙箱警告的 i18n（运维面）。
- 逐技能 / 逐 MCP 工具的适配性矩阵行（v0.1.12 只上了传输层那一行）。
- P1 flake：aiosqlite teardown `Event loop is closed`（零测试失败但 CI 红，两次不同测试同形状）。
- macOS 11–12 的 Vision 语言集实测（无设备）。
- 聊天附件里的扫描版 PDF 之外的其余能力面。

---

## 🟢 evolution_auto 硬闸门已解除（审计方 2026-07-30）

三条件**逐项在 main 验证通过**：估算器 ✅ + `evolution_max_dispatches` 真闸 ✅ + FU-2b（`676887f`）✅。

**解除的是「允许开启」，不是默认值。`evolution_auto` 默认仍然 OFF**，由用户在 Settings 里自己打开
（`settings_service.evolution_auto` 的 docstring 记着它为什么从 ON 改成 OFF：当初那套理由的两半后来都被证明是假的）。

**同一 commit 修正 README:178**。那句 "There is no working spend cap yet" 现在是**假的** ——
派发闸和抓取预算都真实生效了。**往保守方向说假也是说假**：一个不存在的缺陷会让人以为
必须靠 provider 账单页兜底，而不是用产品自己的闸。改成分开写清楚：

| | |
|---|---|
| **有** | 派发次数上限（用户可在 Settings 设；超限的 attempt 在跑之前就被拒） |
| **有** | 抓取预算：live 每 run、eval **每 attempt**（后者是会放大的那一面） |
| **没有** | token 级精确上限 —— 计派发不计 token，是因为每次派发的花费差异太大；且预估 token 高估 3.7–5.2 倍，按真实花费设的上限会拒掉每一次尝试 |

⇒ 文案的定性：闸**约束的是数量级**，provider 账单页的硬限**仍然建议保留**。

## 📌 归档：「任何人任何设备」这条弧线的收口证据（用户 2026-07-30 记入）

v0.1.12 的发布流水线，在**干净的 CI runner** 上：

```
PASS  the probe environment has no third-party OCR      ← ⓪ 先证明这台机器没有可借的东西
PASS  the shipped app reads English off an image        ← 再做能力声明
44 passed, 0 failed
```

顺序是关键：探针**先证明自己的前提**，再作出声明。在我的开发机上同一份 DMG 是
**42 passed / 1 failed** —— 唯一那条 failed 正是这个探针**按设计拒绝作答**（本机装了
Homebrew tesseract）。两个结果不矛盾，它们一起说明了同一件事：**能力随包走，不是借来的。**

release run id `30565785174`；spctl：`accepted / Notarized Developer ID /
Developer ID Application: Mierzati Aireti (XULY3SAJ22)`。

## 📌 门规修订记录（2026-08-01，用户裁决 D1-D4）

- **D2 截断陷阱获准插队**（用户明示"插队修掉"——行使的是门主的裁量权，非三类自动插队）。
  已修：分支 `fix/skill-truncation-trap`，两半（空简介兜底 + 上限 2000→3000 实测定值），
  真实种子验证 deck-authoring 整段送达。**插入即划掉。**
- **D1** 工具传输层：确认**不插**，门外第一批。
- **D3** Settings mock 三个子决定全按提案（分组导航 / provider 卡片 / 删两个占位 tab）——
  ③ 从"mock 待批"变为"**mock 已批，待实现**"。
- **D4** 主动性循环 spec 已立（`docs/specs/2026-08-01-proactive-loop.md`），四个拍板项待审——
  门外第三批，不占门内。

## 门内余额

**1 项待我做**（⑦ 会话持久化 —— launch 阻塞）
**2 项待用户**（④ 验收回执、⑤ demo 素材）

> 2026-08-01 划掉四项：①②（`i18n/backend-display-text`）+ ⑥（`fix/hermetic-budget-refund`）
> + ③（`feat/settings-redesign`）。
> **插入两次**：⑥ 走「花钱失控」、⑦ 走「数据丢失」——三类例外用掉两类，第三类（个人信息泄漏）未用过。

> ④ 上押着五条挂账，回执后逐条销：整理层端到端 · 打包版实渲染（七块空状态 + Settings）·
> 窄屏响应式 · ⑥ 的真实并发（auto-evolution 真跑）·
> 🔴 **⑦ 重启 → 会话在、可继续**（用户 2026-08-01 加入验收表，回执改在 v0.1.15 上交）。

> 每轮交付末尾附一行余额，格式：`门内余额：我 N 项 / 用户 M 项（剩：…）`

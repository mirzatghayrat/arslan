# 第二大脑前端：只读核对结果 + 剩余项 spec

base main = `a97d2ba`。任务书：`arslan-second-brain-frontend-brief`（2026-07-18 登记）。
任务书自带流程约束：**先只读 → spec → plan，勿直接编码**。本文件是「只读」与「spec」两步；未写任何生产代码。

---

## 0. 只读核对 —— **任务书的规模判断已经过期**

登记时它是一个 F0/F0.5/F1/F2 四阶段的大轮。逐个文件核过之后，**十项里九项已经在 main 上**：

| 阶段 | 项 | 现状（亲核） |
|---|---|---|
| F0-1 | D 活跃时间条 | ✅ `BrainActivityStrip.tsx` + 测试 |
| F0-2 | 协调刷选（hover/select 共享态） | ✅ `BrainBrushing.test.tsx` 存在，且测试标题记着一个已修的真 bug：`focusedId` 曾同时当 hover 通道和标签筛选 |
| F0-3 | 快速收集（笔记 / ingest） | ✅ `NoteEditor.tsx` |
| F0-4 | 索引健康 | ✅ `BrainIndexHealth.tsx` + 测试 |
| F0-5 | 反链跳转 | ✅ `BrainEntryDetail.tsx` |
| F0-6 | 图谱 craft | ✅ `BrainGraph.tsx`（d3-force 保留） |
| F0.5-7 | 撤销取代 | ✅ EntryDetail 内 |
| F0.5-8 | 敏感徽章 | ✅ EntryDetail 内 |
| F0.5-9 | 出处透镜 | ✅ BrainGraph 内 |
| **F0.5-10** | **搜我的大脑（走 retrieve_scoped 同管线 + 三视图联动）** | ❌ **唯一真缺口**，见 §1 |
| F1 | ghost 节点 / as-of 滑杆 / 信念河流 | ✅ `BrainAsOfSlider.tsx`、`BrainLineage.tsx`、`temporal.ts` |
| F2 | 记忆提案箱 | ✅ `BrainProposalInbox.tsx` + 测试 |

**这正是「先只读」这条流程要买到的东西**：不看就动手，会重建九个已经存在的东西。

---

## 1. 唯一缺口：搜我的大脑

### 1.1 现状要说准（不要把两件事混成一件）

`BrainNav.tsx:134-136` **有一个搜索框**，但它是**前端对已加载树做的字符串过滤**（本地 `q` state）。
缺的是任务书写的那件事：**走后端 `retrieve_scoped` 同一条检索管线**，并让命中在**图谱 + 时间条**同步高亮。

两者差别不是程度问题：本地过滤只能匹配已经拉到前端的节点标题；`retrieve_scoped` 走 FTS5 +（若已配置）嵌入，能命中正文，且**和 spawn 真正读记忆时用的是同一条路**——这才是「搜我的大脑」的意义：你看到的召回，就是它看到的召回。

### 1.2 后端：新增 `GET /brain/search`

- 参数：`q`（必填）、`limit`（默认 20，上限 50）。
- 走 `server/services/knowledge.retrieve_scoped`，**不新写一套检索**。
- 返回：`{query, results: [{kind, ref, title, snippet, rank}], ranking: "lexical" | "hybrid", truncated}`。

🔴 **`ranking` 是诚实性字段，不是元数据洁癖。** 任务书的时效基线写明：`knowledge.rerank` 是**词面重叠**（CJK-aware），**不是语义分**。所以：
- **UI 绝不渲染 `0.92` 式的语义相关度分**；
- `ranking` 如实报当前管线（无嵌入 ⇒ `lexical`），前端据此措辞；
- `truncated` 同 D5 读端点的先例：命中上限必须告知，否则截断结果会被当成全部。

🔴 **测试的第一检查项（任务书制度化条款）**：brain 的读端点直接开**生产** `AsyncSessionLocal`，`client` fixture 的依赖覆盖够不着。新端点若沿用该形状，测试必须
`monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)`（先例 `tests/server/test_brain_api.py:25`）。**不照做会打到开发者真实库。**

### 1.3 前端：接进既有刷选，不新建 store

- 搜索结果面板复用现有 hover/select 共享态（`BrainBrushing` 那套），**扩展它，不硬上新 store**（任务书明令）。
- 命中 → 图谱节点高亮 + 时间条对应行高亮；点击 → 开 `BrainEntryDetail`。
- 本地过滤框**保留**（快速找已知条目仍然有用），但要和服务端搜索**在界面上可区分**，否则用户不知道自己看的是哪一种召回。

### 1.4 验收
1. 命中在**三处**同步高亮（图谱 / 时间条 / 详情），有测试。
2. `ranking="lexical"` 时界面**不出现任何语义相关度数字**；有测试断言这一点（这是最容易被"顺手加个分数"破坏的一条）。
3. `truncated=true` 时界面明说"还有更多"，不静默截断。
4. vitest 全绿 + `tsc --noEmit` 干净 + 新组件带测试 + i18n 六语齐。

---

## 2. 本轮**不做**（任务书里已完成或另立项的）

- F0/F0.5 其余九项、F1、F2：**已在 main**，不重做。
- 进化面板 dogfooding 三条（ENQUEUE 花钱确认闸 / 空状态教学 / "Why no proposals" 翻人话）：任务书里写明**家在 Diagnostics，不进 brain**，且属独立登记，不并入本 spec。
- 语义 rerank、复习队列/间隔重复：任务书明写各自单独立项。

---

## 3. 待你裁决

1. **`GET /brain/search` 的返回是否要带 `snippet`？** 带的话要决定截断长度与是否高亮匹配词；不带则结果只有标题，点开才看到正文。我倾向带，但这会让端点多返回一份正文片段，属于新的数据出口。
2. **本地过滤框与服务端搜索并存的形态**：同一个框（输入即本地过滤、回车走服务端）还是两个入口？前者省位置但两种召回混在一个框里，用户不易分辨自己看的是哪一种。

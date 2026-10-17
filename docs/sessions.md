# 多会话协作规矩

**所有在本仓库工作的会话，开工前必读。** 当轮的分道、任务卡和合并顺序，见 `docs/plans/0162/README.md`。

**唯一的共享内存是这个仓库。** 交接、计划和决定都要以提交物的形式存在。下面这些都不算交接：会话自己的记忆、草稿区、本机文件、聊天记录。

---

## 1. 编号与职责

| 编号 | 职责 |
|---|---|
| ⓪Plan | 维护当轮计划和任务卡；M 线（跑分、本机周报、体感验收）；发版前判定是否达到门槛 |
| ①iOS | iPhone App（另一个仓库）。本仓库里只读它依赖的 Mac 端契约 |
| ②Main | 实现 F、C、K、S 各线；管合并队列、共享文件仲裁、迁移号登记、CI 健康、版本号与发版准备 |
| ③Hands | 负责 Hands：`desktop/hands/**`、`server/registry/hands_tools.py`、`server/services/hands_service.py`、`server/api/hands.py`、`scripts/hands_smoke.py` |

- 新开的会话往后编号（④、⑤……），开工前先在当轮 README 的分道表里登记。
- 版本号、打 tag、发布、合并，都由用户拍板、用户点。

## 2. 文件归属

- **默认规则：** 谁的任务卡，谁改卡上「改哪些文件」列的文件。卡上「不许碰」的文件不改。
- **Hands 的文件归 ③Hands。** 其他道的卡要动它们，必须由 ③Hands 审。
- **Bridge 契约文件不改帧格式。** 这些文件是：`desktop/bridge/**`、`server/ws/bridge.py`、`spec/mobile-bridge/**`、`server/api/phone.py`、`server/services/phone_*.py`。确实要改，先问 ①iOS 和 ②Main。
- **发现要动别人的文件时：**
  1. 停下，不要改；
  2. 在 PR 描述或给对方的消息里，写清楚要改什么、为什么；
  3. 由文件的主人来改，或者由 ②Main 仲裁后指定一个人改。

## 3. 共享热点文件

| 文件 | 规矩 |
|---|---|
| `server/orchestrator/arslan.py`、`server/orchestrator/tool_loop.py`、`server/orchestrator/memory.py` | 当轮 K 线主改。其他 PR 只做小改动，合并时排在当前打开的 K 线 PR 之后；rebase 时两边都保留 |
| `web/src/locales/*.json`（6 种语言） | 新加的 key，6 种语言同一个 PR 一起加；不改别人的 key；冲突在文件末尾，rebase 时两边都留；`web/src/__tests__/locale-parity.test.ts` 通过才算完 |
| `docs/CAPABILITY_INVENTORY.md` | 生成物，不手改、不手工解冲突。rebase 后重新生成：`.venv/bin/python -m scripts.capability_inventory > docs/CAPABILITY_INVENTORY.md`（在仓库根目录、用项目的虚拟环境运行）。C5b 合并后，只在发版 PR 里生成 |
| `server/db/migrations/**`、`tests/server/test_migration_runner.py`、`server/db/models.py` | 迁移号按 §4 处理 |
| `server/main.py`、`web/src/App.tsx` | 只做小改动。路由和启动步骤加在末尾，不重排；rebase 时两边都留 |
| `docs/releases/*.md` | 只有发版 PR 写。每一句对用户的承诺旁边，写出对应的测试名 |
| `docs/plans/**`、`docs/specs/**` | 计划只由 ⓪Plan 改；任务卡的状态由 ②Main 更新；spec 只在决定变化时改，并注明日期 |

## 4. 迁移号

- **谁分配：** ②Main，在当轮 README 的登记表里分配。一个 PR 最多带一个迁移。
- **同步改的地方：** 加一个迁移要同时改这几处，缺一处 CI 就红：
  - 版本文件 `server/db/migrations/versions/_00NN_*.py`；
  - `server/db/migrations/runner.py` 里的导入和 `MIGRATIONS`；
  - `tests/server/test_migration_runner.py` 里的 id 列表；
  - `server/db/models.py`。
- **顺序：** `MIGRATIONS` 按数字升序排列。合并前，如果别的迁移已经先合了，该 PR 先把自己的号改成下一个空号，再合。
- **冻结：** 一个号只要进过正式版本，就永远不能改。`runner.assert_supported_schema` 会拒绝启动带未知 id 的数据库。
- **别碰真实数据：** 没合并的迁移，不许在用户的真实数据目录上跑；开发构建用临时数据目录。

## 5. 分支、PR、合并

- **分支名：** `claude/<版本><编号>-<主题>`，例如 `claude/0162-k1-native-tools`。
- **一个 PR 只做一件事。** 产品代码改动不超过约 800 行，测试、翻译和生成的文件不算在内；超过就拆。
- **PR 的写法：**
  - 标题写它推动的是哪个门槛；
  - 描述里链接对应的任务卡；
  - K 线 PR 要贴跑分的前后对比，没有对比不合。
- **合并顺序**由依赖图决定，不是先到先得。顺序表在当轮 README。
- **rebase 纪律：**
  - 开 PR 前和合并前，各 rebase 一次到最新 main；
  - 冲突按 §3 处理；
  - 不 force-push 别人的分支；
  - 破坏性的 git 操作单独执行，不放进 `&&` 链里。
- **说 CI 绿时**，附上 run id 和结论。

## 6. 文档卫生

- **不写进仓库的东西：**
  - 本机绝对路径；
  - 私聊内容；
  - 用户数据库的摘录（只有汇总数字可以）。
- **草稿区**（系统临时目录）会被清理，不要放交付物。
- **范围冻结：** 新想法写进当轮 README 的「下一版候选」，不进本版。

## 7. 发版

- **版本号的唯一来源**是 `desktop/src-tauri/tauri.conf.json`，必须是三段 semver：
  - 四段的版本号（比如 0.1.61.1）读配置时就会报错；
  - 带 `-` 的 tag 会被发成预发布版，更新器看不到。
- **发布说明：** 每一句对用户的承诺，都要对得上一个测试。
- **打 tag** 要用户点头；**发布**由用户点。

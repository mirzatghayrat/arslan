# D1 回合做出的文件送到用户手上（窗口和 iPhone）

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须（用户报告：在 iPhone 上要一张 Mac 截图，只收到一个 Mac 上的路径） |
| 依赖 | — |
| 合并位置 | **不进 K 线串行链。** 改 `tool_loop.py`（原生参数表）和 `arslan.py` 两个热点文件。K1 合并后的第一个空档合；如果 D1 已经就绪而 M1B 还没跑（K1 合不了），D1 可以先于 K1 合，K1 rebase（⓪Plan 定） |
| 推动的门槛 | §5.3 新增一条手机上的体感验收（见「验收」） |
| 分支 | `claude/0162-d1-deliver-files` |
| 迁移号 | 无 |
| 来源 | 2026-10-18 用户报告，经 ①iOS 转来（iPhone 1.0 build 18 + Mac 0.1.62） |

## 目标

用户要的文件（截图、图表、导出的表格）由这一回合做出来以后，出现在回答下面：窗口里是文件卡，iPhone 上是收到的文件。和 Mac 交付的文件一样，不再只给一个路径。

今天的情况（`origin/main`，⓪Plan 核过）：

- 手机只拿得到一次运行**登记过的产物**：
  - Bridge 那边：`ConversationLinks.offerFiles(ofRun:)`（`desktop/bridge/Sources/BridgeCore/ConversationLinks.swift:155`）。
  - 服务端那边：`phone_reads.run_files` → `artifact_store.list_artifacts(run_id)`（`server/services/phone_reads.py:79-82`）。
- 登记产物的只有两条路：
  - `write_file` / `edit_file` 存下文字文件的快照（`server/registry/file_tools.py:370`，`store_bytes`）；
  - 后台作业结束时导出工作区（`server/services/artifact_store.py:112`）。
- 聊天回合里用命令做出来的文件（例如 `screencapture` 存的 PNG），或任何二进制文件，都不会登记，所以手机收不到，窗口里也没有文件卡。
- 模型不知道这条消息来自 iPhone：`source == "phone"` 只用来在窗口里标「来自 iPhone」（`server/orchestrator/arslan.py:420-423`），没有传进提示词。所以它会回一个对手机用户毫无用处的 Mac 路径。
- iPhone 那边已经好了：build 18 会显示并能打开收到的 `file.offer`（①iOS 报告）。**不改 Bridge 帧。**

## 改哪些文件

- `server/registry/file_tools.py`：新工具 `attach_file(path, title?)`，把一个现有文件登记成本次运行的产物。
  - 用 `artifact_store.store_bytes(run_id, title, data)`。
  - 路径照读文件的规矩走 `file_reader.resolve`：只认可读的文件夹，拒绝隐藏文件和像凭据的名字，不跟随链接出去。
  - 大小上限：照 Bridge 现有的文件传输上限，开工时核。超了就明确拒绝并说明原因。
  - 效果按「本地」算，不出卡。文件只到用户自己配对的设备和本机窗口。
- 工具注册：注册处和 `tool_loop.py` 的 `_NATIVE_PARAM_SCHEMAS`。工具只追加在最后，不挪别的工具（K3、K7 的约定）。
- `server/orchestrator/arslan.py`：把 `source` 带进回合。来自 iPhone 时，在本回合的上下文里加一句：用户在手机上，Mac 上的路径对用户没用；用户要的文件用 `attach_file` 附上。
  - 这句放在本回合会变的那一段，不放进固定前缀（K3 的缓存约定）。
- 测试，见「验收」。

## 不许碰

- Bridge 帧格式、iOS 代码。
- 自动登记「回合里碰过的所有文件」：一个回合会产生很多临时文件。也不去猜回答里提到了哪些路径。只登记模型明确附上的。
- `artifact_store` 的存储格式；`write_file` 的快照逻辑（F2 的验收依赖它）。

## 怎么做（要点）

1. 先写测试：用命令在工作区做出一张 PNG，`attach_file` 之后，`list_artifacts` 里有它，`phone_reads.run_files` 也返回它。
2. 工具说明写清楚：用户要文件、或用户在手机上时，用它把文件附到回答下面；不要只回路径。
3. 来自 iPhone 的那一句：用测试确认只在 `source == "phone"` 时出现。

## 验收

- **测试：**
  - 命令做出的 PNG 附上之后，成为本次运行的产物，手机能读到；
  - 拒绝：可读文件夹之外的路径、像凭据的名字、指向外面的链接、超过上限的文件，都有明确的错误；
  - 来自 iPhone 的回合，上下文里有那一句；来自窗口的回合没有。
- **体感（加进 M3）：** 在 iPhone 上让 Arslan 截一张 Mac 的图，图片出现在回答下面，能打开；在窗口里同样要，回答下面有文件卡。
- 完成证据四项（`docs/sessions.md` §8）。

## 量级

产品代码约 +100 行（工具约 60 行、注册和参数表约 15 行、`arslan.py` 约 15 行）。测试另算。

## 风险与回退

- **风险：模型忘了附。** 工具说明和来自 iPhone 的那一句两处提醒；M3 那条体感验收会抓到。
- **风险：把不该给的文件送出去。** 只认可读文件夹、拒绝凭据名和外链，和 `read_file` 同一套规矩；文件只到本机窗口和用户自己配对的 iPhone。
- **回退：** revert 这一个 PR。没有迁移，也不改 Bridge。

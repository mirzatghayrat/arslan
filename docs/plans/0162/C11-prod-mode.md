# C11 删掉 prod 模式：先把打包版加固，再删

| 项 | 内容 |
|---|---|
| 道 | ③Hands（⓪Plan 2026-10-21 分；由 ②Main 审） |
| 版本 | v0.1.63 |
| 分级 | 应该（云端审计 [3]，用户转来，U14） |
| 依赖 | C10（已合，Docker 删了以后只剩它用 prod 模式）；**#298（SECURITY.md 改正）先合**，两边都改 SECURITY.md |
| 合并位置 | 不进 K 线严格链；一个 PR，先加固、后删除 |
| 推动的门槛 | 打包版的安全底线不靠一个环境变量；用户 2026-10-21 定的「干净」目标（`docs/sessions.md` §11） |
| 迁移号 | 无 |
| 来源 | 云端「Arslan 0.1.62 规划审计」2026-10-21 的结论 [3]（Opus 5.5，main `da49a794`）。行号是审计核的，开工时再核 |

## 为什么能删

桌面版跑的是 `dev` 加 `ARSLAN_PACKAGED`；恢复功能还要求必须是 `dev`。`ARSLAN_ENV=prod` 现在只有已经删掉的 Docker 在用。

## 先加固（同一个 PR 的前半）

1. 打包版密钥为空时拒绝启动，并且忽略 `ARSLAN_ALLOW_INSECURE_SECRETS`。今天会回退到公开密钥、只打一条警告（`server/main.py:77-82`）；环境里继承了这个变量，就能用公开密钥存 API key。
2. `ARSLAN_PACKAGED` 改成强制赋值，不用 `setdefault`（`server_entry.py:64`）。今天继承一个 `ARSLAN_PACKAGED=0` 就能关掉鉴权。
3. 打包版 CORS 默认为空（`server/config.py:155-158`）。
4. 打包版拒绝没有 Origin 的 WebSocket（`server/security.py:109-110`）。
5. 打包版禁用测试路由（`server/main.py:506-510`）。
6. 顺手修：`POST /settings/mcp-token/generate` 补上「出示当前 token」的检查，做法同 access-token（`server/api/settings.py:129-136`）。

## 再删（同一个 PR 的后半）

- 删 `is_prod` 和 `ARSLAN_ENV=prod` 那一支。
- 文档同步：`SECURITY.md:14-16`、`:27`，README，`CONTRIBUTING.md`，`docs/QUICKSTART.md:16`，`.env.example`。
- 测试同步，包括 `recovery_secret.rs:270`。
- 顺带删死代码 `code_sandbox.net_profile`（凭据代理的遗留，审计 [1]）。

## 不许碰

- `web/` 和静态文件服务；Hands、iPhone Bridge 的文件。
- 开发模式（`dev`，不打包）本机零配置能起这件事不变。

## 验收

- **测试：** 六项加固各一条，都在打包模式下：
  - 空密钥拒绝启动，带着 `ARSLAN_ALLOW_INSECURE_SECRETS` 也拒绝；
  - 继承 `ARSLAN_PACKAGED=0` 不能关鉴权；
  - CORS 默认为空；
  - 没有 Origin 的 WebSocket 被拒；
  - 测试路由 404；
  - 不出示当前 token 不能重新生成 mcp-token。
- 删掉 `is_prod` 以后，`git grep -n "is_prod\|ARSLAN_ENV=prod"` 在代码和文档里没有（逐条说明留下的）。
- 安全相关：由 Opus 5.5 写和审（用户的规矩）；改过的 SECURITY.md 段落定稿后先发云端审计看。
- 完成证据四项（`docs/sessions.md` §8）。

## 量级

产品代码约 ±150 行，加测试和文档。

## 风险与回退

- **风险：** 有人照 `.env.example` 用 prod 模式在服务器上跑。v0.1.63 的发布说明写明「不再有 prod 模式；桌面版是唯一支持的形态」（和 C10 删 Docker 一起说）。
- **风险：** 打包版空密钥拒绝启动，老用户升级后起不来。开工时先核打包版首次启动是否一定会生成并保存密钥；没有的话，这一条改成「生成并保存」而不是「拒绝」，PR 里写明。
- **回退：** revert 这个 PR。

# C10 删掉 Docker 这条部署路径

| 项 | 内容 |
|---|---|
| 道 | ③Hands（⓪Plan 2026-10-21 分；由 ②Main 审） |
| 版本 | v0.1.63 |
| 分级 | 应该（用户 2026-10-21 定，U13 第 5 条） |
| 依赖 | — |
| 合并位置 | 不进 K 线严格链，什么时候合都行 |
| 推动的门槛 | 用户 2026-10-21 定的目标：到 v0.1.65 干净、简单、好用（`docs/sessions.md` §11） |
| 迁移号 | 无 |
| 来源 | ④参谋的清理清单 §4、§6 第 6 条；用户：以后只用 Mac 桌面 App，不再用浏览器访问 |

## 删什么

- 仓库根目录的 `Dockerfile`、`docker-compose.yaml`、`.dockerignore`。
- `README.md`、`README.zh-CN.md`、`README.ja.md`、`README.es.md`、`README.de.md`、`README.tr.md` 和 `docs/QUICKSTART.md` 里讲 Docker 的段落（⓪Plan 在 main 上查过，这 7 份都提到 Docker）。
  - 只删这几段。其余对外文档等 v0.1.65 一次更新（U13 第 6 条）。这里提前改，是因为文件删了，这几段就成了错的。
- ⓪Plan 在 main 上查过：`.github/`、`scripts/`、`desktop/` 里都没有用到 Docker。所以 CI 和打包不受影响；开工时再查一遍，按字符串查。

## 不许碰（用户特别交代：不能影响现有能力，Hands、iPhone 都要在）

- `web/`，以及 `server/main.py` 里挂 `StaticFiles` 的静态文件服务（main 上 `:674` 一带）：Mac App 的界面就是这套 `web/` 界面，由本地服务端提供；tauri 只放一个启动页。
- `ARSLAN_ENV=prod` 和相关的鉴权：现在只有 Docker 用它，但它是安全面，先给云端审计看，再单独定（U13 第 5 条）。这张卡不碰。
- Hands、iPhone Bridge 的文件。

## 验收

- `git grep -niI docker` 在代码、CI、脚本里没有引用（文档里留下的，逐条说明为什么留）。
- CI 全量绿，包括 macos 那一项（附 run id）。
- PR 里写明：打包的 App 照常起、Hands 和 iPhone 照常连。macos CI 证明打包成功；Hands 和 iPhone 跟着下一次冒烟一起看（F5b-1 的冒烟，或 R63 的 M3）。
- 完成证据四项（`docs/sessions.md` §8）。

## 量级

整份删除 3 个文件，加 7 份文档里的段落。

## 风险与回退

- **风险：** 有人照着旧的 README 用 Docker 跑。v0.1.63 的发布说明写一句「不再提供 Docker 部署」。
- **回退：** revert。

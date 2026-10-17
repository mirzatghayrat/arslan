# C2f 网页杂项死代码、没用的依赖、误提交的文件

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 0.1.62 |
| 分级 | 必须 |
| 依赖 | C1 |
| 合并位置 | C1 之后随时。不碰 K 线热点，也不碰 `web/src/App.tsx`、locales。C5a 也改 `.gitignore`（改的是 `:44-50` 的注释），后合的那个 rebase |
| 推动的门槛 | 无直接门槛；净减代码和依赖。间接：`npm ci` 少装几个包，仓库里不再有构建缓存和浏览器快照 |
| 分支 | `claude/0162-c2f-misc-web-repo` |
| 迁移号 | 无 |

## 目标

删掉网页端没人引用的文件和组件、没人 import 的依赖，以及误提交进仓库的缓存和快照文件，并让 `.gitignore` 挡住它们，不再犯。

## 改哪些文件

以下都在 `fb6d7230` 上核过。

**没人 import 的文件**
- `web/src/api/workspace.ts`（12 行）。服务端的 `/workspace*` 路由不动。
- `web/src/components/Sparkline.tsx`（16 行）。`RunReplay.tsx:250` 的 `showSparkline` 是个变量，不是这个组件。

**`ToolsView` 和只被它用的 `ToolCard`**（`web/src/components/CapabilityCatalog.tsx:101-208`）
- 只在 `kind="tools"` 时渲染。产品里唯一的调用是 `Capabilities.tsx:135`，传的是 `kind="skills"`；`kind="tools"` 只出现在测试里。
- 删掉以后，`kind` 参数只剩 `"skills"`：可以去掉这个参数，或者收窄类型。
- 测试：
  - `capability-filter-ui.test.tsx`、`capability-catalog.test.tsx`、`catalog-localization.test.tsx` 里 `kind="tools"` 的用例删掉；
  - `empty-states.test.tsx:57` 那一行 `empty-capabilities-filtered`（「Tools, filtered」）跟着改。

**依赖**（`web/package.json`）
- 删 `motion`（`:27`）、`ogl`（`:28`）、`autoprefixer`（`:47`）。`web/src`、`vite.config.ts`、`web/scripts` 里都没有 import，也没有 postcss 配置。
- `vite` 写了两次（`:34` 在 dependencies，`:53` 在 devDependencies）。保留 devDependencies 那一份：CI（`ci.yml:417`）、`release.yml:113`、`packaging/build_dmg.sh:124` 和 `Dockerfile:5` 都是普通的 `npm ci`，不带 `--omit=dev`。
- `web/package-lock.json`：重新生成。它是生成文件，不计入行数。
- `web/src/__tests__/sidebar-second-brain.test.tsx:24-28`：删掉 `motion/react` 的 mock。

**误提交的文件**
- `node_modules/.vite/vitest/da39a3ee5e6b4b0d3255bfef95601890afd80709/results.json`，在仓库根目录，不是 `web/node_modules`；
- `.playwright-mcp/page-2026-09-29T19-18-53-082Z.yml`、`.playwright-mcp/page-2026-09-29T19-19-13-863Z.yml`。

这 3 个文件都用 `git rm`。

**`.gitignore`**
- 根目录加 `/node_modules` 和 `.playwright-mcp`，不带结尾斜杠，理由见 `.gitignore:6-8`。
- `web/.gitignore` 已经有 `node_modules`，不用动。

## 不许碰

- 服务端的 `/workspace`、`/workspace/open`、`/workspace/reveal` 路由。
- `CapabilityCatalog` 的 `SkillsView` 和 `kind="skills"` 这条路径。
- 其他依赖的版本。本卡只删，不升级。
- `desktop/package.json`、Cargo 文件。版本号的事归 C5b。

## 怎么做（要点）

1. 删依赖之前先确认：

   ```bash
   rg -n "from ['\"](motion|ogl|autoprefixer)" web/src web/scripts web/vite.config.ts
   ```

   应该无结果。
2. 进 `web/` 跑 `npm install`，重新生成 lock，再跑 `npm ci` 确认从干净状态能装上。
3. 跑 `npm run lint`、`npm test`、`npm run build`，三个都要过。

## 验收

- CI 的 frontend 任务绿，贴 run id。如果碰上已知不稳定的 `inbox-v2.test.tsx`，按 F5a 卡里的说法单独写明。
- `git ls-files node_modules .playwright-mcp` 输出为空。
- 再跑一遍 vitest，`git status` 里不出现新的 `node_modules/.vite`。

## 量级

产品代码约 −140 行。另有 `package-lock.json`（生成文件），以及 3 个误提交文件，约 22 KB。

## 风险与回退

- **风险：** 删掉 `kind="tools"` 以后，将来想恢复工具目录页得重写。0.1.62 的能力页没有这个入口；K7 走的是按需检索，用不到它。
- **风险：** 重新生成 lock 会顺带升级间接依赖的小版本。生成时用 `npm install --no-audit --no-fund`，PR 描述里写明 lock 的 diff 只来自删包。如果有别的变化，单独说明。
- **回退：** revert 本 PR。

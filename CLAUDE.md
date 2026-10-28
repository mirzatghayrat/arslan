# Arslan：给在本仓库工作的 agent

开工前先读这三份：

1. `docs/sessions.md`：多会话协作规矩（文件归属、热点文件、迁移号、分支与合并、文档卫生、发版）。
2. 当轮的总计划：`docs/plans/2026-10-17-0162-execution-first.md`。先看开头的「决定记录」和「更正记录」。
3. 当轮的分道表和任务卡：`docs/plans/0162/README.md`。只做分给你的卡。

几条最常被违反的规矩：

- 一个 PR 只做一件事，产品代码不超过约 800 行。
- 不改别人的文件，也不改 Bridge 的帧格式。要改时先停下来问。
- 不写本机路径、私聊或用户数据。草稿区里的东西不算交接。
- 每个 PR 和每次说「做完了」，都写完成证据四项：做了什么验证、覆盖到哪、没覆盖到哪、还剩什么风险（`docs/sessions.md` §8）。
- 留着的旧路径、兜底和回退开关，代码注释和任务卡里都写明哪个版本删、或什么条件下删（§9）。
- 合并、打 tag、发布都由用户点。
- **Everything written to GitHub is in English (user, 2026-10-28):** code, comments, commit messages, PR titles, bodies and comments, plan docs and task cards, bundled skills, READMEs. Existing Chinese text is not rewritten; new lines in an older Chinese file are still English. Chat with the user stays in Chinese. Exceptions: quoting exact Chinese inside an English sentence (UI labels, the user's or the model's words, session names such as ④参谋); data that has to match Chinese input (for example the secret keywords in `arslan/companion/content_policy.py` or app names in `desktop/hands/policy.json`); translation files and tables (for example `web/src/locales`, `desktop/src-tauri/native_menu_messages.json`, and the iOS `*.xcstrings` / `*.lproj`); tests, evals and fixtures whose input is Chinese; the multilingual `docs-site`; and, until the user decides, the iOS app's UI copy (its string catalog's source language is zh-Hans; comments, docs and commits in the iOS repo are English from now on). See `docs/sessions.md` §6.

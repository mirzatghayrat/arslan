---
name: webapp-testing
description: Web 应用测试方法 —— 用 Playwright 测本地 Web 应用（验证前端功能、调试 UI、截图、看浏览器日志）时的"侦察-再动作"方法论与常见陷阱。
version: 0.1.0
authors:
  - Arslan
source: adapted from anthropics/skills · webapp-testing (Apache-2.0, © 2025 Anthropic PBC); bundled with_server.py and example scripts removed — methodology only
---

## Trigger

当要测试本地 Web 应用 —— 验证前端功能、调试 UI 行为、截图、查看浏览器日志时激活。这是用 Playwright 做浏览器自动化时的方法论（选择器策略、时序、侦察模式），而非某段可直接跑的脚本。

## 决策规则

- **先分静态还是动态**：静态 HTML → 直接读 HTML 文件定位选择器，成功就据此写脚本，失败就当动态处理；动态应用 → 走"侦察-再动作"。
- **侦察-再动作模式**：先导航并等待 `networkidle`（关键：等 JS 执行完）→ 截图或检查 DOM → 从渲染后的实际状态识别选择器 → 再用发现的选择器执行动作。别凭空猜选择器。
- **动态应用检查 DOM 前必等 networkidle**：`page.wait_for_load_state('networkidle')` 之前就检查 DOM 是最常见的坑；等到网络空闲再检查。
- **选择器用描述性的**：优先 `text=`、`role=`、语义化 CSS 或 id；配合 `wait_for_selector()` 等恰当等待，别用脆弱的定位。
- **截图是廉价的真相**：`page.screenshot(full_page=True)` + `page.content()` 先看清渲染后的页面再操作，比盲点更可靠。
- **收尾干净**：同步脚本用 `sync_playwright()`，headless 模式启动 chromium，用完 `browser.close()` 关闭浏览器。
- **注**：原技能依赖若干打包脚本（如管理服务器生命周期的 helper）来跑；Arslan 分身不执行脚本，这里只保留其可迁移的测试方法。若在能执行代码的环境里，把上述模式落成 Playwright 脚本即可。

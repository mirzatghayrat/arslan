<div align="center">

<a href="https://aralem.dev/arslan/">
  <img src="docs/assets/readme/banner.jpg" alt="Arslan——干活，先问再动手。Mac 刘海里的 Arslan Island 正在等你批准移动文件。" width="100%">
</a>

<br/><br/>

**一个住在你 Mac 上的开源 AI agent——也听你 iPhone 的。**<br/>
**它能用你的终端、操作你的 app，你聊天的时候它在后台接着干。**<br/>
**凡是以你的名义做的事，都要等*你*点头。**

<br/>

[![Release](https://img.shields.io/github/v/release/mirzatghayrat/arslan?style=flat-square&color=34d399&label=release)](https://github.com/mirzatghayrat/arslan/releases/latest)
[![License](https://img.shields.io/badge/license-Apache--2.0-4c72e0?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/macOS_11+-Apple_Silicon-111?style=flat-square)](README.md#status--honest-about-whats-proven)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-2ea44f?style=flat-square)](CONTRIBUTING.md)

<br/>

<a href="https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg"><img src="docs/assets/btn/zh-download.png" alt="下载 macOS 版" height="28"></a>&nbsp;&nbsp;<a href="https://aralem.dev/arslan/"><img src="docs/assets/btn/zh-website.png" alt="官网" height="28"></a>&nbsp;&nbsp;<a href="docs/QUICKSTART.md"><img src="docs/assets/btn/zh-quickstart.png" alt="快速上手" height="28"></a>&nbsp;&nbsp;<a href="SECURITY.md"><img src="docs/assets/btn/zh-security.png" alt="安全" height="28"></a>&nbsp;&nbsp;<a href="CONTRIBUTING.md"><img src="docs/assets/btn/zh-contributing.png" alt="参与贡献" height="28"></a>

<a href="README.md"><a href="https://aralem.dev/arslan/docs/zh/"><b>📖 技术文档</b></a> <sub>(中文 · <a href="https://aralem.dev/arslan/docs/">English</a>)</sub>

<img src="docs/assets/btn/lang-en.png" alt="English" height="22"></a>&nbsp;<img src="docs/assets/btn/lang-zh-on.png" alt="简体中文" height="22">&nbsp;<a href="README.de.md"><img src="docs/assets/btn/lang-de.png" alt="Deutsch" height="22"></a>&nbsp;<a href="README.ja.md"><img src="docs/assets/btn/lang-ja.png" alt="日本語" height="22"></a>&nbsp;<a href="README.es.md"><img src="docs/assets/btn/lang-es.png" alt="Español" height="22"></a>&nbsp;<a href="README.tr.md"><img src="docs/assets/btn/lang-tr.png" alt="Türkçe" height="22"></a>

</div>

---

<div align="center">
  <img src="docs/assets/readme/island.gif" alt="Arslan——干活，先问再动手。Mac 刘海里的 Arslan Island 正在等你批准移动文件。" width="760">
  <br/>
  <sub>后台任务实时显示在刘海里：它在干活，移动你的文件之前<b>停下来问你</b>，做完告诉你发现了什么。</sub>
</div>

## 你可以这样问它

> *“把今年的发票从下载文件夹整理到一个文件夹里，告诉我缺了哪几个月。”*<br/>
> *“下载文件夹里有多少重复文件？把副本移到废纸篓，保留最新的。”*<br/>
> *“把 sales_q3.csv 做成一页带图表的报告。”*<br/>
> *“在备忘录里新建一条笔记，写下这次会议的三个要点。”*<br/>
> *“每天早上 9 点看一下这个网页，价格变了就告诉我。”*

它干活的时候你可以接着聊。凡是删除、发送、安装或操作其他 app 的事，**都会先问你**——在 Mac 上或 iPhone 上。

## 一分钟上手

1. **[下载 macOS 版 Arslan](https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg)**（Apple Silicon，macOS 11+）——已签名、已公证，会自动更新。
2. 把它拖进 **应用程序** 并打开。
3. 在设置里粘贴一个模型 API key——OpenAI、Anthropic、Gemini、DeepSeek、通义千问、Kimi、OpenRouter 等等——或者通过 **Ollama** 接本地模型。

就这样。不用注册账号，也没有 Arslan 服务器。

## 0.1.63 新功能：回复中途改变方向、回答随书写显示、撤回一轮

Arslan 工作时你可以接着输入消息，它会在下一步就到达这条回复；回答随模型书写即时显示；最多四个读取同时进行；在某一轮第一次改动你的工作文件夹之前，Arslan 会保存一个检查点，所以“撤回这一轮”能把文件放回去。你要的文件会以附件形式返回，iPhone 上也一样。有两项安全方面的改变要先说：**每条新的终端命令现在都会在运行前先问你**（可在 设置 › Arslan 能做什么 › 终端 里切回去），以及**定时任务在这一版里不运行任何命令**——需要命令的步骤会被跳过，并列在你的收件箱里。每条回复和每个后台任务默认也会在模型花费 $2 时停止，专家时代的代码也已删除（产品代码比 0.1.62 少 12,514 行）。说明里还列出了挪到 0.1.64 的事项，以及我们没有达到的两项发布前标准。[完整发布说明 →](https://github.com/mirzatghayrat/arslan/releases/tag/v0.1.63)

最近几版：
- **[0.1.62](https://github.com/mirzatghayrat/arslan/releases/tag/v0.1.62)**——长命令能跑完：命令按它自己的上限运行（默认 2 分钟，最多 10 分钟），只有确实可能发生了什么时才“需要你检查”，MCP 工具描述不会再让聊天失败，写文件也绝不会顺着链接跑出你的工作文件夹。
- **[0.1.61](https://github.com/mirzatghayrat/arslan/releases/tag/v0.1.61)**——各处同一张审批卡（聊天、收件箱、Island、iPhone），MCP 服务自行启动，被拒绝 `temperature` 设置之后 Claude 重新可用。

<div align="center">
  <img src="docs/assets/readme/devices.jpg" alt="Mac 上的 Arslan 正在后台整理发票；iPhone 上的 Arslan 显示一条待批准" width="100%">
</div>

<p align="center"><sub>Mac 画面：取自 0.1.52 发布片，界面按源码重建，场景为摆拍。iPhone 画面：真实录屏。 <a href="https://aralem.dev/arslan/#film">▶ 60 秒看完整个系统</a></sub></p>

## 为什么是 Arslan

| | |
|---|---|
| **一条回路，每个动作都在闸门后面** | 一条消息进入一条原生工具调用回路。模型只负责提议；每条 shell 命令运行前，由一个固定的策略函数——不是另一个模型——给出 **run**、**ask** 或 **forbid**。返回结果一律当作不可信数据包裹，网页里藏的指令只会被读，不会被执行。 |
| **你聊天，它接着干** | 长任务变成后台任务，这一轮对话随即结束。任务的结局只有 **done**、**partial**、**blocked**、**stopped** 四种——从不悄悄放弃。定时任务最短间隔 15 分钟（最多 10 个），Mac 睡着时错过的不会补跑。 |
| **状态就在刘海里** | **Arslan Island** 显示它在做什么、需要你时来问、做完了告诉你。还有菜单栏、按住说话，以及随时可按的 Stop。 |
| **Hands：先问，不擅自** | 通过 Arslan Hands 操作 Mac app、Arslan 自己的浏览器、你的快捷指令、AppleScript。从不在密码框里打字，也从不碰钥匙串访问、密码管理器、系统设置、macOS 安全提示、通知中心和它自己。 |
| **你的 Mac，装进口袋** | Arslan for iPhone（即将上架 App Store）通过**你自己的私有 iCloud** 与 Mac 通信，端到端加密。同一张批准卡同时出现在两端，谁先点算谁的；无人回应的卡会等 30 分钟，时间到了也不算拒绝（0.1.61 起；更早的版本在 300 秒后自动拒绝）。 |
| **本地优先，自带 key** | 记忆存在你 Mac 上的 SQLite 里；模型服务商只看到你发出的那几轮，用的是你的 key。**Arslan 不运营任何服务器。** 纠正它一次，它就记住这个做法——还能撤销。 |
| <img src="docs/assets/icons/shield-check.svg" width="16"> **凭据始终归你** | Arslan 从不获取或注入你的账号凭据。需要凭据的连接器（如 App Store Connect）仍保持禁用，直到隔离的凭据代理通过安全验收——见 [W11](docs/companion/W11-security-boundary.md)。你批准在沙箱外运行的命令，以你自己的权限执行。 |

## 一轮对话，从头到尾

<div align="center">
  <img src="docs/assets/readme/loop.jpg" alt="回路：消息、循环、策略、沙箱、结果——每一步都标出负责它的源码文件" width="100%">
</div>

| 步骤 | 发生什么 | 源码位置 |
|---|---|---|
| **消息** | 来自窗口、iPhone 或语音——同一个对话，同一条回路 | `server/orchestrator/arslan.py`, `server/services/phone_bridge.py` |
| **回路** | 原生工具调用；计划由宿主保管；回复被截断时接着写而不是猜；每次模型调用上限 75 秒 | `server/orchestrator/tool_loop.py` |
| **策略** | `run` · `ask` · `forbid`，命令文本的纯函数 | `server/services/terminal_policy.py`（命令读取与安全底线改编自 Hermes Agent，MIT） |
| **沙箱** | macOS seatbelt：命令只能写工作文件夹、临时目录和缓存；SSH 密钥、钥匙串和 Arslan 数据一律关闭；模型 key 永远不会交给命令；命令按它自己的上限运行，默认 2 分钟，最多 10 分钟 | `server/services/command_sandbox.py`, `terminal_exec.py` |
| **结果** | 包裹成不可信数据、检查后才给你；没真正做过的事被确定性守卫拦下 | `server/orchestrator/untrusted.py`, `promise_guard.py` |

## 闸门

<div align="center">
  <img src="docs/assets/readme/gate.jpg" alt="官网上的闸门：输入命令，看 Arslan 的真实判定——读取钥匙串密码为 forbid" width="100%">
</div>

| 判定 | 什么时候 | 例子（都是 `terminal_policy.assess()` 的真实输出） |
|---|---|---|
| **run** | 读取、列目录、转换、构建、抓网页 | `ls -la ~/Downloads` · `ffmpeg -i talk.mov talk.mp4` · `npm run build` · `curl -s https://example.com` |
| **ask** | 有破坏性，或以你的名义对外动作 | `rm -rf build/` · `git push --force` · `curl … \| sh` · `osascript …` · `brew install jq` · `mail -s …` · `scp … mac-mini:` |
| **forbid** | 永远不行，勾了“不再询问”也不行 | `security find-generic-password … -w` · `cat ~/.arslan/secret_key` · `rm -rf ~` · `sudo …` · `shutdown` |

“不再询问”按命令种类记住，可在 设置 › 高级 里查看；forbid 的规则永远记不住。闸门防的是失误和网页里夹带的指令——不是牢笼：你放行的命令会以你的权限运行。自 0.1.63 起，新命令默认先问，不论它在上表中属于哪一行。在[官网](https://aralem.dev/arslan/#gate)试试 64 条命令。

## Hands、后台任务与 iPhone

<div align="center">
  <img src="docs/assets/readme/hands.jpg" alt="Hands：通过 Arslan Hands 操作 Mac app、浏览器、快捷指令和 AppleScript；看得见、停得下；永远不碰的 app" width="100%">
</div>

<div align="center">
  <img src="docs/assets/readme/iphone.jpg" alt="Mac 与 iPhone：经由你的私有 iCloud 端到端加密（X25519、HKDF-SHA256、ChaCha20-Poly1305、Ed25519），先答者生效，Island 的表情" width="100%">
</div>

iPhone 链路没有 Arslan 服务器，也没有中转：消息走你私有 iCloud 数据库里的一个 CloudKit 区——X25519 密钥协商、HKDF-SHA256、ChaCha20-Poly1305、Ed25519 签名。送达的消息随即删除；没送达的残留超过 7 天后由 Arslan Mac 版删除——Mac 开着并联网时大约每天检查一次，离线期间的清理等它恢复后再做。

## 隐私

<div align="center">
  <img src="docs/assets/readme/privacy.jpg" alt="谁能看到什么：本机看到全部，模型服务商只看到你发的那几轮，iCloud 只有密文和路由，Arslan 服务器什么也看不到——因为根本不存在" width="100%">
</div>

## 安装

从源码运行（贡献者）：见 **[docs/QUICKSTART.md](docs/QUICKSTART.md)**。

图片与扫描版 PDF 的文字识别、完整的安全说明、环境变量和数据备份，请看[英文 README](README.md#install)（以英文版为准）。

## 现状——只说已经证实的

- **Pre-v1。** 目前只支持 Apple Silicon 上的 macOS 11+。沙箱基于 macOS seatbelt；在其他平台上，生成的 Python 会被拒绝，终端命令则在无沙箱状态下运行并如实标明。
- **自带模型 key。** Arslan 用你的账户跑，费用由你的服务商结算。原生工具调用已实现并对 OpenAI 兼容、Anthropic、Gemini 三条路径做了协议测试——这不等于每个模型或端点都经过实测。
- **Hands 还不能按屏幕位置点击或拖拽。**另一个桌面上的窗口要短暂过去才能操作（需开启借用前台）。应用跳到前台的约 50 毫秒内按下的键会进入那个应用；大窗口（比如笔记很多的备忘录）读一次要 10–20 秒。
- **Arslan for iPhone 即将上架 App Store**，Mac 端已随 0.1.53 发布。
- **花费有默认上限，但不是保证。** 每条回复和每个后台任务在模型花费 $2 时停止（设置 › 后台与主动），只计入价格已知的模型；仍建议在服务商的账单后台设个硬上限。
- **默认每条新命令都先问，定时任务不运行命令**（0.1.63）。
- v1 之前，API、数据结构和默认值都可能变化。

## 社区

- 发现 bug 或有想法？[提交 issue](https://github.com/mirzatghayrat/arslan/issues)。
- 想帮忙？先看 [CONTRIBUTING.md](CONTRIBUTING.md)。
- 项目官网在 [`docs/index.html`](docs/index.html)（GitHub Pages）。本 README 的图片都截自官网。

## 许可证

Apache-2.0。见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。第三方声明——包括 Hermes Agent（MIT）和 agent-desktop（Apache-2.0，从带有 Arslan 一处修改的 fork 构建，随 Arslan Hands 分发）——见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。图标：[Lucide](https://lucide.dev)（ISC）。

---

<div align="center">
<sub>如果 Arslan 打动了你，<a href="https://github.com/mirzatghayrat/arslan/stargazers">点一颗 <img src="docs/assets/icons/star.svg" width="12" height="12"> 能帮更多人找到它</a>。</sub>
</div>

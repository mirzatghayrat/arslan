# P3 施工 spec:触达 / 舰队(那个惊艳用户的场景)

日期:2026-08-21 · 状态:**待用户批** · 总纲:`2026-08-20-agent-reach-and-proactivity.md` 支柱 C
前序:P1(v0.1.25)、P2(v0.1.26)已出货。用户裁决:C4「已登记 node 免执行闸」**不开**。

---

## 0. 重核 OpenClaw 现行安全默认(用户点名的挂账,今天做的)

总纲 §6 挂了「C 阶开工前重核 OpenClaw 现行安全默认(它可能已修)」。**重核了:没修,而且形势比立项时更糟。**

| 项 | 2026-08-21 实况 |
|---|---|
| 条件触发脚本 / script payload | **仍然默认无人值守跑,带 owner 全量工具策略含 `exec`**(官方 docs 原话未变) |
| `cron.triggers.enabled` | **默认 true** — 唯一的硬停开关要手动关 |
| 无人值守的审批流 | **没有**。沙箱是可选的 per-agent 配置,不是自动的 |
| Gateway 认证 | **默认关闭**;绑 0.0.0.0 时任何人可访问 |
| 新增实证 | 2026-01 一个真实 CVE:Control UI 一个未校验 URL 参数 → **1-click RCE**;v2026.2.21 补 SHA-256 迁移漏洞(GHSA-76m6-pj3w-v7mf)+ 两个 Node CVE |

⇒ **总纲 §3.1「抄形态、反默认」不但仍然成立,而且现在有了 CVE 级的实证支撑。** 本 spec 的每个闸都不放宽。

## 0b. 我们自己的现状(亲核 main `b3c7a8eb`)

| 面 | 现状 | 对 P3 的意义 |
|---|---|---|
| `net_pin._is_non_public` | `not is_global` 的**允许清单**,封 loopback/私网/CGNAT/link-local | 🔴 **与 LAN 发现正面冲突**,见 §2.1 |
| `command_policy` | 二进制白名单 + 硬拒扫描 + LOW/MED/HIGH 分类器 | 远程执行**复用它**,不另造 |
| `command_sandbox` | seatbelt 包子进程;**不隔离文件系统** | ssh 子进程可包,但它保护的是本机不是远端 |
| `crypto` | 盐进 DB、`encrypt/decrypt`、三态诊断 | 私钥存这里,不另造 |
| ssh / mDNS | **零痕迹**(grep 全仓无 paramiko/asyncssh/zeroconf) | 真·整维缺失,不是重造 |
| 确认帧三件套 | run_command / workspace_write / schedule 各一张卡 | 远程闸**照这个形状**加第四张 |

---

## 1. 分三个独立 PR,闸一步比一步硬

### P3a — LAN 发现(只读,提议面)
**能力**:扫同网段 → 列出「我看到这些设备」候选卡(IP、开放端口、OUI 厂商名如 `80:a9:97`→Apple、mDNS 主机名)。

🔴 **与 net_pin 的冲突,以及唯一可接受的解法**:`net_pin` 故意封私网(SSRF 硬化,[[arslan-allowlist-not-blacklist]]),而 LAN 发现**必须**触达 `192.168.x.x`。解法**不是**给 net_pin 开口子——那会同时给 `web_extract` 开门,把一个 SSRF 防线换成一个配置项。而是:
- 新模块 `server/services/lan_scan.py`,**独立代码路径**,不 import net_pin、不复用 web fetch 的出口。
- 设置 `lan_discovery_enabled`(默认 **OFF**)。关着时工具**不注册**(P1 的 workspace 定式)。
- 扫描面**硬编码收窄**:只扫**本机所在网段**(从本机地址推),只探**固定端口白名单**(22/5900/3389/80/443),超时 + 并发上限,**永不**扫任意用户输入的网段。
- 输出**纯只读**,不落库、不自动连。

### P3b — SSH 外联 + 远程执行(执行面,per-host 人闸)
- 工具 `ssh_probe(host)`:只做连通性 + host key 指纹,**不执行任何命令**。
- 工具 `ssh_run(host, command, argv)`:**每条命令一张确认卡**,和本地 T2 同尺——远程 exec 是本地 exec 的超集风险,闸只能更严。
- 命令走**现有** `command_policy.validate` + `classify`;远程一律按 **HIGH** 处理(即便 `ask_risky` 也确认)——理由:白名单里的 `git` 在远端可能是另一个 git。
- 🔒 **凭据**:
  - 首选**公钥流**:本地生成密钥对,**私钥进 crypto 加密存储**,公钥给用户去粘(OpenClaw 截图里那套)。
  - 密码流:**只在建立连接的那一跳用一次,绝不落库**,用完即弃。
  - 🔴 **首次连接 = 一次显式人类同意**,卡上显示 **host key 指纹**(防中间人)。
- 传输:sidecar `ssh` 子进程(复用 command_sandbox 的 seatbelt 包裹),**不引入 paramiko/asyncssh**(少一个依赖面,且系统 ssh 的 known_hosts 语义是用户熟悉的)。

### P3c — 节点登记(最危,显式 + 可撤销)
- 一次**显式动作**把主机存成 node(不是 P3b 的副产物)。
- 🔴 **登记 ≠ 免执行闸**(用户裁决):已登记 node 的 `ssh_run` **仍然逐条确认**。登记只免掉 C2 的重认证。
- 每个 node **一键撤销**(删私钥 + 删登记 + 从 known_hosts 摘除)。
- 每个远端动作**留审计**(谁、哪台机、什么命令、退出码),trace 台可查。

---

## 2. 安全立场(逐条,不放宽)

1. **LAN 发现独立于 net_pin**,绝不给 SSRF 防线开配置口子。
2. **远程执行一律 HIGH**,`ask_risky` 不豁免。
3. **凭据不落明文**;私钥进 crypto;密码只用一跳。
4. **登记不免执行闸**(用户裁决,写死)。
5. **无人值守 ∩ 远程 = 结构性禁止**:定时轮没有 confirm 回调,而 `ssh_run` 要卡 ⇒ **定时任务无法 ssh**。这是 P1/P2 那层自动带来的,不是新规则——也正是 OpenClaw 那两篇 arXiv + 那个 1-click RCE 的核心攻击面。
6. **本会话的我不替用户输密码**:这是产品让用户的 agent 做的事,不是我在这条会话里执行的动作。

## 3. 验收判据(mutation 必红)

1. `lan_discovery_enabled` 关 ⇒ 扫描工具**不在工具表里**。
2. 扫描只覆盖本机网段与端口白名单;喂进任意网段/端口被拒。
3. `lan_scan` **不 import** net_pin(源码级断言 + 行为级:它能触达 192.168.x.x 而 `web_extract` 仍然不能)。
4. `ssh_run` 无 confirm 回调 ⇒ 拒绝(和三个既有闸同形)。
5. 远程命令即便是 `git status`(本地判 LOW)也**仍然出卡**。
6. 定时轮里调 `ssh_run` ⇒ 结构性拒绝(§2.5 的实证)。
7. 私钥落库后**库里读不到明文**(断言性质,不断言调了 encrypt)。
8. 撤销 node ⇒ 私钥、登记、known_hosts 三处都没了。

## 4. 裁决点(开工前请拍)

1. **P3a 单独先发**还是三阶攒一起发?(我倾向:**P3a 先发**——只读、风险最低、且它单独就有价值:「我网里有什么」。P3b/c 攒一起。)
2. **密码流要不要做**?(我倾向:**只做公钥流**。密码即便只用一跳,也要经过 Arslan 的进程内存;公钥流用户体验只多一步粘贴,但把整类风险移出产品。你在 OpenClaw 那次就选了公钥。)
3. **远程命令白名单**:沿用本地那套(git/gh/ffmpeg/pandoc + 15 只读),还是远程另开一份更窄的?(我倾向:**沿用**,理由是一套心智模型;但远程一律 HIGH 补偿。)
4. **P3 完成后打不打「v0.2.0 长出手脚」的旗号**(总纲 §4b 裁决④说留到 P3 完成时)。

## 5. 尚无证据、未声称已验

- 本 spec 零代码;§0b 现状为 2026-08-21 对 main `b3c7a8eb` 亲核。
- **跨机端到端需要你的第二台真机**——这是 P3 唯一无法靠测试代替的验收项。
- 系统 `ssh` 在打包 .app 的最小 PATH 下能否被找到:**未验**。P1 的 `spawn_env.merged_path()` 大概率已经解决(它就是为 npx 那个坑做的),但开工时要拿测试证,不能假设——**打包版专属缺陷家族已经咬过我们三次**。

关联:[[arslan-agent-reach-p1]]、[[arslan-allowlist-not-blacklist]]、[[arslan-propose-vs-execute-bias]]、[[arslan-shell-network-proxy]]、[[arslan-packaged-only-defect-family]]、[[arslan-crypto-salt-round]]。

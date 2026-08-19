# Arslan 触达 + 本地执行 + 主动性(OpenClaw 水平,fail-closed 版)

日期:2026-08-20 · 状态:**待用户批** · 触发:用户看到 OpenClaw 扫同网段定位新 Mac(192.168.1.8)并 SSH 过去装好 OpenClaw,要 Arslan 达到同一水平。

## 0. 校准:用户被惊艳的到底是什么

用户原话——「我说我有个新电脑要装 OpenClaw,它通过同一 Wi-Fi 就能准确定位找到,并真的在另一台电脑上装上了」。拆开是**四步链**:
1. **局域网发现**:扫同网段 → 认出 `192.168.1.8` 是 Apple 设备(MAC 前缀 `80:a9:97`)。
2. **SSH 外联**:拿用户给的用户名/密码(或用户粘贴公钥)登进去。
3. **远程执行**:装 Node → 跑 `install.sh` → 初始化 → 验证。
4. **节点登记**:把新机注册成网关的 node,「以后想操作它随时能操作,不用再输密码」。

这**不是**「本地执行」一件事,是 Arslan 现在完全没有的一整个维度:**触达另一台机器**。同时它也是 OpenClaw 两篇 arXiv 安全分析(agentic botnet:LAN 传播 + 无人值守 exec + 节点持久化)的攻击面全集。**所以本 spec 的立场:抄能力形态,反其默认值。**

## 1. 现状亲核(不是缺口就别重造)

| 能力 | Arslan 现状(file 级) | 判定 |
|---|---|---|
| 浏览器操控 | Playwright MCP 已闭环(v0.1.24) | ✅ 有 |
| SKILL.md 生态 | `skill_import` 逐字导入 + clawhub 同族格式 | ✅ 有 |
| MCP + OAuth | 全套 + 服务器级装备(v0.1.24) | ✅ 有 |
| Python 沙箱 | `code_sandbox.py` | ✅ 有 |
| **cron 调度核心** | `scheduler.py`:5 字段 cron 解析 + 监督执行环(S3-M4)+ `scheduled_tasks.py` | ✅ **已有,别重造** |
| shell 执行 | `command_policy.py` **只白名单 git/gh/ffmpeg/pandoc** + 逐条人闸 | 🟡 有但极窄 |
| 文件读写 | 分身知识库 `ingest` 有;**通用 workspace file 工具无** | 🔴 缺 |
| 主动性"上半身" | heartbeat 清单轮 / 条件触发 / Arslan 自排程 | 🔴 缺 |
| **触达另一台机** | LAN 发现 / SSH 外联 / 远程 exec / 节点登记 | 🔴 **整维缺失** |

**houserule 复用**:`command_policy`(硬拒扫描)、`command_sandbox`、`net_pin`(SSRF 允许清单——注意 LAN 发现要**故意**触达私网,与 net_pin 的封私网直接冲突,见 §4)、`scheduler.py`(调度核心)、`propose-vs-execute-bias`(提议宁开执行宁关)、`replay-sealing-semantics`。

## 2. 三支柱 + 分阶(每阶独立 spec 审 + PR + mutation + 逐 id 基线)

### 支柱 A — 本地执行面(分级 file + shell)
**目标**:把「只有四命令」升成 OpenClaw 那种 `read/write/edit/apply_patch` + 更宽 shell,但**分级**:
- **T0 只读**(read/list/stat/grep)——提议面,免确认。
- **T1 workspace 写**(write/edit/apply_patch,限定在一个用户指定的工作目录内,路径逃逸硬拒)——首次授权后该 session 内免逐条确认。
- **T2 任意 shell / 目录外写**——**逐条人闸,fail-closed**(现有 `run_command` 语义,扩白名单但保留确认)。
- 默认全关,用户在设置里逐级开(镜像现有 shell_enabled 开关族)。

### 支柱 B — 主动性引擎(骑现有 S3-M4 调度核心)
**目标**:让 Arslan **自己**能排任务 + 周期性醒来干活。抄 OpenClaw 的任务模型,配我们的闸:
- **自排程工具**:给 Arslan 一个 `schedule_task` 工具(写进 `scheduled_tasks`,复用 `scheduler.py`)——它能把「明早汇总 CI」排进去。
- **heartbeat 清单轮**:一个用户可编辑的清单(HEARTBEAT.md 等价),周期性主会话轮读它决定要不要动手;**默认 OFF**,间隔用户设。
- **条件触发**:on-exit / stream / 阈值——但 🔴 **绝不抄 OpenClaw「条件脚本默认带 owner 全量工具含 exec 无人值守跑」**(正是 arXiv botnet 面)。我们的条件触发**只能提议,不能自执行 T2**;要执行走人闸。
- **送达**:结果 announce 到聊天线程(复用 turn_journal/ws 帧)。
- **连败自停**:抄 OpenClaw 的「连败 N 次自动禁用」(便宜的失控保险)。

### 支柱 C — 触达/舰队(那个惊艳用户的东西)
**这是新维度,也是最高危面。分四子步,闸一步比一步硬:**

- **C1 LAN 发现(只读,提议面)**:mDNS + 有界端口探测(22/5900/…)+ OUI 厂商识别(`80:a9:97`→Apple)。产出「我在同网段看到这些设备」的候选卡。
  - 🔴 **与 net_pin 正面冲突**:net_pin 的允许清单**故意封私网/CGNAT/Tailscale**(SSRF 硬化)。LAN 发现要触达 `192.168.x.x`——**必须是独立的、显式开启的能力,不是给 net_pin 开口子**。开一个 `lan_discovery_enabled` 设置(默认 OFF),扫描器走独立代码路径,**永不复用 web fetch 的出口**。
- **C2 SSH 外联(执行面,per-host 人闸)**:对**用户点名的**主机、**用户提供的**凭据(或用户粘贴公钥),sidecar shell 出 `ssh`。
  - 🔒 **凭据红线**:Arslan/sidecar **不存明文密码**;密码只在建立连接的一跳用一次(与截图里 OpenClaw 的做法一致),或走公钥。密钥对生成在本地,私钥进现有加密存储(crypto 家族),公钥给用户粘。**我(Claude 本会话)不替用户输密码**——这是产品让用户的 agent 做,不是我做。
  - 每台新主机**首次连接 = 一次显式人类同意**(host key 指纹确认,像截图那样)。
- **C3 远程执行(fail-closed)**:登进去后跑命令——**默认逐条人闸**,和本地 T2 同尺。远程 exec 是本地 exec 的超集风险,闸只能更严不能更松。
- **C4 节点登记(最危,显式登记 + 可撤销)**:把主机存成「已登记 node」,未来免密操作。
  - 🔴 **这正是 botnet 持久化面**。规矩:登记是**一次显式动作**(不是 C2 的副产物);登记 ≠「随时无需确认操作」——**远程 T2 exec 永远要闸,哪怕已登记**;每个 node 可一键撤销(删私钥 + 删登记);登记面 fail-closed。
  - 对照 OpenClaw:它的 node「以后随时操作不用输密码」把 C4 和 C3 的闸一起免了——我们**只免 C2 的重认证,不免 C3 的执行闸**。

## 3. 安全立场(写死,评审必看)

1. **抄形态、反默认**:OpenClaw 每个「默认无人值守带 exec」的地方,我们默认关 + 人闸。两篇 arXiv(botnet via LAN 传播 + 无人 exec + 节点持久化)就是反面教材。
2. **提议面宁开、执行面宁关**([[arslan-propose-vs-execute-bias]]):C1 发现/B 提议都可开放;C2/C3/C4/A-T2 全 fail-closed。
3. **LAN 发现独立于 net_pin**,绝不给 SSRF 硬化开口子([[arslan-allowlist-not-blacklist]])。
4. **凭据只读一跳/走公钥,私钥进 crypto 存储**,Arslan 不持明文([[arslan-no-real-personal-data-in-code]] 精神延伸)。
5. **登记 ≠ 免执行闸**:已登记 node 的远程 T2 仍逐条确认。
6. **每个远端动作留审计**(谁、哪台机、什么命令、结果),trace 台可查。

## 4. 分阶交付建议

| 阶 | 内容 | 量级 | 依赖 |
|---|---|---|---|
| **P1** | 支柱 A(分级 file/shell 工具 + 设置开关族) | 中 | 无(地基,B/C 都要用) |
| **P2** | 支柱 B(自排程工具 + heartbeat 清单 + 条件触发提议 + 连败自停) | 中-大 | 骑 S3-M4;用 A 的执行面 |
| **P3a** | C1 LAN 发现(只读候选卡) | 小-中 | 独立 |
| **P3b** | C2+C3 SSH 外联 + 远程 exec(per-host 闸) | 大 | A、C1 |
| **P3c** | C4 节点登记(显式 + 可撤销) | 中 | C2/C3 |

**先做 P1(地基),它本身就让 Arslan 从「四命令」变成能真读写文件——即时可见的能力跃迁**;P2 给它"主动";P3 给它"触达"。C 那条(最惊艳也最危)排最后,证据链最厚时再上。

## 5. 待用户裁决点

1. **分阶顺序**:按上表 P1→P2→P3 顺序做,还是你要先啃 P3(触达)那条惊艳的?(我的建议:P1 先,地基;但你说了算。)
2. **A 的默认粒度**:T1 workspace 写「首次授权后 session 内免确认」是否够松/够紧?
3. **C4 节点登记**:「已登记 node 的远程 T2 仍逐条确认」——你要不要一个「信任此 node 免确认」的高级开关(我强烈不建议,但它是你的机器你的裁决)。
4. **发不发**:这几阶是随做随发小版本,还是攒一个大版本(如 v0.2.0「Arslan 长出手脚」)。

## 6. 尚无证据、未声称已验

- 本 spec 零代码;所有 file:line 现状是 2026-08-20 亲核,开工前每阶再核。
- OpenClaw 的架构/默认值取自其官方 docs + 两篇 arXiv;开工前对 C 阶再核其现行安全默认(它可能已修)。
- 跨机端到端(真的在第二台 Mac 上装东西)是 P3 的验收项,需要用户的第二台真机——届时配方照 OpenClaw 截图那套(用户开 Remote Login → 给 Arslan IP+凭据 → Arslan 接管)。

关联:[[agent-reach-reference]]、[[arslan-propose-vs-execute-bias]]、[[arslan-allowlist-not-blacklist]]、[[arslan-shell-network-proxy]]、[[arslan-gap-assessment-2026-08]]、[[arslan-external-research-borrow-map]]、[[arslan-extension-contract-spec]]。

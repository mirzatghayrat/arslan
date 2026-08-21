# P3b 施工 spec:SSH 外联 + 远程执行

日期:2026-08-21 · 状态:**待用户批** · 总纲:`2026-08-20-agent-reach-and-proactivity.md` 支柱 C · 上级:`2026-08-21-p3-reach-and-fleet.md` §1 P3b
前序:P1(v0.1.25)、P2(v0.1.26)、P3a LAN 发现(#54 `3a59255a`)已出货。

---

## 0. 开工前亲核(用户常设规矩:别在上级 spec 的 file:line 上直接动手)

对 main `48a09a62` 重核。**上级 spec 的三条说法今天被推翻或必须限定**,这是本节存在的理由。

### 0.1 🔴 `ssh` 走不了 `run_command`——不是"扩白名单"能解决的

`command_policy.py:22` 的模块注释原话:加 fetcher(`curl`/`wget`/**`ssh`**)会让整个分级**变装饰品**,因为「跑这条 LOW 命令」等于「跑任意代码」。`ALLOWED_BINARIES`(`command_policy.py:26`)也确实不含 `ssh`,`validate()` 会直接拒。

⇒ **不动 `ALLOWED_BINARIES`**。`ssh_run` 走**独立执行器**(`server/services/ssh_exec.py`),与 P3a `lan_scan` 不碰 `net_pin` 是同一个形状:**新能力开新路,不给既有防线开口子**([[arslan-allowlist-not-blacklist]])。

### 0.2 🔴 seatbelt **锁不住"只准连这一台"**(今天实测,不是推演)

`code_sandbox.py:100` 的 `net_profile` docstring 已记「host 必须是 `*` 或 `localhost`」。我今天把它推到 P3b 需要的形状上实测:

| 探针 | 结果 |
|---|---|
| `(allow network-outbound (remote tcp "192.168.1.8:22"))` | ❌ `sandbox-exec: host must be * or localhost in network address` |
| `(allow network-outbound (remote tcp "*:22"))` | ✅ 接受 |

⇒ **"沙箱保证只连你批准的那台机"这句话不能说**——内核层做不到。说了就是 P1 §0 那条教训的复发(造一个**看起来有牢笼、实际没有**的假安全面,[[arslan-assert-behaviour-not-source]])。**目标主机的边界只能由纯函数参数守卫保证**,和 P1 的路径守卫同性质。

### 0.3 ✅ 但端口能锁,而且我实测它真的在拦

同一 profile 下起 `/usr/bin/python3` 连本机:

| 目标 | 无沙箱基线 | `deny network*` + `allow tcp "*:22"` |
|---|---|---|
| tcp/22 | ConnectionRefused(61) | ConnectionRefused(61) ← 放行到正常路径 |
| tcp/80 | ConnectionRefused(61) | **PermissionError(1)** ← 被拦 |
| udp/53 | 发出 | **PermissionError(1)** ← 被拦 |

两个后果,都要写进设计:
1. **UDP 全封 ⇒ 子进程没有 DNS**。所以 `host` 参数**只接受 IP 字面量**(正好是 P3a 的产出形状)。这不是限制是收益:少一个名字解析面,也少一条 DNS 外泄信道。
2. **子进程没有 443/任意端口出口**。它拿到远端数据后**无法自己外传**——这是纵深防御里真正能兑现的那一层,可以说。

### 0.4 🔴 上级 spec 一句话是错的:known_hosts 不会是用户的那份

`command_sandbox.py:60` 把 `HOME`/`TMPDIR` 都刷成临时目录,**故意**让沙箱里的 git 读不到 `~/.ssh` 和 `~/.gitconfig`。ssh 同样读不到 ⇒ 上级 spec §1「系统 ssh 的 known_hosts 语义是用户熟悉的」**不成立**。

**改为**:Arslan 维护**自己的** known_hosts(在自己的数据目录内)。这比复用用户那份更好——它可枚举、可撤销、撤销时能真的删干净(P3c 的判据 8 才成立);但**不许**再写"沿用系统语义"这种话。

### 0.5 ✅ 打包版 PATH 陷阱在这里不适用(要拿断言钉住)

`/usr/bin/ssh`(OpenSSH_10.2p1)、`/usr/bin/ssh-keyscan`、`/usr/bin/ssh-keygen` 都在 base system 的**绝对路径**上,不像 `npx` 依赖用户 shell 的 PATH。⇒ 全部**按绝对路径调用**,并写一条断言钉住"不走 PATH 查找"。([[arslan-packaged-only-defect-family]] 咬过三次,这次用结构避开而不是靠运气。)

### 0.6 现有确认闸的形状(决定第 4 张卡怎么加)

三个回调 `confirm_command` / `confirm_workspace_write` / `confirm_schedule` 在 `tool_loop.py:480-563` 逐个判、"无回调即拒";但它们被**逐参数**穿过 `arslan.py` 约 15 处、`tool_loop.py` 约 6 处。**再加第 4 个参数 = 三十来处纯机械改动,收益只有一个更好看的卡。**

**建议(裁决点 ①)**:不加第四个参数,改为给**已经处处穿好**的 `confirm_command` 加一个可选 kwarg:

```
confirm_command(command, argv, *, remote_host: str | None = None) -> bool
```

`remote_host` 非空 ⇒ 前端渲染**远程卡**(醒目标出"这条命令在另一台机器上执行"+ 指纹)。测试替身按 P1b 定式在**桩上**加 `**_kw`,不动产品签名语义。

---

## 1. 三个裁决点(上级 spec §4 的 ②③④,我的建议在此,你可以推翻)

### ② 密码流做不做 → **建议:只做公钥流**
密码即便"只用一跳"也要经过 sidecar 的进程内存,而且要经过 ssh 的 tty 交互(得 `expect`/`sshpass` 或伪终端——又是一个依赖面 + 一段没人愿意维护的代码)。公钥流只多"粘一次公钥"这一步,把整类风险移出产品。**你在 OpenClaw 那次选的也是公钥。**

### ③ 远程命令白名单 → **建议:沿用本地那套 + 远程一律 HIGH,但必须补一条上级 spec 没提的防线**
🔴 **本地 policy 的安全论证不能整段搬到远程**:本地 argv 是直接 `create_subprocess_exec`(`command_sandbox.py:65`),**没有 shell 参与**,所以 `_SHELL_META` 只需要拦"万一被 shell 重新解析"的那几个字符。而 `ssh host cmd args` 是把 argv **拼成一个字符串交给远端登录 shell 解析的**——`_SHELL_META`(`command_policy.py:30`)**不含** `* ? [ ] { } ~ ! \ ' " ` 和空白。

⇒ 沿用本地白名单**成立的前提**是:每个 argv 元素在发出前 `shlex.quote`,并且这条要有**专门的 mutation**(去掉 quote 后 `ls *` 在远端展开 ⇒ 测试必须变红)。没有这条,"沿用"就是把一个在无 shell 前提下正确的检查搬到有 shell 的地方——[[arslan-probe-must-match-consumer]] 那条的原样复发。

### ④ 「v0.2.0 长出手脚」旗号 → **建议:P3c 合完也先别打,等真机端到端跑过**
P3 唯一无法用测试代替的验收项就是**在你第二台 Mac 上真的装成一次**(上级 spec §5)。在那之前打旗号,等于用营销声明替代唯一的实证——正是 [[ci-green-claims-must-cite-actions-run]] / [[arslan-delivery-report-no-evidence-section]] 那一族规矩要防的事。**跑通了当天就打,不用等下一个版本。**

---

## 2. 交付物

### 2.1 设置 `ssh_enabled`(默认 OFF)
镜像 `lan_discovery_enabled` 定式(`settings_service.py:31,225`、`schemas.py:68,118`):关着时 **ssh 工具不注册**(不是注册后报错)——`arslan.py:1831` 那个分支照抄。

### 2.2 `server/services/ssh_keys.py`(密钥)
- `ensure_keypair()`:`/usr/bin/ssh-keygen -t ed25519 -N ""` 生成在临时目录 → **私钥文本经 `server.crypto.encrypt` 落库**,公钥明文落库,临时文件即刻删除。
- `public_key()`:给 UI 展示/复制的公钥串(用户去目标机 `authorized_keys` 粘)。
- `materialize()`:上下文管理器,`mkdtemp(0700)` + 私钥写 `0600` 文件,退出时删除。
  🔴 **诚实边界(必须写进代码注释和交付报告)**:私钥在这段窗口里**是明文在本地磁盘上**的。ssh 的 `-i` 只接受路径;`/dev/fd/N` 能不能绕过**未验**,不作为设计依据。我们能保证的是:目录 0700、文件 0600、窗口=一条命令的时长、进程退出即删。**不许写"私钥从不落盘"。**

### 2.3 `server/services/ssh_exec.py`(传输,独立代码路)
- `HOST_RE`:只接受 IPv4 字面量(§0.3 的 DNS 事实)。
- `probe(ip)`:`/usr/bin/ssh-keyscan` 取 host key → `/usr/bin/ssh-keygen -lf` 出指纹。**零凭据、零远程执行**。
- `run(ip, command, argv, *, key_path, known_hosts)`:绝对路径调 `/usr/bin/ssh`,`-o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=<我们自己的> -o PasswordAuthentication=no`,argv 逐个 `shlex.quote`。
- seatbelt profile:`ssh_profile()` = `deny network*` + `allow network-outbound (remote tcp "*:22")`(§0.2/0.3 实测形状)。

### 2.4 工具两件
| 工具 | 闸 | 语义 |
|---|---|---|
| `ssh_probe(host)` | **免确认**(提议面) | 连通性 + host key 指纹。不执行任何命令、不用任何凭据。 |
| `ssh_run(host, command, argv)` | **每条一张卡** | `command_policy.validate` + `classify`,但**远程一律按 HIGH**:`ask_risky` 不豁免。 |

### 2.5 前端
- 远程确认卡:主机 IP + **指纹** + 将要执行的命令原文 + 一句"这条命令在另一台机器上执行"。六语。
- 公钥展示/复制 + 一句话说明该往哪儿粘。

---

## 3. 安全立场(逐条)

1. **不谎称沙箱锁住了主机**(§0.2)。能说的只有:端口锁在 22、UDP/DNS 全封、子进程无外传信道。
2. **主机边界=纯函数守卫**,和 P1 的路径守卫同性质、同证明责任。
3. **远程一律 HIGH**,`ask_risky` 不豁免;`git status` 在远端也出卡。
4. **无人值守 ∩ 远程 = 结构性禁止**:定时轮不传 confirm 回调 ⇒ `ssh_run` 必拒。这是 P1/P2 那层白送的,不是新规则。
5. **私钥落库加密、明文窗口如实披露**(§2.2)。
6. **本会话的我不替用户输任何密码**——这是产品让用户的 agent 做的事。

## 4. 验收判据(每条 mutation 必红)

1. `ssh_enabled` 关 ⇒ `ssh_probe`/`ssh_run` **不在工具表里**。
2. `validate("ssh", …)` **仍然拒**(回归钉:我们没有偷偷放宽本地白名单)。
3. 主机参数:非 IPv4 字面量(域名、`1.2.3.4 extra`、`::1`)被拒。
4. **`shlex.quote` 专项**:argv 含 `*`、空格、`'` 时,发给 ssh 的字符串里它们是被引起来的;去掉 quote ⇒ 测试红。
5. `ssh_run` 无 confirm 回调 ⇒ 拒(与三个既有闸同形)。
6. 远程 `git status`(本地判 LOW)在 `ask_risky` 下**仍然出卡**。
7. 定时轮里调 `ssh_run` ⇒ 结构性拒绝(拿 P2 的 `run_arslan_turn` 实证,不是断言源码)。
8. 私钥落库后**库里读不到明文**(断言性质,不断言"调了 encrypt")。
9. `ssh`/`ssh-keyscan`/`ssh-keygen` **按绝对路径调用**(§0.5)。
10. seatbelt profile 里出现的是 `"*:22"` 而**不是**任何被 sandbox-exec 拒绝的 host 形式(§0.2)。

## 5. 不做面(v1 明说)

- **密码流**(裁决 ② 若你推翻则另开)。
- 非 22 端口、IPv6、跳板机/ProxyJump、SFTP/文件传输。
- 远程 sudo、远程解释器、远程写文件(远程只跑白名单里那套读多写少的命令)。
- **节点登记 = P3c**,本轮**不做**:本轮每次连接都要指纹确认,不存"已知主机"。
- 上级 spec 里那句 known_hosts 的说法已在 §0.4 更正,原文不再引用。

## 6. 尚无证据、未声称已验

- 本 spec 零代码。§0.2/0.3 的 seatbelt 结论是**今天在本机实测的**(附表即测量结果);§0.1/0.4/0.5/0.6 是对 main `48a09a62` 亲核。
- **真的 ssh 进一台真机、在那台机上跑出一条命令——未做**。这是 P3 唯一无法用测试代替的验收项,需要你的第二台 Mac 开 Remote Login。
- `ed25519` 密钥在**打包 .app** 里生成、加密落库、再取出使用的整条路,只在 dev 树验证过是不够的;发版前要走 `fresh_install_check` 那条路再看一眼。
- `/dev/fd/N` 能否免掉私钥落盘窗口:**未验**,不作为设计依据(§2.2)。

关联:[[arslan-agent-reach-p1]]、[[arslan-allowlist-not-blacklist]]、[[arslan-assert-behaviour-not-source]]、[[arslan-probe-must-match-consumer]]、[[arslan-packaged-only-defect-family]]、[[arslan-crypto-salt-round]]、[[arslan-propose-vs-execute-bias]]。

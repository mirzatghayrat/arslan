# P1 施工 spec:本地执行面(分级 file + shell)

日期:2026-08-20 · 状态:**待用户批** · 总纲:`2026-08-20-agent-reach-and-proactivity.md` 支柱 A
用户裁决(2026-08-20):P1 先做;T1 = 首次授权 + session 内免确认;随做随发小版本。

---

## 0. 开工前亲核结论(总纲的 file:line 已作废,以本节为准)

用户要求「别在总纲的 file:line 上直接动手」。全部重核,**现状比总纲写的丰富得多**:

| 已有(不要重造) | 位置 | 事实 |
|---|---|---|
| **风险三级分类器** | `command_policy.py:classify()` | LOW/MEDIUM/HIGH,借 OpenHands 分级但**纯模式无 LLM**;未知形状 fail-safe 为 HIGH;`_is_probe` 防「verbose 标志伪装成探针」 |
| 双层命令防御 | `command_policy.py:validate()` | 二进制白名单 `{git,gh,ffmpeg,pandoc}` + 硬拒扫描(shell 元字符/sudo/rm -rf/绝对路径解释器) |
| 网络面守卫 | 同上 | `is_network_command` / `is_host_allowed`(GitHub + 本仓 remote)/ `push_targets_current_branch` |
| **确认策略对** | `settings_service.py:223,237` | `orchestrator_shell_enabled`(bool)+ `shell_confirm_policy`(`ask_all`\|`ask_risky`);ask_risky = LOW 自动、其余出确认卡 |
| seatbelt 沙箱 | `code_sandbox.py:120` `_seatbelt_wrapper` | macOS `sandbox-exec`;非 darwin → null backend **fail-closed** |
| **内核级写限原语** | `code_sandbox.py:109` `readonly_profile()` | `(deny file-write* (subpath …))`;`file-write*` 覆盖 write/unlink/**chmod** ⇒ 同 uid 脚本无法 chmod 绕过 |

### 🔴 两条决定设计的硬事实

1. **seatbelt 不隔离文件系统**(`command_sandbox.py` 模块注释原话:「denies NETWORK but not filesystem — a command may read/write any path the server user can… **Do not treat the tmpdir cwd as a filesystem jail**」)。
2. **文件工具不经过 seatbelt**。seatbelt 只包裹**子进程**;file 工具在 sidecar 进程内用 Python 直接 `open()` 读写,**内核层根本不在链路上**。
   ⇒ **T0/T1 的边界必须由纯函数路径守卫保证,不能宣称「有沙箱保护」**。这是本 spec 最重要的一条,写错了会造出一个「看起来有牢笼、实际没有」的假安全面(正是 [[arslan-assert-behaviour-not-source]] 那类)。

---

## 1. 交付物

### 1.1 workspace 概念(新)
- 设置项 `workspace_dir`(默认**空 = 未设 = 文件工具全关**)。用户在设置里选一个目录。
- 存储:走现有 settings 表 + `_KNOWN_KEYS`(`settings_service.py:22`);**非 secret**。
- 解析:读取时 `Path(raw).expanduser().resolve()`;**空/不存在/不是目录 → 视为未设**,文件工具不注册。

### 1.2 路径守卫(纯函数,新模块 `server/services/workspace_paths.py`)
唯一判据函数,**所有** file 工具入口必经:

```
def resolve_in_workspace(user_path: str, ws_root: Path) -> Path   # 或 raise PathEscape
```
规则(每条都要 mutation 钉死):
1. **realpath 后判前缀**——先 `.resolve()`(跟随 symlink)再比,借 `readonly_profile` docstring 的教训(seatbelt 按 realpath 匹配,我们同尺)。
2. 前缀比较用 **`Path.is_relative_to`**,不用字符串 `startswith`(`/ws-evil` 不得匹配 `/ws`)。
3. 拒绝:workspace 外、`..` 逃逸、绝对路径逃逸、**指向 workspace 外的 symlink**(realpath 后自然拒)。
4. **写路径的父目录也要在 workspace 内**(写新文件时目标不存在,resolve 会落到不存在的路径——按父目录判)。
5. workspace 未设 → 直接 raise(工具本就不该注册,双保险)。

### 1.3 工具族(新)

| 工具 | 层级 | 语义 | 闸 |
|---|---|---|---|
| `read_file(path, max_bytes)` | **T0** | 读 workspace 内文本文件,尾截断 | 免确认(提议面) |
| `list_dir(path)` | **T0** | 列目录(名/大小/类型),不递归全盘 | 免确认 |
| `search_files(query, glob?)` | **T0** | workspace 内文本搜索,结果有界 | 免确认 |
| `write_file(path, content)` | **T1** | 写/覆盖 workspace 内文件 | **首次授权 + session 内免确认**(用户裁决 2) |
| `edit_file(path, old, new)` | **T1** | 精确串替换(要求唯一命中,否则拒) | 同上 |
| `run_command` | **T2** | 现有工具,**扩白名单** | 保持现有 `shell_confirm_policy` 人闸,**不放宽** |

- T0 三件:走 `_arslan_tools` 的既有注册路(和 web_search 同族),spawn 面按现有 registry 咽喉分级(safe)。
- T1 两件:注册但**首次调用产生一次授权请求**(复用 `run_command` 的 confirm 帧机制,见 §1.5)。
- 所有工具的 `path` 参数是 **workspace 相对路径**;绝对路径只在落在 workspace 内时接受。

### 1.4 T2 白名单扩展(小步)
现有 `{git,gh,ffmpeg,pandoc}` → 加 **只读/无副作用**类:`ls`、`cat`、`head`、`tail`、`wc`、`grep`、`find`、`rg`、`file`、`stat`、`du`、`df`、`which`、`uname`、`date`。
- 每个新二进制**必须**在 `classify()` 里有归级;**不写就是 fail-safe HIGH**(现有行为,正确)。
- 上述只读类归 **LOW**(ask_risky 下自动跑),但**只在 workspace 内 cwd**执行。
- 🔴 **不加**:`rm`/`mv`/`cp`/`chmod`/`curl`/`wget`/`ssh`/`scp`/任何解释器(`python`/`node`/`sh`)。解释器 = 任意代码执行,等于把整个分级作废。

### 1.5 授权机制(T1)
- 复用 WS 的 confirm 帧通路(`run_with_confirm_frames` / `confirm_command`,`server/ws/arslan.py`)。
- 第一次 T1 调用 → 前端出授权卡(显示 workspace 路径 + 要写的文件)→ 用户批 → **该 conversation 内**后续 T1 免确认。
- 会话结束/切线程 → 授权失效(内存态,不落库)。**这是「session 内免确认」的确切边界**。

### 1.6 设置面
`workspace_dir` 选择器 + 一句话说明(它是什么、Arslan 能在里面做什么)。六语。

---

## 2. 安全立场(逐条,评审必看)

1. **不谎称沙箱**:文件工具的边界=纯函数路径守卫,**代码注释和 UI 文案都不得暗示内核隔离**(§0 事实 2)。
2. **T2 子进程额外加固**(可选、加分项):给 workspace 内的命令用一个新 profile
   `workspace_profile(ws_realpath)` = `(deny file-write*)` + `(allow file-write* (subpath ws))`,
   仿 `readonly_profile` 写法。**这是纵深防御,不是主防线**;非 darwin 无此层(fail-closed 已有)。
3. **workspace 未设 = 文件工具不存在**(不是「存在但报错」)——能力自知面([[arslan-v0122-field-triage]] 第三报的教训)也要如实反映。
4. **T0 读也有边界**:不设 workspace 就读不了任何东西;设了也只能读 workspace 内 ⇒ `~/.ssh/id_rsa`、`~/Library/Application Support/Arslan/arslan.db` 天然在外。
5. **提议宁开、执行宁关**([[arslan-propose-vs-execute-bias]]):T0 免确认属提议面;T1/T2 属执行面,闸不放宽。
6. **`.env`/密钥文件**:即便在 workspace 内,`read_file` 对 `.env`/`*.key`/`*.pem`/`id_*` 命中名单**默认拒读**并说明理由(用户可在设置里放开——但 v1 不做那个开关,先拒)。

---

## 3. 验收判据(每条必须有测试,mutation 必红)

1. workspace 未设 ⇒ `_arslan_tools()` 里**不出现**任何 file 工具(不是出现后报错)。
2. `resolve_in_workspace` 五条规则各一测:`..` 逃逸拒、绝对路径外拒、**symlink 指向外部拒**、`/ws-evil` 不匹配 `/ws`(前缀陷阱)、写新文件按父目录判通过。
3. `read_file` 对 workspace 内 `.env` 拒读且理由可读;对普通文件通过。
4. `edit_file` 的 old 串**非唯一命中时拒**(不许静默改第一处——[[arslan-tests-must-discriminate]] 那条替换教训的产品化)。
5. T1 首次调用产生确认;同 conversation 第二次不产生;**新 conversation 又产生**。
6. 新增白名单二进制**全部**在 `classify()` 有归级(测试从白名单**派生**期望,不手工枚举——[[arslan-v0121-audit-round]] 的 SLOT_KEYS 规矩)。
7. `run_command` 的现有确认语义**逐条不变**(回归钉)。

---

## 4. 不做面(v1 明说)

- 递归全盘搜索、二进制文件读、大文件流式读(有界优先)。
- workspace 外的任何读写(**含**用户主目录其他位置)——要多目录等下一轮。
- `apply_patch`(OpenClaw 有;我们先用 `edit_file` 的唯一命中语义,更保守)。
- 解释器/网络二进制进白名单(§1.4 红线)。
- Linux 的 workspace_profile 加固(bubblewrap 未实装,fail-closed 现状不动)。

---

## 5. 裁决点(开工前请拍)

1. **workspace 默认值**:是否给一个建议默认(如 `~/Documents/Arslan Workspace`,首次使用时提议创建)?还是**必须用户显式选**(我倾向显式选,零默认)。
2. **T0 免确认**是否包含 `search_files`?(它能一次性扫出很多内容;我倾向包含——仍在 workspace 内且只读。)
3. **`.env` 类拒读名单**是否够(`.env*`/`*.key`/`*.pem`/`id_rsa*`/`*.p12`)?要不要加 `credentials*`/`*.token`?
4. **白名单扩展**那 15 个只读命令,有没有你不想要的?

---

## 6. 尚无证据、未声称已验

- 本 spec 零代码;§0 的现状为 2026-08-20 对 main `7ad1bc32` 亲核。
- `workspace_profile` 的 seatbelt 语法**未实测**(仿 `readonly_profile` 推演);它是加分项,开工时若实测不通就砍掉该层,**主防线不受影响**。
- P1 不触碰 P2/P3 的任何面;C 阶开工前重核 OpenClaw 现行安全默认这条(总纲 §6)**仍挂账**。

关联:[[arslan-shell-network-proxy]]、[[arslan-p0-sandbox-auth-hardening-round]]、[[arslan-propose-vs-execute-bias]]、[[arslan-allowlist-not-blacklist]]、[[arslan-assert-behaviour-not-source]]。

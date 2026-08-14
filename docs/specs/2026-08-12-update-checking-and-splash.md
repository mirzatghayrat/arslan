# 检查更新的可见反馈 + 开屏窗口同形 —— 任务书

**base**: `main = 1e827cf4`(v0.1.21 已发 draft)

两条来自用户实际使用的体验改进,**分两个 PR**:①是更新状态机 + 组件,②是开屏窗口与那一个 HTML。
它们唯一的共同点是「都跟启动/更新有关」,合在一起会让「哪个改动导致了什么」变难判断,
而 ② 触及打包窗口行为 —— 正是这个项目栽过三次的那一类([[arslan-packaged-only-defect-family]])。

---

## 0. 现状(2026-08-12 亲核,带 FILE:LINE)

| 事实 | 证据 |
|---|---|
| `Check for Updates` 是**原生菜单项**,不是网页按钮 | `desktop/src-tauri/src/lib.rs:624` |
| 检查期间**没有任何状态**可显示 | `UpdateStatus.state` 只有 `none/available/downloading/error`(`lib.rs:233`) |
| 启动检查刻意静默 | `lib.rs:296-300` 注释:离线是正常的早晨,不是用户能行动的错误 |
| pill **每 60 秒**才轮询一次 | `UpdatePill.tsx` `setInterval(poll, 60_000)` |
| 权限是**显式白名单**,只有四条 | `capabilities/remote-ui-drag.json`,**无 event 权限** |
| 开屏窗口 `decorations(false)` 且**未透明** ⇒ 直角 | `lib.rs` splash builder |
| `macOSPrivateApi` **未设置** | `tauri.conf.json` |
| 开屏视频**确实打进了出货二进制** | 在 v0.1.21 的 `arslan-desktop` 里验到 mp4 容器标记与文件名 |

---

## 1. 🔴 ②a 是一个 BUG,不是外观偏好

用户报的是「开屏动画结束时出现 `Starting Arslan…`,我不想要」。亲核后这不是有人加的文案:

- `#fallback`(那行字 + 脉冲点)**铺满整屏,压在 `<video id="clip">` 底下**(`splash/index.html:48-53`)
- `__arslanFadeOut()` **只给 `#clip` 加 `.gone`**(`:155`),`#fallback` 原地不动
- ⇒ 视频一淡出,底下的兜底层就露出来,正好在交接那 400ms 里

**那句 CSS 注释「costs nothing when the video plays」是错的** —— 播放期间确实不可见,
但**淡出期间可见,而淡出每次启动都发生**。

🔴 **顺带排除了更糟的假说**:一度怀疑是视频从未播放(用户截图是纯黑加一行字)。
在**已出货的 v0.1.21 二进制**里验到 mp4 容器标记 ⇒ 视频在包里。两个假说被区分开了。

---

## 2. 本轮裁决(用户 2026-08-12)

| # | 裁决 |
|---|---|
| ① | checking 状态**只在手动点菜单时显示**;启动检查保持静默 |
| ② | **不新增**「Starting Arslan」文字 —— 要的是**去掉**现有那个的意外显形 |
| ③ | ②a 用**方案 A**:淡出时把兜底层一起淡掉,保住它在视频失败时的用处 |

**方案 A 而不是 B(视频一播就 `display:none` 兜底)的理由**:autoplay 被拒和解码失败
在这个项目里**都真实发生过**(`splash/index.html:87-97` 记着实测:WebKit 到 readyState 4、
error 为 null,仍拒绝 play())。B 会让视频播到一半崩掉时什么都不剩。

---

## 3. 设计 ①:checking 状态

### 3.1 Rust 侧

`UpdateStatus.state` 增加第五个值 `"checking"`。`check_for_updates` 在 `updater.check().await`
**之前**、且**仅当 `interactive` 为真**时 `shared.set("checking", "", "")`。

🔴 **必须落回**:检查结束后每条路径都要离开 checking ——
`Ok(Some)` → `available`,`Ok(None)` → `none`,`Err` → `none`(**不是 `error`**:
`error` 状态在 pill 里是给安装失败用的,而检查失败已经有原生对话框了,
再在角上留一个红条是同一件事说两遍)。

**一个卡住的加载指示比没有指示更糟**,所以这条是硬要求,不是收尾工作。

### 3.2 🔴 60 秒轮询让这个功能看不见 —— 需要裁决

一次检查通常 1-3 秒,而 pill 每 60 秒轮询一次 ⇒ **绝大多数情况下 checking 状态在两次轮询之间就结束了**,
做出来等于没做。三条路:

| | 做法 | 代价 |
|---|---|---|
| **甲(推荐)** | Rust 用 `app.emit` 推状态变化,前端 `listen`;60 秒轮询保留为兜底 | 🔴 **要加权限**:`capabilities/remote-ui-drag.json` 现在只有四条显式白名单,需加 `core:event:allow-listen`。这是**安全面改动**,该被当作这样对待 |
| **乙** | 把轮询间隔从 60s 收紧到 1s | 不动权限。但**每秒一次 IPC 跑一整天**,只为一个用户一天点不了一次的按钮 |
| **丙** | 菜单点击后由 Rust 直接 `eval` 一段 JS 通知前端 | 不动权限,但绕过状态机、在两处描述同一件事 —— 正是本项目反复吃亏的「两份描述会漂移」 |

**我倾向甲**,并明写它是权限扩张:`allow-listen` 只授予监听,不授予发射,
且 capability 仍只绑 `main` 窗口。**若你不接受扩权,乙是可接受的退路**,丙不建议。

### 3.3 前端

`UpdatePill.tsx` 的 allow-list 加入 `checking`(那处注释已写明是 allow-list 不是 deny-list,
未知状态必须渲染 nothing —— 加值时要一并加进那个数组,否则新状态会被静默丢弃)。

渲染:三角点阵动效 + `Checking for updates…`,位置与现有 pill **完全相同**(右下角),六语文案。
checking 状态**不显示 Install / Later 按钮**,也**不可被 dismiss** —— 它是瞬时状态,不是待办。

### 3.4 动效

照参考(7×7 三角点阵逐行扫描)**用纯 CSS 重写**:参考实现是 Svelte 的,本项目是 React,
且不引新依赖。

🔴 **必须尊重 `prefers-reduced-motion`**:开启时显示静态点阵不扫描。
这不是可选的礼貌 —— 前庭功能障碍者会被持续动效影响。

---

## 4. 设计 ②:开屏

### 4.1 ②a 兜底层随视频一起淡出(**先做,它是 bug**)

`__arslanFadeOut()` 里同时给 `#fallback` 加 `.gone`,并给 `#fallback` 配同样的
`transition: opacity 400ms ease-out`。

**不改的部分**:`__arslanBootError` 已经显式 `display:none` 掉 fallback(`:164`),
那条路径正确,不动。

### 4.2 ②b 窗口圆角与主窗口一致

splash builder 加 `.transparent(true)`;`tauri.conf.json` 加 `macOSPrivateApi: true`;
`splash/index.html` 的根元素加 `border-radius`,窗口背景透明。

🔴 **诚实边界**:macOS 的窗口圆角半径由系统决定,**没有公开 API 可读**。
只能取一个视觉吻合的固定值(macOS 11+ 约 10px),**并在真机截图比对**。
本轮**不声称「精确一致」**,只声称「肉眼对齐,截图为证」。

🔴 **`macOSPrivateApi: true` 的代价必须明写**:它启用 Tauri 的私有 API 通路以支持透明窗口。
若将来 App Store 分发成为目标,这一项需要重新评估 —— 现在不是,但决定要留痕。

---

## 5. 验收

### ① checking

| # | 判据 | mutation |
|---|---|---|
| 1 | 手动检查期间状态为 `checking` | 去掉 `set("checking")` ⇒ 红 |
| 2 | **启动检查不进 checking** | 把 `interactive` 判断去掉 ⇒ 红 |
| 3 | 三条结束路径都离开 checking(available / none / none) | 任一条不落回 ⇒ 红(**这条防的是卡住的转圈**) |
| 4 | 检查失败落 `none` 而非 `error` | 改成 `error` ⇒ 红 |
| 5 | `checking` 在 pill 的 allow-list 里 | 从数组删掉 ⇒ 红 |
| 6 | checking 时不渲染 Install / Later | 渲染它们 ⇒ 红 |
| 7 | 六语齐、逐语言非空 | —— |
| 8 | `prefers-reduced-motion` 下不扫描 | 去掉媒体查询 ⇒ 红 |

### ② 开屏

| # | 判据 | mutation |
|---|---|---|
| 9 | `__arslanFadeOut()` 后 `#fallback` 带 `.gone` | 只淡 clip ⇒ 红(**这条就是那个 bug**) |
| 10 | `__arslanBootError` 仍然隐藏 fallback | 删掉那行 ⇒ 红(防止修 ②a 时把这条弄坏) |
| 11 | splash 窗口 `transparent` 为真 | 去掉 ⇒ 红(源码断言,因为它断言的是构建参数) |
| 12 | 真机截图:开屏四角与主窗口对齐 | —— 人眼,附截图 |

**判据 3 的形状要求**:三条结束路径要**分别**断言,不能只测一条。
「检查完成后状态是 X」这种写法在三条路里只走了一条,而卡住的转圈恰恰出在没被走到的那条。

---

## 6. 不做

- 不加周期性自动检查(v0.1.5 用户裁决:只在启动 + 菜单)。
- 不改 pill 的位置、尺寸、dismiss 语义。
- 不新增任何开屏文字(裁决 ②)。
- 不动 `#slow`(5 秒后出现的「首次启动在建库」)—— 它是另一件事,且真的有用。
- 不改开屏时长(地板 2.0s)。

---

## 7. 尚无证据 / 未声称已验

- **透明窗口在 macOS 上的阴影行为未验**:`transparent(true)` 可能改变系统投影,
  只能真机看。若阴影消失,②b 需要回来重新裁决(CSS 投影 vs 接受)。
- 圆角半径是**取值吻合**,不是从系统读的(§4.2)。
- 六语文案**无母语者校对**(既有挂账)。
- checking 状态在**打包版**里的表现本轮不验证 —— dev 里 `__TAURI_INTERNALS__` 不存在,
  updater 桥整体 no-op,所以 ① 只能在打包版真机验。**这是本轮最大的验证缺口,必须在交付报告里写明。**

关联:[[arslan-packaged-only-defect-family]]、[[arslan-update-ux-round]]、
[[arslan-assert-behaviour-not-source]]、[[arslan-tests-must-discriminate]]。

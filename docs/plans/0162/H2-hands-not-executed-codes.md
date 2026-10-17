# H2 Hands 什么都没做时，结果里明说「没执行」

| 项 | 内容 |
|---|---|
| 道 | ③Hands |
| 版本 | v0.1.62（赶不上则 v0.1.63） |
| 分级 | 必须 |
| 依赖 | 赶热修时：F5a（`release/0.1.62` 的 CI 靠它才绿） |
| 合并位置 | **尽量赶上 v0.1.62**（审查 §6）：开进 `release/0.1.62`，排在 F2 之前，F2 就直接认 `executed: False`。赶不上，就等 v0.1.62 发布、分支合回 main 之后，开进 main（v0.1.63），F2 先用它的回落（见 F2 卡） |
| 推动的门槛 | §5.2「其中『需要你核对』≤5%」 |
| 分支 | `claude/0162-h2-hands-not-executed-codes`（赶热修时从 `release/0.1.62` 拉、base 是它；否则从 main 拉） |
| 迁移号 | 无 |

## 目标

Hands 的工具只要在动手之前就停下了，比如被拒、没人答、App 不对、屏幕锁着，结果都写成下面这样：

```
{"ok": False, "code": <固定清单里的一个>, "executed": False}
```

F2 看到 `executed: False`，就把它记成已知失败，不再让任务以「需要你核对」收场。
可能已经做了一半的情况，绝不写 `executed: False`。

## 现状（亲核）

- **`_no`**（`server/registry/hands_tools.py:111-132`）：卡没让做时，返回五个码之一：`declined`、`no_answer`、`no_one_to_ask`、`reviewer_denied`、`not_allowed`。没有 `executed` 字段。
- **其他在动手之前就返回的路径：**
  - `act_in_background`：`:45-48`、`:878-879`、`:923-925`、`:962-969`、`:1000-1003`、`:1294-1296`；
  - `stopped_by_user`：`:972-974`；
  - `no_one_to_ask`：`:964-966`、`:1292`、`:1380`；
  - `bad_request`：`:874`、`:1233`、`:1374`；
  - `no_such_file`：`:1286`；`app_not_found`：`:1334`；`no_apps`：`:1390`；
  - 还有几处只有文字、没有码：
    - 「app required」：`:960`、`:1231`、`:1281`；
    - 「Arslan Hands is not available on this Mac.」：`:649`、`:676`、`:881`、`:971`、`:1298`、`:1377`。
- **`_failed(result)`**（`:516-519`）把 helper 的码原样透传。
  - helper 拒绝时，回 `{"ok": false, "refused": {"code", "message"}}`。Rust 端在 `desktop/hands/src/argv.rs:23`、`server.rs:210-212`，解析在 `server/services/hands_contract.py:129-136`。
  - 这些码的文字表在 `hands_contract.py:45-99`。
  - 其中有些码不是「没做」：
    - `unknown`：回复丢了，可能做了；
    - `submit_unsure`：字打进去了，没按回车；
    - `TIMEOUT`。
  - 所以不能把「refused」等同于「没执行」。
- **动作送达了、App 拒绝了：** `outcome == "refused"` 时返回 `ok: False`，说「nothing was delivered」（`hands_tools.py:1053-1055`、`:1072`）。
- **批量操作停在第几步时，前面的步骤已经做了**（`:1249-1260`，`batch_stopped`）。

## 定稿清单（③Hands 逐个在 Rust 端核过发出位置，2026-10-18，PR #189；⓪Plan 照录）

**没执行（`NOT_EXECUTED`，标 `executed: False`）：**

| 码 | 依据 |
|---|---|
| `declined` `no_answer` `no_one_to_ask` `reviewer_denied` `not_allowed` | 卡在动作之前（`_no`） |
| `act_in_background` `bad_request` `no_such_file` `app_not_found` `no_apps` `no_passwords` `no_page` `too_long` `append_unreadable` `window_not_found` | Python 端的前置检查；`app_not_found` 是 `open -g` 返回非 0（没打开） |
| `hands_unavailable` | 只在请求没送到 Hands 时抛（没送出、没装、没启动）；送出后丢了回复走 `_recover`，答 `unknown` |
| `app_denied` `app_look_only` `app_click_only` `op_not_allowed` `app_not_running` `app_ambiguous` `apps_unreadable` | Hands 端在执行动作之前的检查（`guarded`、`which_app`、`resolve_app`） |
| `bad_ref` `ref_unknown` `ref_wrong_app` `password_field` `target_unreadable` | `guarded` 读 ref 和字段状态，在动作之前 |
| `window_elsewhere` `window_unreachable` `screen_locked` | 去窗口、锁屏检查，都在动作之前 |
| `changed` | 动作之前；原文就写「Nothing was done」 |
| `borrow_off` `borrow_declined` `waiting_for_pause` `secure_input` `takeover_unsafe` | 借前台、接管开始之前 |
| `menu_unreadable` `menu_disabled` `menu_ambiguous` `menu_not_found` | 按下菜单之前；`menu_not_found` 是没找到、没按 |
| `bad_token` `peer_not_allowed` `no_takeover` `not_paused` | 请求进入派发之前 / 接管 API |
| `screen_recording_off` `window_not_capturable` `needs_macos_14` `not_supported` `capture_failed` | 截图没拍成（只读） |
| `app_refused` | 动作的结果是 `refused`（App 拒收）；今天只有 Cua Driver 路径会这么回，agent-desktop 不会 |
| `arg_not_allowed` `borrow_not_allowed` `element_required` `engine_missing` | Cua 路径自己的前置检查（正式版不编；F5b 删掉以后，③Hands 把这几个码从集合里删） |

**可能做了（`MAYBE_EXECUTED`，不标）：** `unknown` `TIMEOUT` `submit_unsure` `takeover_paused` `takeover_resumed` `takeover_ended` `stopped_by_user` `busy` `helper_failed` `bad_output` `bad_reply` `refused` `batch_stopped` `menu_press_failed` `append_needs_set_value` `browser_unavailable` `engine_error` `engine_refused` `engine_unknown`，以及 agent-desktop 的全部错误码。

**和原候选清单不同的地方：**

- `stopped_by_user`、`takeover_paused` 改为「可能做了」：Hands 在动作中途被 Stop 或接管暂停杀掉时，也说这两个码。Python 自己在发请求之前的那次 Stop 检查，单独标 `executed: False`。
- `append_needs_set_value`、`menu_press_failed`、`helper_failed`、`busy` 改为「可能做了」：动作可能已经送达。
- `hands_unavailable` 核过，归「没执行」：送出后丢了回复不会报它，走 `unknown`。
- 新补的码 `no_page`、`app_refused` 归「没执行」。
- 完整性测试保证：Hands 端和 Python 端出现的每个码都必须落在两个集合之一，两集合不相交。新码不归类，CI 就红。

## 怎么做（要点）

1. 先核 Rust 端：「待核」那两行里的每个码，在 `desktop/hands/src/` 里找到发出的位置，确认是在动作之前。
2. 定稿清单，写回上面那张表。拿不准的放进「不标」。
3. 再改 Python 端：加两个集合，给每条路径写上 `executed: False`。
4. 最后补完整性测试和执行器测试，跑一遍冒烟。

## 改哪些文件

- **`server/registry/hands_tools.py`：**
  - 加两个集合：`NOT_EXECUTED`（定稿后的清单）和 `MAYBE_EXECUTED`；
  - `_no`、`_failed` 和上面那些前置检查，都按清单写上 `executed: False`；
  - 只有文字的返回补上码。
- **测试：**
  - 新文件 `tests/server/test_hands_not_executed.py`。
  - 有改了措辞的现有测试，就同步改，比如 `test_hands_0145.py:66` 断言了 `act_in_background`。
- **`docs/CAPABILITY_INVENTORY.md`：** rebase 到目标分支后重新生成（`.venv/bin/python -m scripts.capability_inventory > docs/CAPABILITY_INVENTORY.md`）。`hands_tools.py` 的哈希在里面。冲突时随便取一边，再重新生成，不手工合。
- **本卡的清单：** 已按 PR #189 改成定稿版（⓪Plan 代改，`docs/plans/**` 归 ⓪Plan）。

## 不许碰

- `server/services/hands_contract.py`：它不在 ③Hands 的文件清单里。要改，先找 ②Main。按上面的做法不需要改它。
- `server/services/task_service.py`（F2 的事）；
- `desktop/hands/**` 的行为；
- 告诉模型的文字：只加字段和码，不改措辞；
- Bridge 文件。

## 验收

- **完整性测试：** `hands_contract.REFUSALS` 里的每个码，以及 `hands_tools.py` 里出现的每个 `code`，都必须落在 `NOT_EXECUTED` 或 `MAYBE_EXECUTED` 里。以后新加的码，不归类 CI 就红。
- **每一类至少一个执行器层面的测试：**
  - 卡被拒：`executed is False`，`code == "declined"`；
  - 前置检查（屏幕锁、永不碰的 App）：`executed is False`；
  - `unknown` 和 `submit_unsure`：没有 `executed: False`。
- 现有 Hands 测试全过。
- `scripts/hands_smoke.py` 在开发版上跑一遍，和改动前一致，结果写进 PR。

## 量级

产品代码约 40–80 行，外加测试。

## 风险与回退

- **风险：** 把「可能做了」错标成「没执行」，F2 就会放过一个真的需要核对的动作。
  - 拿不准的一律归到 `MAYBE_EXECUTED`。
  - 宁可多问一次，不能漏问。
- **赶不上热修：** 定稿清单的核对（第 1、2 步）多半是工期的大头。FR 要开发版 PR 时还没合，就不等，转 main。
- **留着的东西：** 无。F2 里「只认 `_no` 那 5 个码」的回落归 F2 卡管：本卡赶上热修，F2 就不写它；赶不上，本卡合进 main 之后由 ②Main 删（v0.1.63 内）。
- **回退：** revert 合并提交。F2 的回落不受影响（只认 `_no` 那 5 个码）。

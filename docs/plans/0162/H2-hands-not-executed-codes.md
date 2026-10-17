# H2 Hands 什么都没做时，结果里明说「没执行」

| 项 | 内容 |
|---|---|
| 道 | ③Hands |
| 版本 | 热修版 |
| 分级 | 必须 |
| 依赖 | — |
| 合并位置 | F2 之前（软依赖：F2 没等到也能先合，见 F2 卡） |
| 推动的门槛 | §5.2「其中『需要你核对』≤5%」 |
| 分支 | `claude/0162-h2-hands-not-executed-codes` |
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

## 候选清单（③Hands 逐个核对 Rust 端在哪里发出，定稿后改这一节）

| 归类 | 码 | 依据 |
|---|---|---|
| 没执行 | `declined` `no_answer` `no_one_to_ask` `reviewer_denied` `not_allowed` | 卡在动作之前（`:1009-1029`） |
| 没执行 | `act_in_background` `stopped_by_user` `bad_request` `no_such_file` `app_not_found` `no_apps` | Python 端的前置检查 |
| 没执行（补码） | `hands_unavailable`（`:498` 已有这个码，那 6 处只有文字的也改用它；但见表下第一条）、`bad_request`（给「app required」补上） | 同上 |
| 没执行（待核） | `app_denied` `app_look_only` `app_click_only` `ref_wrong_app` `ref_unknown` `bad_ref` `password_field` `borrow_off` `waiting_for_pause` `secure_input` `window_elsewhere` `window_unreachable` `borrow_declined` `screen_locked` `takeover_unsafe` `target_unreadable` `app_not_running` `apps_unreadable` `app_ambiguous` `append_unreadable` `append_needs_set_value` `op_not_allowed` | 文字表多数写着「Nothing was done」，要在 Rust 端核对是不是在动作之前发出 |
| 没执行（待核） | `outcome == "refused"` | 「nothing was delivered」 |
| **不标**（可能做了） | `unknown` `TIMEOUT` `submit_unsure` `takeover_paused` `bad_output` `bad_reply` `batch_stopped`；agent-desktop 的错误码（`ACTION_FAILED` 等）；`_run` 超时（`:286`） | 回复丢失、半途停止、执行中报错 |

表下第一条：`hands_unavailable` 有一种情况要分开：连接 helper 之前就失败，是没执行；请求发出之后连接断了，就不能算。
`_hands` 里的 `HandsUnavailable` 是哪一种（`:495-499`）要核，核不清就不标。

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
- **`docs/CAPABILITY_INVENTORY.md`：** rebase 后重新生成（`.venv/bin/python -m scripts.capability_inventory > docs/CAPABILITY_INVENTORY.md`）。
- **本卡的「候选清单」：** 改成定稿版。

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
- **回退：** revert 合并提交。F2 有回落：只认 `_no` 那 5 个码。

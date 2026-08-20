# P2 施工 spec:主动性引擎(Arslan 成为调度的主体)

日期:2026-08-20 · 状态:**待用户批** · 总纲:`2026-08-20-agent-reach-and-proactivity.md` 支柱 B
前序:P1 已出货(v0.1.25)。用户裁决(2026-08-20):P1→P2→P3;随做随发。

---

## 0. 开工前亲核:P2 比总纲写的**窄得多**

用户规矩「别在总纲的 file:line 上直接动手」。全核 `scheduler.py`(596 行)+ `api/scheduled_tasks.py` + 模型。**S3-M4 的调度层是完整的**,总纲列为「要抄 OpenClaw」的东西**大半已有**:

| 总纲说要做 | 亲核结果 | 位置 |
|---|---|---|
| 定时触发 | ✅ 已有 | `scheduler.py`:5 字段 cron + interval + `compute_next_due` + `tick`/`watch_loop` |
| **连败自停** | ✅ **已有** | `PAUSE_AFTER_FAILURES = 3` + `_notify_pause` 通知会话 |
| 结果送达 | ✅ 已有 | `recap_service.log_event` + 会话内 run |
| 单飞/防重叠 | ✅ 已有 | in-flight row 即闸 + `record_skip_overlap` |
| 花钱闸 | ✅ 已有 | `MAX_ENABLED = 10`、`MIN_INTERVAL_S = 900` |
| 崩溃自愈 | ✅ 已有 | `sweep_orphans` + 重启从 `next_due_at` 恢复(不补跑) |
| 用户建任务 | ✅ 已有 | `POST/PUT/DELETE /scheduled-tasks` + pause/resume |

### 🔴 真缺口只有三条

1. **调度只能派给 spawn**。`_fire`(`scheduler.py:464`)必须有 `spawn_id`,`_require_spawn`(`api/scheduled_tasks.py:65`)在 API 层强制存在;spawn 被删则任务报错自停。**Arslan 自己不能被排程** ⇒ 「每天早上把 CI 汇总给我」这种事必须先造一个分身。
2. **Arslan 不能自排程**:`grep schedule_task` 在 executors/arslan.py **零命中**。它无法把「明早提醒你」变成一条真任务。
3. **无 heartbeat 清单轮**:没有「周期性醒来、读一份用户写的清单、决定要不要动手」的东西。

**⇒ P2 = 让 Arslan 成为调度的主体**,不是重建调度。

---

## 1. 交付物

### 1.1 A — 无 spawn 的 Arslan 轮(地基,其余两条都要它)
- `ScheduledTask.spawn_id` 已可空(`ondelete SET NULL`)。改语义:**NULL = 派给 Arslan 自己**,不再是「悬空错误」。
- `_fire` 分叉:有 spawn_id → 今天的 `dispatcher.dispatch` 路径**一字不动**;无 spawn_id → 走 `arslan.handle_user_message`。
- 🔴 **headless 上下文的诚实处理**:Arslan 轮通常带 WS 的 `emit` 和两个 confirm 回调。定时触发**没有 socket**,所以:
  - `emit` = 走 `run_registry.make_emit(cid)`(已有的 fan-out:有 tab 开着就实时看到,没有就落 recorder journal)。
  - **两个 confirm 回调都传 None** ⇒ `run_command` 与 workspace 写在定时轮里**自动拒绝**(P1 已实测的安全默认)。**这是刻意的**:无人值守 + exec 正是 OpenClaw 那两篇 arXiv 的攻击面,总纲 §3.1「抄形态、反默认」在此落地。定时轮只能用只读工具。
  - API 的 `_require_spawn` 改为「给了才校验」。
- **验收**:`spawn_id=None` 的任务能跑完并留下 Run;其轮内 `run_command`/`write_file` 被拒且理由可读。

### 1.2 B — `schedule_task` 工具(Arslan 自排程)
给 Arslan 一个工具,复用**现有** `scheduled_tasks` 服务与全部闸:
```
schedule_task(name, prompt, when)   # when: "cron: 0 9 * * *" | "every: 3600"
```
- 落库前**照走** `MAX_ENABLED`/`MIN_INTERVAL_S`/cron 合法性校验——**不新开咽喉**,超限就返回可读拒绝。
- `spawn_id` 默认 None(=派给自己,§1.1);`conversation_id` = 当前会话,所以结果回到用户看得见的地方。
- 🔵 **闸的裁决点(见 §4)**:建任务是「花未来的钱」。默认我倾向 **T1 式一次会话授权**(与 workspace 写同形),而非逐条确认或全免。
- 同时给 `list_my_tasks` / `cancel_task`——一个能建却不能查不能撤的 agent 会制造用户删不掉的东西。

### 1.3 C — heartbeat 清单轮
- 一份用户可编辑的清单(存 `Setting`,**不是** workspace 文件——那要求用户先设 workspace,把两个功能耦死)。
- 一条**内置的**周期任务:到点把清单作为 prompt 跑一轮 Arslan(§1.1 的路径),让它自己判断「有没有哪条现在该动手」。
- **默认 OFF**,间隔用户设(仍受 `MIN_INTERVAL_S=900` 约束)。
- 🔴 **只提议不执行**:清单轮的产出是**给你的消息**(建议/发现),不是自动动作——因为它的 confirm 回调是 None,写与命令**结构上**做不到,而不是靠自觉。
- **条件触发**(总纲有):**本轮不做**,登记。理由:OpenClaw 的条件脚本正是「默认无人值守带 exec」的那一面,我们要做也得先把提议面走通、拿真机反馈,再谈。

---

## 2. 安全立场

1. **无人值守 = 只读**。定时轮拿不到 confirm 回调 ⇒ T1 写与 T2 命令自动拒绝。这是**结构性的**(P1 的闸本就是「无回调即拒」),不是新规则。
2. **提议宁开、执行宁关**:heartbeat 产出建议;要动手,用户在聊天里说一句。
3. **花钱闸不新开**:自排程复用 `MAX_ENABLED`/`MIN_INTERVAL_S`,超限拒绝并说明。
4. **可见可撤**:Arslan 建的任务与用户建的在同一张表、同一个 UI 里,一键暂停/删除。
5. **不抄条件触发的默认值**(总纲 §3.1)。

## 3. 验收判据(每条要测,mutation 必红)

1. `spawn_id=None` 的任务跑通,产生 Run,`kind="scheduled"`。
2. 定时轮内 `run_command` 被拒;`write_file` 被拒;`read_file`(有 workspace 时)**可用**——梯度成立。
3. 有 spawn_id 的老路径**逐条不变**(回归钉)。
4. `schedule_task` 超 `MAX_ENABLED` 时返回可读拒绝且**不落库**。
5. `schedule_task` 的 cron 非法 → 拒绝且不落库。
6. Arslan 建的任务在 `GET /scheduled-tasks` 里出现(可见)、能被 pause/delete(可撤)。
7. heartbeat 默认 OFF ⇒ 不产生任何任务/fire。
8. heartbeat 开启后到点跑一轮,且该轮的写/命令工具被拒。

## 4. 裁决点(开工前请拍)

1. **`schedule_task` 的闸**:①一次会话授权(与 workspace 写同形,我倾向)②每次建任务都确认 ③默认开、只受配额约束。
2. **heartbeat 清单存哪**:①`Setting` 里一段文本(我倾向,零耦合)②workspace 里的 `HEARTBEAT.md`(更像 OpenClaw,但强制用户先设 workspace)。
3. **heartbeat 默认间隔**:OpenClaw 是 30 分钟;我倾向**默认 OFF + 首次开启时建议 6 小时**(15 分钟下限仍在)——你的机器你的电费。
4. **条件触发本轮跳过**是否同意。

## 5. 尚无证据、未声称已验

- 本 spec 零代码;§0 现状为 2026-08-20 对 main `23d56ae2` 亲核。
- `handle_user_message` 在**完全无 socket**的上下文里跑通,尚未实测——这是 §1.1 的头号风险,开工第一件事就是拿测试证它(而不是假设它能跑)。
- P3(触达/舰队)不在本轮;「C 阶开工前重核 OpenClaw 现行安全默认」仍挂账。

关联:[[arslan-agent-reach-p1]]、[[arslan-propose-vs-execute-bias]]、[[arslan-scheduler-round]]、[[arslan-launch-gate]]。

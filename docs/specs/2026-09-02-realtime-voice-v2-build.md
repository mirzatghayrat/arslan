# 实时语音 V2 施工 spec:常开对话(说了就干)

> 状态:**已批(2026-09-02);探针 P1–P3 已做(2026-09-03),决策①=B 嘴留 webview**。用户对 §9 三条拍板全按建议:V2a 半双工先出 · V2 打断不取消生成 · `voice_mode` 默认 `push_to_talk`。决策①仍由探针 P1 决定。§0.2 的红灯已随 PR #82 修入 main。上位 spec = `2026-09-02-realtime-voice.md`(三条建议已同意,V1a 已随 v0.1.36 出货,V1b 在 PR #81)。
> 用户 2026-09-02 原话:「我要的不是语音转文字的交互方式,是直接语音交流下指令就能直接干的」——这句话回答了上位 spec §6 里唯一逻辑定不了的产品判断:**按住说话不够,要常开**。
> VibeVoice 已评估、不采用(记忆 `arslan-vibevoice-eval`):它是嘴和耳,不是这份 spec 要的任何一件。

## §0 先摆事实:V2 要站在什么上面(全部亲核,FILE:LINE)

### 0.1 V1a 现在的形状
| 事实 | 出处 |
|---|---|
| helper 是**一次性**进程:一次按住 = 一次 spawn,stdin 关 = 结束 | `packaging/listen/arslan-listen.swift:64-67`, `desktop/src-tauri/src/listen.rs:95-109` |
| 麦克风 tap 直通 `SFSpeechRecognizer`,`shouldReportPartialResults=true`,on-device(zh-CN/en-US 实测) | `arslan-listen.swift:100-107, 148-149` |
| **没有** VAD、端点检测、静音计时、音量计;final 由识别器自己的 `isFinal` 决定,松手后 8 秒看门狗 | `arslan-listen.swift:138, 172-174` |
| Rust 侧一条事件通道 `voice://line`,把 helper 的每行原样转给 webview | `listen.rs:29, 71-79` |
| **final 只填进输入框,不发送**;用户还得按回车 | `web/src/components/OrchestratorChat.tsx:553-558` |
| 按住说话按钮**只在空会话的输入框里有**;有了消息之后的那个输入框没有它 | `OrchestratorChat.tsx:1437-1500` |
| 嘴在 **webview**(Web Speech),不在原生 | `web/src/lib/speech.ts:4-8` |
| `run_cancelled` **不停嘴**;停嘴只有关开关和换会话两个入口 | `web/src/stores/arslanStore.ts:274, 285, 530-571` |
| 中断回复只有 HTTP `POST /runs/{id}/cancel`,且**只对有 run_id 的回合有效**;普通 Arslan 回合不可取消;WS 没有 stop 帧 | `web/src/api/client.ts:496`, `server/api/runs.py:483-495`, `server/ws/protocol.py:33-37` |
| 仓库里**零处** VoiceProcessingIO / setVoiceProcessingEnabled:AEC 是全新代码 | grep 全仓 |

### 0.2 🔴 一条先于 V2 的红灯:V1a 在打包版里大概率是坏的
`generate_handler!` 注册了 `voice_start`/`voice_stop`(`desktop/src-tauri/src/lib.rs:723-729`),但 **build.rs 的命令清单只有三个旧命令**(`build.rs:6-10`),**capability 只放行那三个的权限**(`capabilities/remote-ui-drag.json`),仓库追踪的生成物 `gen/schemas/acl-manifests.json` 里 `voice` 出现 **0 次**。Tauri 2 的 ACL 对远程源(`http://127.0.0.1`)的 invoke 逐命令放行,没生成权限的命令**不可能被放行** ⇒ 打包版按住说话 = `press()` 抛错 → 输入框上方一行原始错误。
- 这是「A 处标识符必须和 B 处键对上而无守卫」的第四次。
- **处置:独立 PR 先修**(build.rs + capability 两处 + 一个 lockstep 守卫:从 `generate_handler!` 派生,断言每个命令在 build.rs 清单和 capability 权限里都有),不进 V2 的范围。V2 的一切都假设它已修。
- 尚无证据:我这台机器没法跑打包 ACL。**修完后的真机验收 = 原本挂着的「v0.1.36 按住说话」验收**,一次做两件事。

### 0.3 决定架构的那个物理问题 —— 已测(2026-09-03,本机 macOS 26.6.2,M 系 MacBook Pro 内建麦克风+扬声器,AirPods 收进盒子)

探针 = 签名 .app + `open`(`packaging/probes/voice/`,含完整日志)。**先证明探针能出正值再取结论**:VP 关时,真人说话被识别(P0),`say` 从扬声器放的句子被识别 4/5 关键词(P1c,三轮一致)。

| 用例 | 三轮结果 | 结论 |
|---|---|---|
| P1c VP 关、**别的进程**(`/usr/bin/say`)放 | 4/5 · 4/5 · 4/5 关键词,整句转写出来 | 对照组:回声真实存在、探针能听见 |
| **P1d VP 开、别的进程放** | **0/5 · 0/5 · 0/5**,残余峰值 0.008–0.029(对照 0.026–0.057) | **系统级 AEC 成立:VP 消掉了别的进程通过同一输出设备放的声音** |
| P1b VP 开、engine 内 playerNode 放 | 0/5 ×3 | 构造上的 AEC 也成立 |
| P3 VP 开、真人说中文 | 18 个 partial | **VP 下识别器活着**(P1b/P1d 的「没听到」不是识别器聋了) |

⇒ **决策① = B:嘴留 webview**(V1b 刚修好的那套原样用),AEC 靠系统。不搬 AVSpeechSynthesizer。

**顺手钉死的硬事实**(写代码时会撞上,每条都是实测):
- **VoiceProcessingIO 的设备永远跟系统默认输出**。`kAudioOutputUnitProperty_CurrentDevice` 手动指定被拒(-10851),私有聚合设备也被拒;默认输出=内建扬声器时它自动配对内建麦克风。⇒ 用户切到 AirPods/外接输出时 VP 跟着走;**外接扬声器 + 内建麦克风的组合未测**。
- VP 开后 `inputNode.outputFormat` = **48 kHz / 9 声道**(九路内容相同),喂识别器要**只取第 0 声道再降到 16 kHz 单声道**;直接 9→1 用 AVAudioConverter 混出来的是垃圾,识别器报 1110 No speech(踩过)。
- 有播放节点时必须**显式 `connect(mainMixer, to: outputNode, format: outputNode.outputFormat)`**,`format: nil` 必失败(-10875)。V2 用 B 方案后 helper 里没有播放节点,这条只在探针里重要。
- VP 会话拆掉后,下一个非 VP 的 AVAudioEngine 会短暂读到输出设备 0 Hz(初始化 -10875);启动前等 `outputNode.outputFormat.sampleRate > 0`。
- `AVSpeechSynthesizer.write` 和 Speech 回调都投递到主队列:helper 的主线程不能被阻塞(V1a 的 helper 用 `RunLoop.main.run()` 是对的)。
- 这台机器**内建扬声器音量是 0**(33 是 AirPods 的);探针自己把它拉到 80 再还原。真机验收前先看这个。

**P2(连续重 arm,VP 关)**:`endAudio → final` **20–40 ms**;新 request 到第一个 partial 0.9–2.5 s;on-device 连续三句无问题、无重复 final。🔴 **「partial 900 ms 没变化」不是端点**:on-device 识别器的 partial 更新很稀疏,`say` 一句不停顿的话被切成「What」+「About the weather」。§3.1 据此改。
AEC 要**参考信号**(扬声器放了什么)。嘴在 webview 里 ⇒ 原生 helper 看不见自己要消的是什么。
macOS 的 VoiceProcessingIO 对**同一个 audio unit 输出**的声音消回声是确定的;对**别的进程**放的声音能不能消 —— **我不知道,要测**(§5 P1)。这一个探针决定 §2 的形状。

## §1 目标 / 非目标

**目标**:一个「对话模式」开关。开着的时候不碰键盘鼠标:你说 → 它听到你停下 → 直接当一条 user message 走现有 tool loop → 回复边到边念 → 你随时开口它立刻闭嘴听你。

**非目标**(明写,免得顺手做):唤醒词;多设备/远程麦克风;云端 ASR(上位 spec 决策①已否);数字人;**动 tool loop 一行**;绕过执行闸 —— 语音只是输入法,风险命令的确认卡照弹,卡上的「确认」仍要点(或说「确认」—— 那是 V3 的事,不在这轮)。

## §2 架构

```
麦克风 ──► [arslan-voice helper, Swift, 长驻]  AVAudioEngine + VoiceProcessing(AEC)
             │ 送 SFSpeechRecognizer,持续出 partial(带时间戳)
             │ (决策①=A 时)也放 TTS:AVSpeechSynthesizer.write → AVAudioPlayerNode → 同一 engine
             ▼ JSON 行,双向(stdin 命令 / stdout 事件)
          [Rust 壳 voice.rs]  端点判定 + barge-in 判定 = 纯函数,cargo test 覆盖
             ▼ voice://line 事件(沿用) / invoke 命令
          [前端]  对话模式开关 · final→自动发送 · 回复分句→say · interrupted→cancelRun
             ▼ 一条普通 user_message,现有 WS,tool loop 不动
          [Python sidecar]
```

**三条设计原则**
1. **策略在 Rust,管线在 Swift。** Swift 只做 macOS 才有的事(采音、AEC、识别、合成),不做判断;「说完了吗」「该打断吗」是纯函数,放 Rust,CI 的 cargo test 跑得到。Swift 在 CI 里只有 macos job 能编译,不能单元测。
2. **helper 长驻、一次 spawn。** V1a 的一次一进程在常开下不成立(每句重新授权、重新起 engine)。生命周期跟 V1a 一样绑 stdin:壳没了它就死,强退不会留一个开着麦克风的孤儿(`listen.rs:86-88` 的理由原样成立)。
3. **一条 user message 就是一条 user message。** 语音 final 走 `sendOrchestratorMessage`(`web/src/App.tsx:338-355`),和敲回车一个字节不差。语音坏了最坏是回到打字。

### 决策①:嘴放哪(探针 P1 决定,不猜)
| | A. 嘴搬进 helper(AVSpeechSynthesizer 经 engine 出声) | B. 嘴留 webview(Web Speech,V1b 刚修好) |
|---|---|---|
| AEC 参考信号 | **构造上保证**:放和收在同一个 engine | 赌系统级 AEC 对别的进程有效(P1 测) |
| barge-in 停嘴 | 进程内,零跳 | 壳→webview 事件→`speechSynthesis.cancel()`,一跳 |
| 代价 | 新桥、V1b 的选嗓音逻辑要在 Swift 重做一遍(按文本语言选 `AVSpeechSynthesisVoice`) | 几乎零 |
| **建议** | **P1 若说「跨进程消不掉」→ 只能 A** | **P1 若说「消得掉」→ B,把预算留给端点和打断** |

### 决策②:先半双工还是直接全双工 —— **建议 V2a 半双工先出**
V2a = 常开听 + 端点 + 自动发送,**它念的时候麦克风静音**(说话时不能打断)。这一步就已经是「说了就干」,而且**完全绕开 AEC** —— 上位 spec §3.1 的退路。V2b 再加 AEC + barge-in。如果 V2a 用起来已经够,V2b 最贵的那部分可能根本不用花;反过来先做 V2b 再发现方向不对,浪费的是最贵的。

### 决策③:打断时要不要取消生成 —— **建议 V2 不取消,V2c 再说**
打断 = 立刻闭嘴 + 听你说 + 你的新一句照常发送。正在流的那条回复**继续以文字流完**(便宜、安全、tool loop 不动)。取消生成要么靠现有 `cancelRun`(只对有 run_id 的回合有效),要么加 WS 帧/让普通回合可取消 —— 后端改动,单独一轮。

## §3 三个难点的具体做法

### 3.1 端点检测(什么时候算你说完)—— Rust 纯函数(按 P2 结果改:用**音频静音**不用 partial 停更)
输入:识别器的 partial 流(文本 + 到达时刻)。规则(V2 用静音超时,上位 spec 定的):
- helper 每 100 ms 报一次输入电平(`level{peak}`,第 0 声道的绝对峰值,探针量的就是它:静音 ≤0.016、人声 ≥0.15,门限 0.04);壳维护「最近一次高于门限的时刻」。**partial 非空**,且 `now - last_voice_above_threshold ≥ endpoint_silence_ms`(默认 900,可调)⇒ **端点** ⇒ 壳发 `{"c":"end_utterance"}` → helper `request.endAudio()` → 识别器出 final(实测 20–40 ms)→ **立刻重新 arm 一个新 request**(常开的关键:识别 session 是一句一个;新 request 到首个 partial 实测 0.9–2.5 s,这段延迟是 V2a 体感的主要来源)。
- 🔴 不用「partial 多久没变」判端点:P2 实测 on-device 识别器 partial 更新稀疏,一句不停顿的话会被切成两条。
- partial 是空的 ⇒ 永远不算端点(呼吸、噪音不发消息)。
- 一句 final 的文本和上一句相同且间隔 < 1s ⇒ 丢弃(识别器重启时偶发重复,P2 会量)。
- `endpoint_silence_ms` 是**唯一**的调参旋钮,进设置。语义端点(「他停了但话没说完」)明确不做。

### 3.2 barge-in(你一开口它闭嘴)—— Rust 纯函数 + helper 一个命令
- 状态 = speaking 时收到 partial,且 partial 长度 ≥ `barge_in_min_chars`(默认 2,不进设置,常量)⇒ **打断** ⇒ 壳发 `{"c":"stop_say"}` → helper 停播、清队列、回 `{"t":"interrupted"}` → 壳事件到前端 → 前端丢掉本回合剩余分句(文字照显示)、`activeRunId` 有值时顺手 `cancelRun`(有就用,没有不加)。
- 阈值的意义:AEC 不完美,残余回声会被识别成一两个字;两个字以内不算你在说话。**这个数字 P1 会给出真实残余量,再定。**
- V2a 半双工下这条不存在:speaking 时 helper 不喂识别器(`input.removeTap` 或直接丢 buffer)。

### 3.3 AEC(V2b)—— 探针已定:B 方案,靠系统
`AVAudioEngine.inputNode.setVoiceProcessingEnabled(true)`。P1d 三轮实测:webview 里 Web Speech 放的声音(对 helper 来说是别的进程)被 VP 消掉,识别器听不到一个关键词。⇒ helper 只管耳朵:VP 开、tap 取第 0 声道、降到 16 kHz 单声道、喂 SFSpeechRecognizer。**嘴不动**。A 方案(TTS 搬进 helper)作废,不再讨论。

## §4 helper 协议(JSON 行,双向)

stdin 命令(V2a):`{"c":"end_utterance"}` · `{"c":"mute"}` / `{"c":"unmute"}`;locale 走第一个位置参数;stdin 关 = 退出。(`say/stop_say` 随 A 方案作废。)施工 plan:`docs/specs/2026-09-03-realtime-voice-v2a-plan.md`。
stdout 事件(V2a):`ready` · `partial{text}` · `final{text}` · `level{peak}` · `state{muted}` · `error{code,msg}`;壳补一条 `ended`。(`speaking/spoke/interrupted` 是 A 方案的,随决策①=B 作废。)
错误码沿用 V1a 七个;**顺手收掉两处死分支**(`PushToTalk.tsx:55-57` 的 `mic-auth-timeout`/`speech-auth-timeout` 从没被发出;`recognizer-unavailable`/`engine-failed`/`recognition-failed` 没有映射)—— 这是 V2 会重写这张表,不算顺手扩范围。

Rust `voice.rs`(取代 `listen.rs`,保留 `voice_start`/`voice_stop` 名字给 PTT 兼容):命令 `voice_conversation_start/stop`、`voice_say`、`voice_stop_say`;事件通道沿用 `voice://line`(它的名字有 Rust 测试钉着,`listen.rs:111-121`)。🔴 每个新命令 = build.rs 清单 + capability 权限 + 守卫,三处 lockstep(§0.2 的守卫会替你逮)。

## §5 探针(开工前必做;手法 = 上位 spec 同款:签名 .app + `open`)

| # | 问题 | 结果决定什么 |
|---|---|---|
| **P1** ✅ | VP 开着、别的进程放一句话、麦克风同时喂 SFSpeech:转写里**有没有那句话** | **没有(0/5 ×3;对照 4/5 ×3)⇒ 决策①=B**;残余峰值 ≤0.03,识别器不出字 ⇒ barge-in 阈值 2 字够用(待真机复核) |
| **P2** ✅ | 常开下重 arm 的间隔;on-device 连续用;重复 final | final 20–40 ms;首 partial 0.9–2.5 s;三句无重复;**partial 停更不能当端点** |
| **P3** ✅ | VP 后 inputNode 格式;SFSpeech 收不收 | 48 kHz/9 ch(九路相同);**取第 0 声道 + 降 16 kHz 单声道后识别正常**(18 partial) |
| **P4** | §0.2 修完后打包版 `invoke('voice_start')` 能不能过 | = V1a 真机验收本身 |

## §6 设置(只加三个键)
`voice_mode`: `off` / `push_to_talk` / `conversation`(默认 `push_to_talk`,即今天的行为;`voice_output_enabled` 不动,它继续管「不说话也想听」)· `voice_endpoint_silence_ms`(默认 900)· `voice_barge_in`(默认 true,V2b 才露出)。
🔴 每个键七处 lockstep:`server/schemas.py` 入/出两个模型、`settings_service._PLAIN_KEYS`、`client.types.ts`、`adapters.ts` 读+写、`data.ts`、`types.ts`、`AdvancedSection.tsx`、六个 locale、`settings-put-carries-only-what-was-touched` 测试(`github_token` 就是少一处静默坏掉的先例,`settings_service.py:24-26`)。

## §7 分阶段(每阶段独立可验收)
- **V2a 半双工常开**:helper 长驻双向 + Rust 端点纯函数 + 对话模式开关(两个输入框都有)+ final 自动发送 + 念的时候静音麦克风。**验收:不碰键盘,连说三句,三条都发出去、都执行了。**
- **V2b 全双工**:P1 决定 A/B → AEC + barge-in。**验收:它念到一半你开口,它一秒内闭嘴,你的话被发出去。**
- **V2c(可选)**:打断取消生成(后端)。

## §8 测试
- **Rust cargo test**:端点判定表(partial 时序 → 端点/不端点)、barge-in 判定表(状态 × partial 长度)、helper 行解析、命令序列(mute/unmute 状态机)。**mutation 必做**:把 900 改成 0、把阈值改成 0,各要有测试红。
- **vitest**:对话模式下 final → `sendOrchestratorMessage` 被调且输入框清空;`interrupted` → 本回合剩余分句不再 `say`、有 `activeRunId` 时 `cancelRun` 被调;模式切换时 helper 被停。
- **Python lockstep 守卫**:§0.2 那个;设置键七处一致性(从 `_PLAIN_KEYS` 派生)。
- **Swift 不单测**;macos job 只编译它(`build_dmg.sh:157-161` 那条「编不过就不许出无声 app」原样保留)。
- **真机脚本**(五条,验收回执用):①三句连发 ②中文说、英文界面 ③念一半打断 ④风险命令说出来 → 确认卡弹、不执行 ⑤关模式 → 麦克风指示灯灭。

## §9 尚无证据 / 要你拍板
- **已拍板(2026-09-02)**:决策② V2a 先出 ✅ · 决策③ V2 不取消生成 ✅ · `voice_mode` 默认 `push_to_talk` ✅(常开是选择不是默认)。决策①不用拍,P1 拍。
- **尚无证据**:P4(打包版 invoke,= v0.1.36 真机验收);**外接扬声器 + 内建麦克风**下 VP 的设备配对;VP 的 AGC/降噪对中文识别率的影响;常开一小时的 CPU/电量(只能真机量);「两个字阈值够不够」只在本机三轮上成立。
- **不做的理由要写清**:不做语义端点、不做唤醒词、不动 tool loop、不绕执行闸。

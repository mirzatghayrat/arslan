# Spec:语音对话(边说边做任务,不是"有张嘴的聊天")

日期:2026-08-24 · 状态:**待用户批** · 触发:用户看 LiveTalking,澄清要的不是数字人,是"说一句话 → Arslan 真的去查文件/干活 → 说出结果"。

## 0. 校准:用户要的到底是什么(逐字)

原话——「不是只是有张嘴的聊天…我让 arslan 帮我看看桌面什么文件夹,聊天过程中它就能回应我在什么文档里看到内容并说出对应内容」。

拆开是四层,**只有 ②③ 是本 spec**:

| 层 | 是什么 | 现状 |
|---|---|---|
| ① 脑:边聊边真调工具 | list_dir→read_file→复述 | ✅ **已有**(P1 文件工具 + tool_loop + 逐 token 流) |
| ② 耳:ASR 听懂话 | 语音→user message | 🔴 缺 |
| ③ 声:TTS 念回答 | 回答→语音 | 🔴 缺 |
| ④ 脸:数字人口型 | LiveTalking 那层 | **明确不做**,见 §5 |

🔴 **最重要的判断:用户抱怨的"只有一张嘴",正是 LiveTalking 提供的全部(④)。它解决"嘴长什么样",用户要的是"聊天时手真在动"(①,已有)。所以本 spec 不碰视频合成,只把①接上耳朵和嘴。**

## 1. 现状亲核(不是缺口别重造)

| 能力 | 位置 | 事实 |
|---|---|---|
| 逐 token 流式 | `server/ws/protocol.py:32,41`(`stream_start`/`stream_chunk`) | ✅ 回答本来就是一段段吐的 |
| 工具调用帧 | tool_loop 发 `tool_call`/`tool_result` | ✅ **这是语音界面的金矿**:查文件那几秒可以念"我看一下桌面…",别家做不到的诚实反馈 |
| macOS 原生框架先例 | `ocr_vision.py`(Vision OCR,按需、模块级 import 在平台闸内) | ✅ **同款路子**:ASR 用 `SFSpeechRecognizer`、TTS 用 `AVSpeechSynthesizer`,零下载零依赖,非 darwin 优雅降级 |
| 端上 ASR 经验 | Cairn 项目(sherpa-onnx SenseVoice) | ⚠️ **iOS 的经验搬不动 macOS**:那是 sherpa-onnx + 239MB 权重 + ODR;macOS 有系统 `Speech.framework`,不该背一个 239MB 模型 |

## 2. 交付物(分两阶,各自能单独发)

### V1 — 声(TTS)🟢 **已实现(2026-08-31,#71)**
🔴 **架构更正(实现时亲核推翻本 spec 原方案)**:不是 sidecar 里的 `AVSpeechSynthesizer`,是**前端 Web Speech `window.speechSynthesis`**。理由:webview 本来就有、**零 entitlement**、缺了就静默降级——比走 sidecar/原生桥简单一个量级。`lib/speech.ts` 一个纯分句器(可测) + 一层能力守卫的合成 wrapper;`voiceOutputEnabled` 默认关。
- 回复流**逐句念**(攒到句子边界才合成),语言跟随 app 语言设置。
- 🔴 **mutation 逼出两件事**:①off-by-one 边界不是失败是**挂死**(零步进在 UI 线程无限循环)⇒ 加进度守卫;②`say()` 的 enabled 检查是**死代码**(feed/end 已拦)⇒ 删。
- 🔴 **工具停顿念过场("我查一下…")= 未做**,列为 follow-up(§1 说的金矿,但 V1 先只念答案)。
- 🔴 **未验**:打包 WKWebView 是否暴露 `speechSynthesis`(Chromium in-app 浏览器有,但那不是出货 webview——和 TCC 实证要 `open` 真启动同理);真实端到端流(provider 当时是坏的)。

### V2 — 耳(ASR),骑现有聊天框
- **`SFSpeechRecognizer`**(macOS 原生):按住说话 / 说完静默即停 → 转写成一条 user message → **后面整条工具链原封不动**。
- 🔴 **不引 sherpa-onnx、不下 SenseVoice**:那是 iOS 的账。macOS 用系统框架,和 OCR 用 Vision 同理。
- 权限:`SFSpeechRecognizer` 首用触发系统麦克风 + 语音识别授权框(OS 出面,一次性,可撤销)。**这条打包环境未验(见 §6)**。

## 3. 安全立场(逐条)

1. **语音只换输入方式,不换权限模型。** 说"看看我桌面"和打字"看看我桌面"走**完全相同**的工具闸——语音不是绕过任何确认的旁路。写死。
2. **① 的执行面闸一个不动**:workspace 写照样 session 授权卡,run_command 照样逐条。语音里这些确认怎么呈现(念出来?还是必须看屏点?)是 §4 裁决点。
3. **ASR/TTS 都走系统框架**:不新增可下载权重,不新增网络出口(系统 ASR 可选云端识别——**必须关掉,强制 on-device**,否则用户的话出网了)。
4. **依赖「默认可读」spec**:"看看我桌面"要完整,需要那份 spec 的绿环;否则语音里问桌面,答案仍是"没配 workspace"。两份 spec 顺序相关,不合并。

## 4. 裁决点(开工前请拍)

1. **顺序**:先 V1 声(零风险、当天可发)还是先 V2 耳(体感更强、但权限面更大)?我倾向 **V1 先**。
2. **执行面确认在语音里怎么办**:删文件这种红环,语音说"删掉 X"时——(a) Arslan 念"这会删掉 X,确认吗?"等你再说"确认";还是(b) 危险动作强制回到屏幕点卡,语音不接管确认?我强烈倾向 **(b)**——语音确认破坏性动作太容易误触("确认"是高频词)。
3. **打断(barge-in)**:念到一半你开口,要不要立刻停念转听?Cairn 踩过这个坑(扬声器漏音→回声→自问自答),macOS 上要不要做取决于扬声器/耳机场景。我倾向 **V1 先不做,V2 一起评估**。

## 5. 不做面(明说)

- **④ 数字人视频 / LiveTalking**:要 N 卡、独立 Python 服务 + 预录素材、对"做任务"零贡献。若将来要,正确接法是**外部输出设备**(把回答文本推给一台跑 LiveTalking 的机器,不内置)。
- **声音克隆**(Cairn 的招牌)——那是日记 app 的疗愈需求,Arslan 是工具,不需要"你的声音"。
- **实时视频/摄像头**。
- **端上大模型权重**(sherpa/SenseVoice)——系统框架够用。

## 6. 尚无证据、未声称已验

- 本 spec 零代码。§1 现状为 2026-08-24 亲核 main `1b2af7c2`。
- 🟢 **文件夹 TCC 已实证(2026-08-31,[[arslan-tcc-packaged-probe]])**:非沙箱 GUI app 读 Desktop/Documents/Downloads 零弹框直接放行——所以"看看我桌面"这条不卡在 TCC 上(卡在「默认可读」spec 的环模型上)。
- 🔴 **但麦克风/语音识别是另一码事,仍未验**:文件夹不门控 ≠ 麦克风不门控。`SFSpeechRecognizer` 首用**会**弹系统授权框,且**缺 usage 串会直接崩**(不像文件夹可省)。当前 `entitlements.plist` 无 `NSMicrophoneUsageDescription`/`NSSpeechRecognitionUsageDescription`。**V2 开工第一件事:单独打包实测麦克风授权**——这次的文件夹实证不覆盖它。
- 强制 on-device ASR 的 API 存在性(`requiresOnDeviceRecognition`)对当前 macOS 版本未逐一核。

关联:[[cairn-project]](iOS 端 ASR 经验的边界)、[[arslan-capability-fitness-audit-brief]]、`2026-08-24-default-read-surface.md`(依赖它)。

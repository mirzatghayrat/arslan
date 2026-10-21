# D9 附件被截断时告诉模型；上限从 12,000 字调到 40,000 字

| 项 | 内容 |
|---|---|
| 道 | ③Hands（⓪Plan 2026-10-21 分；由 ②Main 审） |
| 版本 | v0.1.63 |
| 分级 | 应该（用户 2026-10-21 定「两条都做」） |
| 依赖 | — |
| 合并位置 | 不进 K 线严格链，什么时候合都行 |
| 推动的门槛 | 用户每天会碰到的：发一份长文件要摘要，Arslan 只读了开头，却当成全文回答 |
| 迁移号 | 无 |
| 来源 | ①iOS 转来的用户报告（TestFlight 1.0 (19) + Mac 0.1.62）：手机发 25 页 PDF 要摘要，摘要明显只看了开头；接着让它写成 notes.md，内容却是全的。⓪Plan 在 main `4f50f9f2` 上核过 |

## 发生了什么

- 手机和窗口加的附件，文字都经 `POST /api/v1/extract`（`server/api/extract.py`）取出来。这个接口只取文字、不存文件。
- `server/services/extract.py:98` 按 `settings.attach_extract_char_limit` 截断：默认 12,000 字（`server/config.py:91`；环境变量 `ARSLAN_ATTACH_CHAR_LIMIT`，`:176`）。接口返回 `truncated: true`。
- 两边的客户端都不管这个标记：
  - Bridge（`desktop/bridge/Sources/BridgeCore/ConversationLinks.swift:255-263`）把文字放进 `attached_context`；它自己的上限很大（单个文件 400,000 字节，`:50`），卡住的是服务端的 12,000；
  - 网页（`web/src/components/ComposerAttach.tsx`）也一样。
- `server/orchestrator/arslan.py:366-367` 把它拼成「[Attached material]」交给模型，没有任何截断说明。模型以为前 12,000 字就是全文。
- 手机的原件其实已经存了（`/api/v1/phone/inbox` → `<工作文件夹>/Inbox/iPhone/<日期>/<文件名>`，`server/api/phone.py:235-237`）。Bridge 也在消息里写了一行「Attached from iPhone: 名字 → 路径」（`ConversationLinks.swift:330`）。所以写 notes.md 时，模型自己用文件工具打开原件，读到了全文。
- 附件文字只放进这一轮的请求，不存进对话历史（`arslan.py` 存的是 `persisted_user_text(user_message, images)`，不含附件文字）。所以调高上限，只多花这一轮的钱。

## 改哪些文件（只改服务端，不改 Bridge）

1. **截断时说明：** `server/services/extract.py`，截断的那一支，在文字末尾加一行，例如：
   > [Only the first 40,000 of N characters of this file are included. If the message says where the file was saved, read the rest from there with read_file; otherwise tell the user that only the beginning was read.]
   - N 是全文的字数；没截断就不加。
   - 手机发来的文件，消息里已经有存放路径；窗口加的附件没存原件，模型要明说只读了开头。
2. **上限调到 40,000 字：** `server/config.py:91` 的默认值和 `:176` 的环境变量默认值。
3. 测试：新加一个测试文件。

## 不许碰

- Bridge 的文件（`desktop/bridge/**`）和帧格式：消息里已经有路径，不用改。
- `/extract` 不存文件这一点不变：窗口的附件照旧不落盘。
- 图片的处理不变。

## 验收

- **测试：**
  - 超过 40,000 字的文件：返回的文字是前 40,000 字，加上那一行说明，里面写对了全文字数；
  - 不到 40,000 字的文件：没有那一行；
  - `truncated` 标记照旧；
  - 默认上限是 40,000，环境变量照旧能改；
  - mutation：去掉那一行，第一条测试要红。
- **手动（M3 加一条）：** 从手机发一份 25 页左右的 PDF 要摘要，摘要覆盖到全文，或者明说只读了前面一部分、再去读原件。
- 完成证据四项（`docs/sessions.md` §8）。

## 量级

产品代码约 +15 行，加测试。

## 风险与回退

- **风险：** 40,000 字的中文大约是 40,000 token，这一轮的请求会变大。K4a 的美元和 token 上限照管；附件文字不进历史，所以只影响这一轮。
- **回退：** revert；或者用环境变量把上限调回 12,000。

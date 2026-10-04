# Arslan Privacy Policy / Arslan 隐私政策

> To be published at https://aralem.dev/arslan/privacy/ (English first, Chinese below). Last updated: 2026-10-05.

## English

**In short: Arslan has no servers, and we collect no data.** Your iPhone talks only to your own Mac, through your own iCloud, end-to-end encrypted.

This policy covers **Arslan for iPhone** (the App Store app) and how it works with **Arslan for Mac** (free and open source, from aralem.dev).

### What we collect
Nothing. The iPhone app has no analytics, no tracking, no advertising and no account. We, the developer, never receive your messages, files, tasks or any information about how you use the app.

### How your messages travel
When you send a message, a task or an approval from your iPhone, it is encrypted on your iPhone and saved as a record in **your own iCloud private database** (Apple CloudKit), under your Apple ID. Arslan for Mac, signed in to the same Apple ID, reads and decrypts it. Replies travel back the same way. Each record is deleted from your iCloud once the other device confirms it has received it. The encryption keys are created when you pair your devices and stay in the keychains of your iPhone and your Mac, so neither Apple nor we can read the contents. Apple stores the encrypted records for you under Apple's privacy policy.

### AI processing happens on your Mac
Arslan for Mac runs the AI agent on your Mac. To answer you, it sends your requests to the AI model service **you** chose in its settings, with **your own** API key. That service processes them under its own terms and privacy policy. The iPhone app never contacts an AI service itself. Before your first message the app explains this and asks for your agreement; nothing is sent before you agree, and you can withdraw your agreement any time in the app's Settings › Privacy.

### Permissions and on-device features
- **Camera**: only to scan the pairing code shown on your Mac. Images are not stored or sent.
- **Microphone and speech recognition**: to turn your voice into the text of a message, in the app's language. Recognition runs on your iPhone; audio is not stored or sent.
- **Face ID or Touch ID**: to confirm an approval. iOS handles it; the app only learns whether it succeeded.
- **Notifications**: to tell you when your Mac needs an approval or has finished a task. Notification previews are decrypted on your iPhone, and you can turn previews off in the app's settings.

### What stays on your iPhone
The pairing keys (in the iOS keychain), an encrypted local record of recent messages and tasks so the app can show them when you are offline, and your settings. Unpairing removes the pairing keys and the local record. If you delete the app without unpairing first, iOS may keep the pairing keys in the keychain; removing the phone on your Mac ends that pairing for good.

### Sharing with others
We do not share any data with anyone. The AI model service is one you choose and contract with yourself, on your Mac; your Mac sends it your requests under that service's terms.

### Keeping and deleting data
Records in your iCloud are deleted once they have been delivered, and Arslan for Mac deletes anything left over after 7 days (for example, messages for a phone that stayed switched off). You can remove a paired phone at any time on your Mac (Settings › iPhone) or on your iPhone (Settings › Unpair). You can also delete the app's data from your iCloud in iOS Settings › your name › iCloud.

### Children
Arslan is not directed to children.

### Changes
If this policy changes, we will update this page and the date above.

### Contact
support@aralem.dev

---

## 中文

**简单说：Arslan 没有服务器，我们不收集任何数据。** 你的 iPhone 只和你自己的 Mac 通信，经由你自己的 iCloud，端到端加密。

本政策适用于 **Arslan iPhone 版**（App Store 上的 App），以及它与 **Arslan Mac 版**（免费开源，从 aralem.dev 下载）配合使用的方式。

### 我们收集什么
什么都不收集。iPhone 版没有统计分析、没有跟踪、没有广告，也没有账号。开发者不会收到你的消息、文件、任务，也不会收到任何关于你如何使用这个 App 的信息。

### 消息怎么传
你在 iPhone 上发出的消息、任务或批准，会先在 iPhone 上加密，再作为一条记录存进**你自己的 iCloud 私有数据库**（Apple CloudKit），归属于你的 Apple ID。登录同一个 Apple ID 的 Arslan Mac 版读取并解密这条记录。回复按同样的路径传回来。每条记录在对方设备确认收到后，就会从你的 iCloud 里删除。加密密钥在你配对两台设备时生成，只保存在你的 iPhone 和 Mac 的钥匙串里，所以苹果和我们都读不到内容。苹果依照其隐私政策替你保存这些加密后的记录。

### AI 处理发生在你的 Mac 上
AI 智能体运行在你的 Mac 上。为了回答你，Arslan Mac 版会把你的请求发给**你自己**在设置里选择的 AI 模型服务，使用**你自己**的 API key。该服务依照它自己的条款和隐私政策处理这些请求。iPhone 版本身从不连接任何 AI 服务。在你发出第一条消息之前，App 会说明这一点并征求你的同意；你同意之前什么都不会发出，之后也可以随时在 App 的“设置 › 隐私”里撤回同意。

### 权限与本机功能
- **相机**：只用来扫描 Mac 上显示的配对码。图像不保存，也不发送。
- **麦克风与语音识别**：把你说的话转成消息文字，识别语言跟随 App 的语言。识别在 iPhone 本机完成；音频不保存，也不发送。
- **面容 ID 或触控 ID**：用来确认批准。由 iOS 处理，App 只知道验证是否通过。
- **通知**：在 Mac 需要你批准、或任务做完时提醒你。通知预览在 iPhone 上解密，你可以在 App 设置里关闭预览。

### 留在 iPhone 上的数据
配对密钥（保存在 iOS 钥匙串里）、一份加密的近期消息和任务记录（方便离线时显示），以及你的设置。解除配对会移除配对密钥和本机记录。如果没有先解除配对就删除 App，iOS 可能仍在钥匙串里保留配对密钥；在 Mac 上移除这台手机，就能彻底结束这次配对。

### 与他人共享
我们不与任何人共享任何数据。AI 模型服务由你自己在 Mac 上选择并签约；你的 Mac 依照该服务的条款把请求发给它。

### 保留与删除
你 iCloud 里的记录在送达后即被删除；没能送达的（比如发给一台一直关机的手机），Arslan Mac 版会在 7 天后删除。你可以随时在 Mac 上（设置 › iPhone）或 iPhone 上（设置 › 解除配对）移除已配对的手机，也可以在 iOS 的 设置 › 你的名字 › iCloud 里删除这个 App 在 iCloud 中的数据。

### 儿童
Arslan 不面向儿童。

### 变更
如果本政策有变化，我们会更新本页和上方的日期。

### 联系我们
support@aralem.dev

<div align="center">

<a href="https://aralem.dev/arslan/">
  <img src="docs/assets/readme/banner.jpg" alt="Arslan — 仕事をこなし、動く前に聞く。Mac のノッチにある Arslan Island が、ファイル移動の承認を待っている。" width="100%">
</a>

<br/><br/>

**あなたの Mac に住み、iPhone からも指示できるオープンソースの AI エージェント。**<br/>
**ターミナルを使い、アプリを操作し、あなたが話している間も作業を続けます。**<br/>
**あなたの名前で動くことは、すべて*あなたの*クリックを待ちます。**

<br/>

[![Release](https://img.shields.io/github/v/release/mirzatghayrat/arslan?style=flat-square&color=34d399&label=release)](https://github.com/mirzatghayrat/arslan/releases/latest)
[![License](https://img.shields.io/badge/license-Apache--2.0-4c72e0?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/macOS_11+-Apple_Silicon-111?style=flat-square)](README.md#status--honest-about-whats-proven)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-2ea44f?style=flat-square)](CONTRIBUTING.md)

<br/>

<a href="https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg"><img src="docs/assets/btn/ja-download.png" alt="macOS 版をダウンロード" height="28"></a>&nbsp;&nbsp;<a href="https://aralem.dev/arslan/"><img src="docs/assets/btn/ja-website.png" alt="ウェブサイト" height="28"></a>&nbsp;&nbsp;<a href="docs/QUICKSTART.md"><img src="docs/assets/btn/ja-quickstart.png" alt="クイックスタート" height="28"></a>&nbsp;&nbsp;<a href="SECURITY.md"><img src="docs/assets/btn/ja-security.png" alt="セキュリティ" height="28"></a>&nbsp;&nbsp;<a href="CONTRIBUTING.md"><img src="docs/assets/btn/ja-contributing.png" alt="コントリビュート" height="28"></a>

<a href="README.md"><img src="docs/assets/btn/lang-en.png" alt="English" height="22"></a>&nbsp;<a href="README.zh-CN.md"><img src="docs/assets/btn/lang-zh.png" alt="简体中文" height="22"></a>&nbsp;<a href="README.de.md"><img src="docs/assets/btn/lang-de.png" alt="Deutsch" height="22"></a>&nbsp;<img src="docs/assets/btn/lang-ja-on.png" alt="日本語" height="22">&nbsp;<a href="README.es.md"><img src="docs/assets/btn/lang-es.png" alt="Español" height="22"></a>&nbsp;<a href="README.tr.md"><img src="docs/assets/btn/lang-tr.png" alt="Türkçe" height="22"></a>

</div>

---

<div align="center">
  <img src="docs/assets/readme/island.gif" alt="Arslan — 仕事をこなし、動く前に聞く。Mac のノッチにある Arslan Island が、ファイル移動の承認を待っている。" width="760">
  <br/>
  <sub>ノッチに表示されるバックグラウンドジョブ：作業し、ファイルを動かす前に<b>止まって確認</b>し、終わったら分かったことを知らせます。</sub>
</div>

## こんなふうに頼めます

> *“ダウンロードにある今年の請求書をひとつのフォルダにまとめて、抜けている月を教えて。”*<br/>
> *“ダウンロードに重複ファイルはいくつある？コピーはゴミ箱へ、いちばん新しいものは残して。”*<br/>
> *“sales_q3.csv をグラフ付きの 1 ページのレポートにして。”*<br/>
> *“メモに、この会議の 3 つのポイントを書いたメモを作って。”*<br/>
> *“毎朝 9 時にこのページを見て、価格が変わっていたら教えて。”*

作業中も会話を続けられます。削除・送信・インストール・他のアプリの操作は、Mac でも iPhone でも**必ず先に確認します**。

## 1 分で始める

1. **[macOS 版 Arslan をダウンロード](https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg)**（Apple Silicon、macOS 11+）— 署名・公証済み、自動アップデート。
2. **アプリケーション** にドラッグして開く。
3. 設定でモデルの API キーを貼り付ける — OpenAI、Anthropic、Gemini、DeepSeek、Qwen、Kimi、OpenRouter など — または **Ollama** でローカルモデルにつなぐ。

それだけです。アカウント登録も、Arslan のサーバーもありません。

## 0.1.53 の新機能 — Mac アプリを操作する Hands

Arslan は小さなヘルパー **Arslan Hands** を通じて、Mac のアプリ（メモ、メール、Pages など）を読み、操作できるようになりました。ウインドウはアクセシビリティツリーとして読み（スクリーンショットは使いません）、操作はバックグラウンドで行います。マウス、キーボード、最前面のウインドウはあなたのままです。アプリを見るときは会話ごと・アプリごとに 1 回確認し、操作はバックグラウンド作業の中だけでアプリごとに 1 回確認します。削除・送信・支払い・購入・送金・提出のボタンは毎回確認します。**Arslan for iPhone** の Mac 側も入り（設定 › iPhone）、白黒のアイコンが標準になりました。 [リリースノート全文 →](https://github.com/mirzatghayrat/arslan/releases/tag/v0.1.53)

<div align="center">
  <img src="docs/assets/readme/devices.jpg" alt="Mac の Arslan がバックグラウンドで請求書を集めている様子と、承認待ちを表示する iPhone の Arslan" width="100%">
</div>

<p align="center"><sub>Mac：0.1.52 のローンチ映像より。UI はソースから再構成、シナリオは演出です。iPhone：実際の画面収録。 <a href="https://aralem.dev/arslan/#film">▶ システム全体を 60 秒で</a></sub></p>

## Arslan を選ぶ理由

| | |
|---|---|
| **ひとつのループ、すべての操作の前にゲート** | メッセージはネイティブなツール呼び出しループに入ります。モデルは提案するだけで、各シェルコマンドの実行前に、固定のポリシー関数（別のモデルではありません）が **run**・**ask**・**forbid** を答えます。結果は信頼できないデータとして包まれて戻るので、ウェブページに隠された指示は読まれるだけで、従われません。 |
| **話している間も作業は続く** | 長い作業はバックグラウンドジョブになり、そのターンは終わります。ジョブの結末は **done**・**partial**・**blocked**・**stopped** のいずれかで、黙って諦めることはありません。スケジュールは最短 15 分間隔（最大 10 件）で、Mac がスリープ中に逃した分は再実行しません。 |
| **状態はノッチに** | **Arslan Island** が今やっていることを示し、必要なときに尋ね、終わったら知らせます。メニューバー、プッシュトゥトーク、実行中のものを止める Stop ボタンも。 |
| **Hands — 勝手にではなく、尋ねてから** | Arslan Hands による Mac アプリ、Arslan 自身のブラウザ、ショートカット、AppleScript。パスワード欄には決して入力せず、キーチェーンアクセス、パスワードマネージャ、システム設定、macOS のセキュリティ確認、通知センター、そして自分自身には触れません。 |
| **ポケットの中の Mac** | Arslan for iPhone（App Store に近日公開）は**あなた自身のプライベート iCloud** を通じて Mac とエンドツーエンド暗号化で通信します。同じ承認カードが両方に表示され、先に答えた方が有効。300 秒応答がなければ拒否されます。 |
| **ローカルファースト、自分のキーで** | 記憶は Mac の SQLite に保存され、モデル提供元に届くのはあなたが送ったターンだけ（あなたのキーで）。**Arslan はサーバーを運用していません。** 一度訂正すれば、そのやり方を覚えます。取り消しも可能です。 |
| <img src="docs/assets/icons/shield-check.svg" width="16"> **認証情報はあなたのもの** | Arslan があなたのアカウントの認証情報を取得したり注入したりすることはありません。認証が必要なコネクタ（App Store Connect など）は、隔離された認証情報ブローカーが安全性の審査を通るまで無効です。詳しくは [W11](docs/companion/W11-security-boundary.md)。サンドボックス外での実行を許可したコマンドは、あなた自身の権限で動きます。 |

## ひとつのターンを最初から最後まで

<div align="center">
  <img src="docs/assets/readme/loop.jpg" alt="ループ：メッセージ、ループ、ポリシー、サンドボックス、結果 — 各ステップにそれを担うファイル" width="100%">
</div>

| ステップ | 何が起きるか | 実装箇所 |
|---|---|---|
| **メッセージ** | ウインドウ、iPhone、音声から — ひとつの会話、ひとつのループ | `server/orchestrator/arslan.py`, `server/services/phone_bridge.py` |
| **ループ** | ネイティブなツール呼び出し。計画はホストが保持し、途中で切れた返答は推測せず続きを書く。モデル呼び出しは 1 回 75 秒まで | `server/orchestrator/tool_loop.py` |
| **ポリシー** | `run` · `ask` · `forbid`。コマンド文字列の純関数 | `server/services/terminal_policy.py`（破壊的コマンドの検出は Hermes Agent より、MIT） |
| **サンドボックス** | macOS seatbelt：コマンドが書けるのは作業フォルダ、一時領域、キャッシュのみ。SSH 鍵、キーチェーン、Arslan のデータは閉じたまま。モデルのキーはコマンドに渡らない。ツール呼び出しは 1 回 20 秒まで | `server/services/command_sandbox.py`, `terminal_exec.py` |
| **結果** | 信頼できないデータとして包み、確認してからあなたへ。実行していない作業の報告は決定的なガードが止める | `server/orchestrator/untrusted.py`, `promise_guard.py` |

## ゲート

<div align="center">
  <img src="docs/assets/readme/gate.jpg" alt="プロジェクトサイトのゲート：コマンドを入力すると Arslan の実際の判定が表示される — キーチェーンのパスワード読み出しは forbid" width="100%">
</div>

| 判定 | いつ | 例（すべて `terminal_policy.assess()` の実際の出力） |
|---|---|---|
| **run** | 読み取り、一覧、変換、ビルド、ページ取得 | `ls -la ~/Downloads` · `ffmpeg -i talk.mov talk.mp4` · `npm run build` · `curl -s https://example.com` |
| **ask** | 破壊的、またはあなたの名前で外部に作用する | `rm -rf build/` · `git push --force` · `curl … \| sh` · `osascript …` · `brew install jq` · `mail -s …` · `scp … mac-mini:` |
| **forbid** | 「今後は確認しない」にしても不可 | `security find-generic-password … -w` · `cat ~/.arslan/secret_key` · `rm -rf ~` · `sudo …` · `shutdown` |

「今後は確認しない」はコマンドの種類ごとに記憶され、設定 › 詳細 に一覧されます。forbid のルールは記憶できません。ゲートはミスや紛れ込んだ指示を防ぐもので、檻ではありません。許可したコマンドはあなたの権限で実行されます。[プロジェクトサイト](https://aralem.dev/arslan/#gate)で 64 個のコマンドを試せます。

## Hands、バックグラウンド作業、iPhone

<div align="center">
  <img src="docs/assets/readme/hands.jpg" alt="Hands：Arslan Hands による Mac アプリ、ブラウザ、ショートカット、AppleScript。見えて止められる。決して触れないアプリ" width="100%">
</div>

<div align="center">
  <img src="docs/assets/readme/iphone.jpg" alt="Mac と iPhone：プライベート iCloud 経由のエンドツーエンド暗号化（X25519、HKDF-SHA256、ChaCha20-Poly1305、Ed25519）、先に答えた方が有効、Island の表情" width="100%">
</div>

iPhone との接続に Arslan のサーバーや中継はありません。メッセージはあなたのプライベート iCloud データベース内の CloudKit ゾーンを通ります — X25519 鍵合意、HKDF-SHA256、ChaCha20-Poly1305、Ed25519 署名。配信済みのメッセージは削除され、残ったものは 7 日を過ぎると Arslan for Mac が削除します。Mac は起動中かつオンラインのとき、およそ 1 日 1 回確認します（オフラインの間は復帰後に）。

## プライバシー

<div align="center">
  <img src="docs/assets/readme/privacy.jpg" alt="誰が何を見るか：この Mac はすべて、モデル提供元は送ったターン、iCloud は暗号文とルーティング、Arslan のサーバーは何も（存在しないので）" width="100%">
</div>

## インストール

ソースや Docker から動かす場合（コントリビューター・セルフホスト）：**[docs/QUICKSTART.md](docs/QUICKSTART.md)** を参照。

画像やスキャン PDF の文字認識、セキュリティの詳細、環境変数、データのバックアップは[英語版 README](README.md#install) をご覧ください（英語版が正です）。

## 現状 — 確かめたことだけ

- **Pre-v1。** 当面は Apple Silicon の macOS 11+ のみ。サンドボックスは macOS seatbelt です。他のプラットフォームでは生成された Python は拒否され、シェルコマンドはサンドボックスなしで実行され、その旨が明示されます。
- **モデルのキーは自分で。** Arslan はあなたのアカウントで動き、費用はプロバイダから請求されます。ネイティブなツール呼び出しは OpenAI 互換、Anthropic、Gemini の経路で実装・プロトコル検証済みですが、すべてのモデルやエンドポイントを実地で認定したわけではありません。
- **Hands が見えるのは現在のデスクトップのウインドウだけ**です。別の操作スペースやフルスクリーンアプリの裏にあるアプリは開いていない扱いになります。大きなウインドウ（メモが多いメモアプリなど）は読むのに 10〜20 秒かかります。
- **Arslan for iPhone は App Store に近日公開。** Mac 側は 0.1.53 に入っています。
- **自分のスケジュールでお金を使う機能は出荷時オフ。** バックグラウンドの記憶整理は 設定 › 自動化 でオンにしたときだけモデルを呼びます。それでもプロバイダの請求画面で上限を設定してください。
- v1 までに API、スキーマ、既定値は変わる可能性があります。

## コミュニティ

- バグやアイデアは [Issue へ](https://github.com/mirzatghayrat/arslan/issues)。
- 手伝ってくれる方は [CONTRIBUTING.md](CONTRIBUTING.md) から。
- プロジェクトサイトは [`docs/index.html`](docs/index.html)（GitHub Pages）。この README の画像はそのサイトのキャプチャです。

## ライセンス

Apache-2.0。[LICENSE](LICENSE) と [NOTICE](NOTICE) を参照。Hermes Agent（MIT）や agent-desktop（Apache-2.0、Arslan Hands に無改変で同梱）を含むサードパーティの表記は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) にあります。アイコン：[Lucide](https://lucide.dev)（ISC）。

---

<div align="center">
<sub>Arslan が気に入ったら、<a href="https://github.com/mirzatghayrat/arslan/stargazers"><img src="docs/assets/icons/star.svg" width="12" height="12"> が他の人に見つけてもらう助けになります</a>。</sub>
</div>

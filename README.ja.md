<div align="center">

<a href="https://mirzatghayrat.github.io/arslan/">
  <img src="docs/assets/banner.jpg" alt="Arslan — 一つが多になる：macOS 向けのローカルファースト AI オーケストレーター" width="100%">
</a>

<br/><br/>

**あなたが話しかけるのは、ただひとつのホストエージェント。仕事は、あなた自身が育てたペルソナスポーン（spawn）へとルーティングされます。**<br/>
**プロンプトは自ら進化します — しかし、すべての変更はホールドアウト試験を通過しなければならず、**<br/>
**あなたが *Promote* を押すまで、何ひとつ反映されません。**

<br/>

[![License](https://img.shields.io/badge/license-Apache--2.0-4c72e0?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS--first-8a63f4?style=flat-square)](#ステータス--実証済みの範囲に正直に)
[![Python](https://img.shields.io/badge/python-3.11%2B-e6863c?style=flat-square)](pyproject.toml)
[![Frontend](https://img.shields.io/badge/react-19_%2B_TS_%2B_Vite-ff9ffc?style=flat-square)](web/)
[![Status](https://img.shields.io/badge/status-pre--v1-orange?style=flat-square)](#ステータス--実証済みの範囲に正直に)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-2ea44f?style=flat-square)](CONTRIBUTING.md)

<br/>

<a href="https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg"><img src="docs/assets/icons/badge-check.svg" width="14" height="14"> <b>macOS 版をダウンロード</b></a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="https://mirzatghayrat.github.io/arslan/"><img src="docs/assets/icons/globe.svg" width="14" height="14"> <b>ウェブサイト</b></a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="docs/QUICKSTART.md"><img src="docs/assets/icons/zap.svg" width="14" height="14"> <b>クイックスタート</b></a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="docs/ARCHITECTURE.md"><img src="docs/assets/icons/layers.svg" width="14" height="14"> <b>アーキテクチャ</b></a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="SECURITY.md"><img src="docs/assets/icons/shield.svg" width="14" height="14"> <b>セキュリティ</b></a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="CONTRIBUTING.md"><img src="docs/assets/icons/heart-handshake.svg" width="14" height="14"> <b>コントリビューション</b></a>

<sub><img src="docs/assets/icons/languages.svg" width="12" height="12">&nbsp;&nbsp;<a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.de.md">Deutsch</a> · <b>日本語</b> · <a href="README.es.md">Español</a> · <a href="README.tr.md">Türkçe</a></sub>

</div>

---

## ひとつのリクエストを、エンドツーエンドで

<div align="center">
  <img src="docs/assets/demo.gif" alt="出荷版 Arslan クライアントの 4 画面 — オーケストレーションスレッド、スポーン台帳、セカンドブレイン、診断" width="90%">
</div>

<p align="center"><em>尋ねるのは一度だけ。ホストエージェントがスポーンを選び、ジョブを分割し、生成されたコードをカーネルサンドボックスで実行して回答します — すべてが、ひとつのスレッドの中で完結します。</em></p>

<p align="center"><a href="docs/assets/arslan-clay-60s.mp4"><b>▶ 60 秒の映像を見る</b></a> — <a href="https://mirzatghayrat.github.io/arslan/">プロジェクトサイト</a>と同じクレイアニメーションの映像です。<br><sub>上の画面は出荷版クライアントそのもので、加工していません。ソース: <a href="video/">video/</a></sub></p>

**Arslan は、ローカルファーストのパーソナル AI オーケストレーターです。** あなた自身のマシン上で、あなた自身の LLM キーを使って動作し、**セーフ・バイ・デフォルトのカーネルサンドボックス**、**正直さを守るガードレール**、そして自由に閲覧・編集できる**可視化されたセカンドブレイン**を備えています。

## なぜ Arslan なのか

| | |
|---|---|
| <img src="docs/assets/icons/users.svg" width="20"><br/>**あなたが育てるペルソナチーム** | Arslan は玄関口。その奥で、あなたはスペシャリストスポーンのロースターを築き上げます — ツール、`SKILL.md` スキルパック、MCP サーバーを装備させ、二層構造の進化ループに時間をかけて磨き上げさせるのです。 |
| <img src="docs/assets/icons/graduation-cap.svg" width="20"><br/>**試験ゲート付きの自己進化** | スポーンのプロンプトは、自身の実行履歴から自らを書き換えます — そのうえで、ホールドアウトされた過去タスクにおいて、*すべての*評価軸で現行版に勝たなければなりません。合格すれば、読みやすい差分があなたの受信箱に届きます。**あなたが Promote を押すまで、何ひとつ有効になりません。** |
| <img src="docs/assets/icons/shield-check.svg" width="20"><br/>**免責ではなく、デフォルトで安全** | 生成されたコードは、カーネルが強制するサンドボックス（macOS seatbelt）の下、ネットワーク遮断で実行されます。クレデンシャル注入プロキシにより、サンドボックス内の git はネットワークと通信できますが、生のトークンは決してサンドボックスに入りません。カーネルサンドボックスが使えない環境では、**フェイルクローズ**します。 |
| <img src="docs/assets/icons/brain.svg" width="20"><br/>**時間軸を持つセカンドブレイン** | 資料、学び、プロフィール、そして `[[wiki-link]]` ノート — FTS5 と埋め込みのハイブリッド検索で引き出せ、Obsidian スタイルの力学モデルグラフとして閲覧できます。ビリーフ（信念）は時間を刻みます：それぞれがいつ真になり、何に置き換えられたのか。過去の任意の瞬間のグラフの姿を映し出すフィルターも備えています。 |
| <img src="docs/assets/icons/badge-check.svg" width="20"><br/>**設計から正直に** | ガードレールが「それはもうやりました」というでっち上げの主張を捕捉し、エージェントの自己報告を実際に実行された内容へと結び付けます。モデルが提案するメモリの削除・上書きは直接適用されることはなく、受信箱に届き、あなたが承認または却下します。 |
| <img src="docs/assets/icons/key-round.svg" width="20"><br/>**ローカルファースト、キーはあなたのもの** | あなたのマシン、あなたの API キー、複数プロバイダーをまたぐ品質優先ルーティング — そして間に挟まる**サードパーティのサーバーはゼロ**。6 言語の i18n と 6 種類のテーマパレット（ライト + ダーク）を同梱しています。 |

<sub>バックエンド：FastAPI + 非同期 SQLAlchemy/SQLite（`server/`）· フロントエンド：React 19 + TypeScript + Vite（`web/`）· トレーシング、LLM ジャッジによる評価、Grafana スタイルの診断ダッシュボードが進化ループに情報を供給します。</sub>

## 実際のクライアントの中身

<div align="center">
  <img src="docs/assets/screens.jpg" alt="出荷版 Arslan クライアントの 4 画面 — オーケストレーションスレッド、スポーン台帳、セカンドブレイン、診断" width="100%">
</div>

## リクエストはどう流れるか

<div align="center">
  <img src="docs/assets/fig01-request-path.png" alt="FIG. 01 — リクエストの経路：ひとつのスレッドで受け取り、ホストエージェントがスペシャリストスポーンへルーティング。その下にカーネルサンドボックスとセカンドブレイン" width="100%">
</div>

## 統制された自己進化

<div align="center">
  <img src="docs/assets/fig02-promotion-gate.png" alt="FIG. 02 — プロモーションゲート：書き換え、ホールドアウト試験、提案カード、あなたが Promote。不合格は破棄され、却下なら現行版が維持される" width="100%">
</div>

スポーンのプロンプトは自動的に書き換えられます — ただし、あなたの目に触れる前に、ホールドアウトされた過去タスクで自らを証明しなければなりません。どの評価軸でも、現行版より悪いスコアは許されません。不合格なら破棄され、表に出ることはありません。合格なら、読みやすい差分付きの提案カードが届きます。変更が反映されるのは、**あなたが Promote をクリックしたときだけ**です。

## 時間軸を持つセカンドブレイン

<div align="center">
  <img src="docs/assets/fig03-second-brain.png" alt="FIG. 03 — セカンドブレイン：メモリは自動的に形成され、スポーンはハイブリッド検索で読み取り、モデルによる編集はあなたの受信箱を経由し、すべてのビリーフが時間を刻む" width="100%">
</div>

メモリはひとりでに形成されます — ルーターが抽出した事実と、セッション終了時の蒸留によって。そしてスポーンは、FTS5 と埋め込みのハイブリッド検索でそれを読み返します。すべてのビリーフは、いつ有効になり、何に置き換えられたのかを記録しているので、Obsidian スタイルのグラフを過去の任意の瞬間までスクラブできます。モデルがメモリの編集や削除を望んだときは、その提案がまずあなたの受信箱に届きます — **何ひとつ黙って上書きされることはありません**。

## インストール

**Arslan はデスクトップアプリで使うのが正解です** — 署名・公証済みで、自動的に最新に保たれます:

<p><a href="https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg"><b>⬇ macOS 版 Arslan をダウンロード</b></a>(Apple Silicon)— DMG を開き、Arslan を<b>アプリケーション</b>フォルダへドラッグしてください。</p>

初回起動時に Settings でモデルの API キーを追加すれば準備完了です。

ソースからの実行や Docker(コントリビューター / セルフホスト向け):**[docs/QUICKSTART.md](docs/QUICKSTART.md)** を参照してください。

## セキュリティ体制

<div align="center">
  <img src="docs/assets/safety.jpg" alt="安全性は免責ではなく組み込み — カーネルサンドボックス、クレデンシャル注入プロキシ、ローカルファーストの BYOK" width="100%">
</div>

Arslan は**デフォルトで安全**です：

- **デフォルトでは localhost のみ。** 開発環境 + localhost は、ローカルでの利便性のために意図的に認証なしで動作します。クロスサイトのドライブバイリクエストは TrustedHost + CORS + WebSocket-Origin チェックでブロックされ、非 localhost / 本番デプロイでは以下の許可リストの設定が必須です。
- **トークンは必要な場面で必ず。** `prod`、パッケージ版ビルド、非ループバックのバインドではベアラートークンが必須です — 自動生成・永続化され、Settings からローテーションできるので、締め出される心配はありません。
- **シークレットは公開キーを拒否します。** BYOK シークレットは、インストールごとのソルトの上で `ARSLAN_SECRET_KEY` から PBKDF2-HMAC-SHA256 により導出されたキーを使い、Fernet で暗号化されます。組み込みの公開開発キーの下では、アプリはシークレットの書き込み自体を拒否します。
- **サンドボックスはフェイルクローズ。** 生成されたコードは macOS seatbelt の下、ネットワーク遮断で実行されます。カーネルサンドボックスが使えない環境では、黙ってサンドボックスなしで実行するのではなく、フェイルクローズします。

**トークンとホスト / オリジンの許可リストなしに、信頼できないネットワークへサーバーを公開しないでください。** 完全な脅威モデルと報告ポリシー：[SECURITY.md](SECURITY.md)。

<details>
<summary><b>環境変数（完全リファレンス）</b></summary>
<br/>

| 環境変数 | デフォルト | 用途 |
| --- | --- | --- |
| `ARSLAN_SECRET_KEY` | *（開発環境では自動生成）* | 保存された BYOK シークレットを暗号化する Fernet キーの導出元。開発環境：未設定なら初回起動時に自動生成され、`~/.arslan/secret_key` へ永続化されて以降は再利用されます。明示的な値が常に優先されます（永続化されたファイルと不一致の場合は警告をログ出力）。`prod` では値の欠如は起動時致命エラーとなり、永続化された開発用ファイルは**決して**読み込まれません。 |
| `ARSLAN_SECRET_KEY_FILE` | `~/.arslan/secret_key` | 開発環境専用：自動生成されたシークレットの永続化先 — 意図的にデータディレクトリの**外**に置かれています（バックアップ = データディレクトリ **+** このファイル）。**空**に設定すると自動生成を完全に無効化します。`prod` では無視されます。サーバー設定を読み込む開発用エントリポイント（サーバー、マイグレーション CLI、診断）はいずれも初回使用時にこれを生成することがあり、生成時には必ず保存先を示す 1 行が出力されます。 |
| `ARSLAN_API_TOKEN` | *（空）* | API/WS のベアラートークン。**開発環境 + localhost で空 = 認証なし**（摩擦ゼロのローカル利用）。本番 / パッケージ版 / 非ループバックのバインドでは、初回起動時にトークンが自動生成されます（下記参照）。 |
| `ARSLAN_DATA_DIR` | プラットフォームのアプリデータディレクトリ | DB、ノート、シークレットの保存場所。未設定の場合 → macOS は `~/Library/Application Support/Arslan`、Linux は `~/.local/share/Arslan`、Windows は `%APPDATA%/Arslan`。**このディレクトリとあなたのシークレットがバックアップの単位です**（[データとバックアップ](#データとバックアップ)を参照）。 |
| `ARSLAN_ENV` | `dev` | `dev` または `prod`。`prod` はトークンを必須とし、デフォルトを堅牢化します。`prod` での `ARSLAN_SECRET_KEY` の欠如は起動時致命エラーです。 |
| `ARSLAN_ALLOWED_HOSTS` | localhost のみ | 非 localhost / 本番デプロイ向けの、カンマ区切りの TrustedHost 許可リスト。 |
| `ARSLAN_ALLOWED_ORIGINS` | localhost のみ | 非 localhost / 本番デプロイ向けの、カンマ区切りの CORS + WebSocket-Origin 許可リスト。 |
| `ARSLAN_ALLOW_INSECURE_SECRETS` | *（オフ）* | 開発環境専用の緊急脱出ハッチ：公開デフォルトキーの下でのシークレット書き込みを許可します。**本物のキーには絶対に使わないでください。** |
| `ARSLAN_ALLOW_UNSANDBOXED_PY` | *（オフ）* | 開発環境専用の緊急脱出ハッチ：サンドボックスが使えない環境で、生成された Python をサンドボックス**なし**で実行できるようにします。その場合、任意のコードがサーバーの権限とネットワークアクセスで実行され、実行は監査のため `sandboxed=false` としてマークされます。完全に信頼できるマシンでのみ有効化してください。 |

本番 / パッケージ版（`ARSLAN_PACKAGED=1`）/ 非ループバックのバインドでは、`ARSLAN_API_TOKEN` が空の場合、アプリは初回起動時にトークンを**自動生成**し、`<data_dir>/api_token`（所有者のみアクセス可）へ永続化し、起動時に一度だけ表示して、Settings から閲覧・リセットできるようにします。

</details>

<details>
<summary><b>データとバックアップ</b></summary>
<br/>

大切なものはすべて、ひとつのディレクトリに収まっています — DB、あなたのノート、暗号化されたシークレット。その場所は `ARSLAN_DATA_DIR`（未設定ならプラットフォームのアプリデータディレクトリ）から解決されます。**そのディレクトリこそがバックアップの単位です：** コピーすれば Arslan のバックアップになり、書き戻せば復元できます。`api_token` と `crypto_salt` の各ファイルも一緒に保管してください — 新方式（PBKDF2）で暗号化されたシークレットは `ARSLAN_SECRET_KEY` **と**インストールごとの `crypto_salt` から導出されるため、`crypto_salt` を失う（または不一致になる）と、正しい `ARSLAN_SECRET_KEY` があっても保存済みシークレットは復号できなくなります。

意図的な例外がひとつだけあります：シークレット自体は、そのディレクトリの**外**にあります。`ARSLAN_SECRET_KEY` を自分で設定していなければ、開発環境で自動生成された値は `~/.arslan/secret_key` にあります — つまり、コピーしたデータディレクトリだけでは保存済みプロバイダーキーを復号できません（錠前と箱は別々に旅をするのです）。したがって、完全なバックアップは**2 つの要素**で成り立ちます：データディレクトリ、**そして**シークレット（環境変数の値、またはそのファイル）です。

</details>

## ステータス — 実証済みの範囲に正直に

**Pre-v1 です。** 私たちは、誇大に売り込むよりも控えめに主張するほうを選びます：

- **macOS ファースト。** カーネルサンドボックスは macOS seatbelt のみで、他のプラットフォームではフェイルクローズします（Linux / Windows は、Tauri デスクトップアプリ経由で今後対応予定です）。
- **自己進化するエージェントチームは強化中です。** 二層構造の進化ループは動作していますが、完全に実証済みだとはまだ主張していません — 完成品ではなく、成熟途上のものとして扱ってください。
- **エージェント的なメモリの読み書きには、ネイティブなツールコール対応プロバイダーが必要です。** `recall`/`remember` ツールは、実際にツールコールを行うプロバイダー（例：DeepSeek）でのみ発火します。Anthropic の直接バックエンド経由では決してトリガーされません — その経路は意図的にテキスト入力 / テキスト出力であり、ツールスキーマがモデルに送られることはないためです。それでもメモリは、この機能とは独立して、どちらの場合でも自動的に形成されます（ルーターが抽出した事実 + セッション終了時の蒸留）。
- **お金を使う 2 つのバックグラウンドループは、無効の状態で出荷されます。** 自動進化とスリープタイムキュレーションは、それぞれ独自のスケジュールで LLM を呼び出すため、どちらもデフォルトでオフです — Settings でオンにします。動作する支出上限はまだありません：実行前の見積もりはコーパスの成長とともに増える既知の過大見積もりであり、それに対して何も強制されません。修正されるまでは、プロバイダーの請求ダッシュボードのハードリミットで支出を抑えてください。
- API、スキーマ、デフォルト値は v1 までに変更される可能性があります。

## コミュニティ

- <img src="docs/assets/icons/bug.svg" width="14" height="14"> バグを見つけた、またはアイデアがある？ [Issue を開いてください](https://github.com/mirzatghayrat/arslan/issues)。
- <img src="docs/assets/icons/heart-handshake.svg" width="14" height="14"> 手伝いたい？ まずは [CONTRIBUTING.md](CONTRIBUTING.md) からどうぞ。
- <img src="docs/assets/icons/globe.svg" width="14" height="14"> プロジェクトサイトは [`docs/index.html`](docs/index.html) にあります（GitHub Pages で配信）。この README のブループリント図は手描きの SVG です — ソースは [`docs/diagrams/`](docs/diagrams/) にあります。

## ライセンス

Apache-2.0。[LICENSE](LICENSE) と [NOTICE](NOTICE) をご覧ください。サードパーティ依存関係の通知は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) にあります。アイコン：[Lucide](https://lucide.dev)（ISC）。

---

<div align="center">
<sub>Arslan が心に響いたなら、<a href="https://github.com/mirzatghayrat/arslan/stargazers"><img src="docs/assets/icons/star.svg" width="12" height="12"> が他の人の目に留まる助けになります</a>。</sub>
</div>

# OpenRouter 一键登录 —— 任务书

**base**: `main = 4330a100` · **登记**: 用户 2026-08-12(排 ③ 后,吃它的基建)
**用户已裁决的形状**:首启向导加「用 OpenRouter 登录」;PKCE 走 ③ 的本地回环;
key 存现有 provider_config 加密路,`provider=openrouter`;`:free` 让零绑卡用户开箱能聊;
**充值在 OpenRouter 侧,我们不碰钱**。

## 0. 前置核实(2026-08-15)

| 事实 | 来源 |
|---|---|
| 官方 PKCE 流程:`https://openrouter.ai/auth?callback_url=…&code_challenge=…&code_challenge_method=S256` | openrouter.ai/docs(回源核过,非记忆) |
| 换 key:`POST https://openrouter.ai/api/v1/auth/keys` body `{code, code_verifier, code_challenge_method}` → 响应含 `key` | 同上 |
| **localhost 任意端口被明确支持**、**无需预注册应用** | 同上 —— ③ 的动态端口回环直接可用,零例外 |
| `openrouter` preset 已在:展开为 openai 兼容 + `https://openrouter.ai/api/v1`,默认模型 `anthropic/claude-sonnet-5` | `arslan/llm/presets.py` 亲核 |
| G1 后 openrouter 在 tool-transport SUPPORTED 表 | capability_fitness 亲核(#18 那轮) |
| 向导第 2 步 = BYOK(`addProviderConfig` 现成保存路) | `FirstRunWizard.tsx` 亲核 |

🔴 **这不是标准 OAuth**(无 client_id、无 token endpoint、无 DCR)⇒ ③ 的 SDK
`OAuthClientProvider` **不适用**。复用的是 ③ 的**基建**:回环捕获器、shell 浏览器门、
「URL 只走后端→响应→open_external」的来源规则。PKCE 的 verifier/challenge 生成是
stdlib 三行(secrets + hashlib + base64),不构成「手写认证协议」——被手写禁令挡的是
协议状态机,不是一次哈希。

## 1. 设计

### 1.1 后端 `server/services/openrouter_oauth.py`
- `start()`:起回环(③ 的 `catch_authorization_code`)→ 生成 verifier/challenge(S256)→
  拼授权 URL → 返回 `{auth_url}`;后台任务等 code。
- code 到手 → `POST /api/v1/auth/keys` **走 `net_pin.pinned_request`**(常量目的地,
  `allow_host=None`——搜索轮建的钉扎路,出站请求不再有裸 client)→ 拿 `key`。
- **建 provider_config**:`provider="openrouter"`,key 走现有加密存储
  (`add_config` 现成路,不新开)。若这是第一个配置,`add_config` 已有的 first⇒primary 逻辑生效。

### 1.2 `:free` 默认模型 —— 动态选,不写死
🔴 写死某个第三方模型 id 是**会腐烂的数据**。换 key 成功后 `GET /api/v1/models`(同样走钉扎),
选一个 `pricing.prompt == "0"` 的 `:free` 模型(偏好 deepseek 系);
**列表拿不到或没有免费模型 ⇒ 回退 preset 默认模型**,并在 status 里如实说
「已连接,但免费模型列表不可用,当前默认模型需要余额」——不许静默给一个会 402 的默认。

### 1.3 API(挂 settings router,`/api/v1` 前缀)
- `POST /settings/openrouter/oauth/start` → `{auth_url}`
- `GET /settings/openrouter/oauth/status` → `{state: idle|waiting|done|error, error, config_id?, model?}`
内存态流程表(同 ③ 端点的理由:waiting 绑着活的回环监听,不该跨重启假装还活着)。

### 1.4 前端:向导第 2 步 + Models 分区各一个入口
- 向导第 2 步顶部加「Sign in with OpenRouter」按钮(BYOK 表单保留在下方,"or" 分隔);
  点击 → start → `openExternal(auth_url)` → 轮询 → done ⇒ 向导完成。
- 六语文案;按钮态:idle / waiting(点阵复用 #24 的)/ error(展示 status.error)。

## 2. 不做
- 不碰钱、不展示余额、不引导充值(用户红线)。
- 不做 key 轮换/撤销 UI(OpenRouter 侧自己管)。
- 不动 preset 的默认模型(那是手填路径的默认;OAuth 路径单独选 free)。

## 3. 验收
| # | 判据 | mutation |
|---|---|---|
| 1 | auth URL 含 code_challenge + S256 + 回环 callback_url | 去掉 challenge ⇒ 红 |
| 2 | 换 key 请求走 pinned_request 且 allow_host=None | 裸 httpx ⇒ 红(源码断言缺席) |
| 3 | key 落库即密文(库行不含明文 key) | —— 性质断言 |
| 4 | 免费模型选择:有 free 选 free;列表失败回退 preset 默认且 status 如实说 | 静默回退 ⇒ 红 |
| 5 | 拒绝授权 ⇒ status=error 不挂起 | —— |
| 6 | 向导按钮:URL 只经 openExternal | window.open ⇒ 红 |
| 7 | 六语齐 | —— |

## 4. 尚无证据
- **对真 OpenRouter 的端到端**(真账号点授权)本轮代码无法自证——要你真机点一次。
  这正好也是 ③ 挂着的「真实 provider 锤回环」那条验收的一半。
- `:free` 模型今天存在明天可能下架;动态选择 + 如实回退就是为此设计的。

# SearXNG provider —— 让自建实例真的可用,且不为此打开一个 SSRF 洞

**base**: `main = d4dcc94a` · **前情**: `docs/specs/2026-08-07-search-capability.md`(§2.3 / §2.5 / 验收 #4 已批)

这轮不是白纸设计。上一轮那份 spec 已经把 SearXNG 的钉扎方向写完并经用户修正,
本份只补它没 settle 的三件(下面 §1)、并把 §2.5 那个**至今不存在**的共享 helper 真建出来。

---

## 0. 现状(2026-08-11 亲核,带 FILE:LINE)

| 事实 | 证据 |
|---|---|
| `requires_key` 契约已落地 | `server/registry/search_providers.py:37`(基类)、`:52` Tavily=True、`:92` DDG=False |
| DDG 零 key 兜底已出货 | v0.1.20,用户 2026-08-11 真机验证过「一个 key 都不填能出结果」 |
| **共享钉扎 helper 不存在** | `server/registry/` 下无 `pinned_http.py`;`net_pin` 仅被 `search_providers.py` 与 `executors.py` import |
| **两个 provider 仍是裸 client** | `search_providers.py:59`(Tavily)、`:111`(DDG)均 `httpx.AsyncClient(...)`,零钉扎 |
| `net_pin` 的 import 只是占位 | `search_providers.py:158` 注释原文:为将来的 SearXNG 预留 |
| settings 已有 `search_provider`(明文)/ `search_api_key`(密文) | `settings_service.py:20`、`:34` |
| **无 `search_base_url` 键** | 同上,两处均无 |

🔴 **上一轮 spec §0.5 预言的洞原样躺着**:今天目的地是硬编码常量所以风险有限,
**SearXNG 一落地,目的地就变成用户填的字符串**——那一刻这条裸路径就是洞。
⇒ **本轮第一步是建钉扎路径,不是写 provider。** 顺序反了,中间那段时间洞是真开着的。

---

## 1. 本轮新裁决(用户 2026-08-11)

| # | 问题 | 裁决 | 代价(明写) |
|---|---|---|---|
| ① | 结果怎么取 | **只用 JSON**(`/search?format=json`),失败给可操作报错 | 实例没开 `search.formats: json` 的用户要多改一行配置 |
| ② | 配了但挂了怎么办 | **硬失败,给准确原因,不回退 DDG** | 实例一挂,搜索就不能用 |
| ③ | 要不要测连接 | **做,且区分四种原因** | 多一个后端端点 + 一块 UI |

**② 的理由值得留档**(它推翻了「回退更稳健」这个显而易见的答案):
人自建 SearXNG 的主要动机是查询不出内网。挂了就改发 DDG,等于把他特意藏起来的查询送给第三方——
出处标注只能**事后**告知,查询已经出去了。可用性在这里要让位给它存在的理由。

---

## 2. 设计

### 2.1 共享钉扎 helper(上一轮 §2.5 的兑现)

新增 `server/registry/pinned_http.py`,把 `net_pin` 里已被 `_fetch_text` 验证过的那套
(resolve-once 钉扎、非公网拒绝、逐跳重钉、`follow_redirects=False` + 手写重定向循环、
`_MAX_REDIRECTS=5`)提成可复用入口:

```
async def pinned_get(url, *, headers=None, timeout=<沿用 net_pin 现值>, allow_host: str | None = None) -> httpx.Response
```

**约束**:`executors.py:24` 已 import `search_providers`,所以 `search_providers`
**不能**反向 import `executors`。`pinned_http` 只依赖 `net_pin`,两边都能 import,无环。

三个 provider(Tavily / DDG / SearXNG)全部改走它。Tavily 与 DDG 传 `allow_host=None`
——它们的目的地是硬编码常量,不需要也不应该拿到豁免。

### 2.2 私网豁免(安全核心)

上一轮已批的三条,原样执行:

1. 用户在 Settings 亲手填的 base host **豁免** `not ip.is_global`(否则 192.168.x / 100.64.x
   ——自建 SearXNG 最可能的两个位置——全被拒)。
2. 豁免**只对那一个 host**,由 Settings 里的字符串定义;**模型能控制的只有 query,不是目的地**。
3. **逐跳重定向仍校验**,任何跳到该 host 之外的一律拒绝。

🔴 **本轮追加一条实现约束**:豁免必须**以显式参数逐次传入**(`allow_host=`),
**不得**实现为全局标志、模块级状态或线程/上下文变量。
理由:`web_extract` 与 DDG 是模型可影响目的地的路径,任何形式的环境态豁免都会被它们静默继承。
这是「网络边界用允许清单不用黑名单」在调用面的同一条要求。

**豁免的判定必须是 host 相等,不是前缀/包含**。`allow_host="192.168.1.10"` 不得放行
`192.168.1.100`,也不得放行 `evil.com/?x=192.168.1.10`。归一化沿用 `net_pin._ascii_host`(:123)。

### 2.3 SearXNGProvider

- `requires_key = False`(它靠 `search_base_url`,不靠 key)。
- 请求 `{base}/search`,参数 `q=<query>`、`format=json`,走 `pinned_get(..., allow_host=<配置 host>)`。
- 解析 `results[]` 取 `title` / `url` / `content`,归一成现有 provider 的返回形状。
- **不做实例认证**(YAGNI:内网自建通常无认证)。要认证的实例本轮用不了,文档明写,不静默失败。

### 2.4 四种测连接结果

新增只读端点(照 `server/services/provider_health.py:52 probe()` 的现成范式),四个 verdict 互斥:

| verdict | 触发 | 用户该做什么 |
|---|---|---|
| `unreachable` | DNS / 拒连 / 超时 / 被钉扎规则拒 | 查地址、查实例是否在跑、查是否在本机可达的网段 |
| `not_searxng` | 连上了,但响应不是 SearXNG 的形状 | 这个地址上跑的是别的东西 |
| `json_disabled` | 是 SearXNG,但 `format=json` 不可用(HTML/403/404) | 去 `settings.yml` 的 `search.formats` 加上 `json` |
| `ok` | JSON 解析成功 | 可用(带本次拿到的结果条数) |

🔴 四种的修法完全不同,**合成一句「连接失败」等于没说**。`json_disabled` 是其中最常见的一种,
恰恰也是最容易被误读成「地址写错了」的一种。

**判定顺序写死(否则「不是 SearXNG 的形状」能被两种实现解释)**:

1. 传输层失败(DNS / 拒连 / 超时 / 被钉扎拒)⇒ `unreachable`。
2. 拿到响应,且能解析成含 `results` 键的 JSON(**空数组也算**)⇒ `ok`。
3. 拿到响应但不是上述 JSON ⇒ 在响应体里找 SearXNG 标识(生成器 meta / `searxng` 字样):
   找到 ⇒ `json_disabled`;找不到 ⇒ `not_searxng`。

🔴 **第 3 步是启发式,只用来选一句人话,永远不参与任何安全判定**——
钉扎与豁免在第 1 步之前就已决定。启发式猜错的最坏后果是给了条不够准的建议,
不是放行了一个不该放行的地址。这条边界必须在实现里以注释固定,否则将来有人会「顺手」拿它做判断。

### 2.5 Settings 面(`search_base_url`)

**存明文,不存密文**:它是内网地址不是凭据;加密会让测连接与排错都变难,且它本来就不是秘密。

🔴 **三处 lockstep**:`settings_service._PLAIN_KEYS` + **两个** pydantic schema。
`settings_service.py:22-27` 的注释记着案底:只注册一处,正是 `github_token`
「看起来能存、实际存不进」的成因。⇒ 配一条守卫断言三处一致。

KV 表存储(`Setting(key=, value=)`,`settings_service.py:98`),**不需要迁移**。

### 2.6 出处标注

沿用上一轮已出货的机制,SearXNG 的结果标 `searxng`(自建实例),与 `duckduckgo (best effort)` 并列。
这轮不新增机制,只接线。

---

## 3. 验收(mutation 为主 —— 每条都要先证明它能失败)

| # | 判据 | mutation(必须让它变红) |
|---|---|---|
| 1 | 豁免只对配置的那一个 host | 把豁免改成全局/无条件 ⇒ 红 |
| 2 | host 判定是相等不是前缀 | 改成 `startswith`/`in` ⇒ 红(`192.168.1.10` 不得放行 `192.168.1.100`) |
| 3 | 逐跳重定向仍校验,跳出 host 拒绝 | 去掉每跳重钉 ⇒ 红 |
| 4 | 硬失败不回退 | 加一条 DDG 回退 ⇒ 红 |
| 5 | 四种 verdict 互相区分 | 任意合并两种 ⇒ 红 |
| 6 | 模型 query 里的私网 URL 不影响目的地 | —— 正向断言,query 与目的地解耦 |
| 7 | 三处 lockstep | 从任一处删掉 `search_base_url` ⇒ 红 |
| 8 | Tavily/DDG 不携带豁免 | 给它们传一个非 None 的 `allow_host` ⇒ 红 |
| 9 | 回归:`requires_key=False` 的 provider 结构上可达 | 把 `if not key` 短路加回去 ⇒ 红(上一轮判据,防回潮) |

**判据 5 的形状要求**:四个 verdict 各自要有一个**只命中它**的 fixture。
一个能同时被两种解释的 fixture,谁也没证明(见 [[arslan-reaudit-own-conclusions]])。

**判据 6 的探针纪律**:先证明探针能失败——构造一个「目的地真的被 query 影响」的假实现,
断言测试在那种实现下变红,再断言真实现下是绿的。

---

## 4. 顺带销的两笔债(本轮范围内)

- **DDG 解析器 HTML 结构单测**:上一轮把解析脆性揽到自己身上时登记的,一直没写。
  测的是解析器对结构变化的行为,不是「今天能跑」。
- **`_last_health_ok` 字面量复查**:`server/services/provider_config_service.py:75`/`:79`,
  登记时只写了「待查」,本轮核清它是不是想要的语义。

---

## 5. 不做(明写,防止顺手扩范围)

- **不打包 SearXNG**(AGPL,见 [[arslan-license-verify-at-source]])。用户填自建实例地址不触发这条。
- **不做实例认证**(§2.3)。
- **不做搜索结果缓存**、不做跨 provider 结果合并/去重。
- **不改 `web_extract`**(它不走 provider 层)。
- **不动 `_WEB_TOOL_GUIDANCE` / `_CAPABILITY_SELF` 的提示词配比**——上一轮 §0.7 已单独立项。
  改配比会同时移动一堆既有行为,和本轮「让 provider 真的能用」互相污染,合起来就分不出谁修好了什么。

---

## 6. 已知不会被本轮证明的事(诚实边界)

- **没有真实自建 SearXNG 实例的端到端验证**。单元测试用本地 stub 服务器,证明的是我们这一侧的
  请求构造、钉扎判定与解析。真实例上的行为(版本差异、反代、限流)本轮不声称已验。
- 四个 verdict 的**文案**六语齐,但**非母语者校对**仍是既有挂账,不在本轮销。

关联:[[arslan-allowlist-not-blacklist]]、[[arslan-probe-must-match-consumer]]、
[[arslan-tests-must-discriminate]]、[[arslan-partial-fix-scope-disclosure]]。

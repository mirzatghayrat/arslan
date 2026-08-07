# spec ⓪ 解密三态 + 盐稳定性 —— 任务书

**状态**:🟢 **已批(用户 2026-08-08,「方向全批」)。开工顺序第一。**
**优先级**:插队最前(用户 2026-08-07 裁决)。它是 ① 的前置 —— 两者都改
`server/registry/executors.py` 的搜索错误路径,见 §6.1 接缝。

> **用户 2026-08-08 裁决原文(逐条批)**
> - 盐进数据库与密文同居 —— **批**(盐不是秘密,PBKDF2 盐可公开,同生死靠同址)
> - 恢复走「只读试解 → 报告 → 我们点头才 rekey」—— **批,一个字节都不许在点头前写**
> - `_FALLBACK_SALT` 只许读不许写 —— **批**
> - 病因诊断不用固定句 —— **批**,`en.json:463` 那句就是反面教材,它把盐的事故说成 secret 的事故
>
> **补充裁决(2026-08-08,拆掉我问错的那个二选一)**:
> 🔴 **解密已经成功的写是迁移,解密还没成功的写是赌博。**
> 迁移(当前钥匙能解开)**自动、不设人闸**,拦它会让 legacy 格式永生;
> 恢复(当前钥匙解不开 → 候选盐试解)**纯只读 + 报告 + 人闸**。详见 §3① 与 §2.2。
>
> **开工顺序(用户 2026-08-08)**:cryptography 升级 + 全量 → 盐进 DB + 三态 + 诊断;
> 验收带上三场景(换目录启动 / 缺环境变量启动 / 备份恢复到新机器,§4.1–4.3)。

**一句话**:今天存好的密钥可以在用户什么都没改的情况下变成「没设置」,而**盐能和密文分离**是
那件事的机制。本轮修的是机制,不是那一句错话。

---

## 0. 前置核实(2026-08-07 亲核 `5f2b083b`,带 FILE:LINE,不引用记忆)

### 0.1 四个消费者共用一条解密路,三种失败形状

| 消费者 | 解不开时 | 用户看到什么 |
|---|---|---|
| `server/services/settings_service.py:66-70` `_safe_decrypt`(覆盖 `_SECRET_KEYS` 三个键) | `logger.warning` + 返回 `""` | **读作「从未设置」**;搜索路径 `executors.py:231 if not key` 报 `"web search is not configured (no API key set)"` |
| `server/services/provider_config_service.py:14-18` `_safe` | 返回 `""` | 但**旁边有** `_key_status`(§0.2),UI 说了实话 —— 只是说错了病因 |
| `server/services/mcp_service.py:30-33` `_to_dict` | 返回 `{}` | MCP server **不带凭据启动**,报的是那个 server 自己的 401 |
| `server/mcp/discovery.py:59-62` `runtime_dict` | 返回 `{}` | 发现路径同上 |

`settings_service.py:27` `_SECRET_KEYS = ("llm_api_key", "search_api_key", "github_token")`
—— 三个键**共用** `:171-174 get_decrypted`,所以「只修 search」在结构上不存在。

🔴 四个消费者里**三个静默**,第四个说话但说错(下一节)。

### 0.2 🔴 树上已有一份「诚实三态」参考实现 —— 而它那一句话把病因指错了

`provider_config_service.py:21-36 _key_status()` 已经返回 `'unset' | 'set' | 'undecryptable'`,
`:50-57 _to_public` 把它作为 `key_status` 发给前端,`:64-69` 还有
`count_undecryptable_keys()`;前端 `web/src/components/settings/ProviderDetailPane.tsx:315-331`
按它切换 placeholder 并渲染一条 `text-danger` 说明,`data-testid=provider-config-key-undecryptable-N`,
测试在 `web/src/__tests__/provider-key-input.test.tsx:80-99`,六语文案在
`web/src/locales/*.json:461-463`。

**⇒ 三态的词汇、API 形状、UI 图元、测试、文案全都已经存在。** 本轮不是发明,是**把它推广**。

🔴 但那条文案是:

> `en.json:463` "The stored key can't be decrypted because **ARSLAN_SECRET_KEY changed** since it was saved. Re-enter it to restore access."

**在真实事故里 `ARSLAN_SECRET_KEY` 没有变 —— 变的是盐。**
这句话把人送去检查/重设 secret key(那半是好的),而真正丢的那半它一个字都没提。
用户那条「谎报病因比不报还坏 —— 用户会去解错的题」在这里有一个**已经出货的实例**:
一句具体、可信、可执行、并且错的诊断,比 `"no API key set"` 更能浪费人的时间。

⇒ 本轮的三态不能是「贴一个 `undecryptable` 标签」,必须是**推断出哪半丢了**(§2.4)。

### 0.3 盐可以和密文分离 —— 三条独立的路

`server/crypto.py:93-94 _salt_path()` = `Path(config.settings.data_dir) / "crypto_salt"`,
`:97-121 _load_or_create_salt()` 路径缺失就 `os.urandom(16)` 造新的、**零迁移逻辑**。

1. **数据目录换了** ⇒ 新目录没有 `crypto_salt` ⇒ 造新盐。
   `server/config.py:39-51 _resolve_data_dir()` 今天是**单一 resolver**(`e5cc75c7` 修的就是这个),
   但那次统一**本身**把一部分安装的 data_dir 从 CWD 相对的 `"data"` 换成了
   `~/Library/Application Support/Arslan`(`config.py:28-36 _default_data_dir`)。
2. **`_FALLBACK_SALT` 静默替换**:`crypto.py:104-110`
   ```python
   except OSError:
       return _FALLBACK_SALT
   ```
   和 `:120-121` 写不进去时同样。`_FALLBACK_SALT`(`:55`)是**公开常量**
   `sha256(b"arslan-crypto-salt-v1")[:16]`。
   docstring(`:100-101`)自称 "so key derivation remains stable across restarts either way" ——
   **稳定 ≠ 对**:拿稳定的错钥匙开好密文必失败;更坏的是**在 fallback 盐下写入的新密文,
   权限恢复后反而打不开**。
3. **备份只带一半**:`server/secret_bootstrap.py:9-16` 明写 lock-and-box ——
   secret 刻意住在 data dir **外面**(默认 `~/.arslan/secret_key`),
   而盐住在 data dir **里面**。⇒ 拷 data dir 得到「盐+密文、无 secret」,
   拷 `~/.arslan` 得到「secret、无盐无密文」。**两个方向各缺一样。**

### 0.4 别的盐写的密文,今天没有任何恢复路径

`crypto.py:124-135 _build_multifernet` 只有**两把钥匙**:
```python
return MultiFernet([Fernet(new_key), Fernet(legacy_key)])
```
`new_key` = PBKDF2(secret, **当前**盐, 600k),`legacy_key` = 裸 `SHA256(secret)`(无盐)。

`d6d8afa8` 的模块 docstring(`crypto.py:19-23`)说得没错 ——
"ciphertext written under the old scheme still decrypts"。
**那句话是真的,它只覆盖了作者设想的那个失败模式**:旧无盐 → 新有盐。
而实际发生的是**新盐A → 新盐B**,回退对它无效。
`server/db/migrations/versions/` 里 grep `crypto|rekey|reencrypt` 零命中 —— 从来没有重加密迁移。

⇒ **读时回退不是迁移。** 一句「这不会造成 X」的注释,本身不是 X 不会发生的证据。

### 0.5 lock-and-box 是刻意的,不能撤

`secret_bootstrap.py` 已经实现了相当多「大声」纪律,别重做:
- `:113-133 _warn_on_mismatch` —— env 与持久文件不一致时**一条**警告,点名路径不带值,
  并且已经写了 "If stored provider keys fail to decrypt, check which secret they were written under."
- `:136-157 _log_disclosure` —— "A full backup is **TWO pieces**: your data dir AND this file."
- `:26-29` —— 读失败的既存文件**不当作缺失**,拒绝覆盖重生成,理由写在注释里。

**secret 在 data dir 外是安全设计**(偷到一份 data-dir 备份的人拿不到钥匙),
本轮**不许**为了「同生死」把 secret 挪进 data dir。

### 0.6 🔵 盐不是秘密 —— 这一条决定整个设计空间

PBKDF2 的盐**从设计上就不需要保密**,它只需要**唯一 + 稳定**。
⇒ 盐可以和密文放在一起,而这不削弱任何东西:
拿到「密文 + 盐」的人依然缺 secret,PBKDF2 600k 迭代照旧顶在那里。

**这是「同生死」和「lock-and-box」唯一的相容解**:
让**盐跟着密文走**,让**secret 独自留在外面**。

### 0.7 加一行不在注册表里的 `settings` 行不会外泄

`settings_service.py:132-168 get_settings` 从
`_PLAIN_KEYS` / `_SECRET_KEYS` / `_INT_ACCESSORS` / `_BOOL_ACCESSORS` **逐个注册表取**,
不是 dump 全表(`:142-153` 的注释还专门讲了「第六个触点」那次事故)。
⇒ 一个不登记在任何注册表里的 `Setting` 行**不会**出现在 `GET /settings` 的响应里。

### 0.8 现有测量(两个真库,已在上一轮做过)

- packaged 库:`web_search` 4 次调用 / 4 次失败 / 0 成功。
- dev 库:到 **2026-07-11 共 216 次成功**,之后 **134 次连续失败**,全部同一句
  `"not configured (no API key set)"`。
- **两库的 `search_api_key` 行都非空**(164 字符密文)。
- 盐A `Arslan/data/crypto_salt` 时间戳 **2026-07-10 22:05**;
  第二个盐 `~/Library/Application Support/Arslan/crypto_salt` **2026-07-11 23:45**。

⇒ **工作过、然后停了、key 还在。重新粘一次 key 是把同一颗雷再埋一次。**

---

## 1. 范围(用户五条,逐条落成条目)

| # | 用户条款 | 本轮条目 |
|---|---|---|
| 1 | 修共享 `get_decrypted` 路径,覆盖 `_SECRET_KEYS` 三个 | §2.3 把 `_key_status` 提成共享谓词,四个消费者全接 |
| 2 | 三态分清:没设置 / 设了但解不开 / 设了但连不通 | §2.3(前两态,存储态)+ §6.1 接缝(第三态,运行态,归 ①) |
| 3 | Settings 里解不开的 key 不许显示成正常掩码 | §2.3 + §0.2 修正:实测它今天渲染成**空**(`mask_secret("")` → `""`,`settings_service.py:49-56`),即「从未设置」——比「正常掩码」更难分辨 |
| 4 | A. 任何非常规盐必须大声 | §2.5 删掉 `_FALLBACK_SALT` 的**写**用途;保留为**读**候选 |
| 5 | B. secret 和盐同生死 | §2.1 盐进数据库(与密文同生死),secret 留在外(lock-and-box 不动) |

### 不做(防蠕变)

- **不改 secret 的存放位置**,不撤 lock-and-box(§0.5)。
- **不换 KDF**,不动 `_PBKDF2_ITERATIONS = 600_000`。再换一次派生 = 再制造一次同族事故。
- **不做密钥轮换 UI**、不做多用户/多 profile。
- **不动 `mask_secret` 的掩码形状**(`_looks_masked` 的 GET→PUT 回显守卫依赖它,
  `settings_service.py:35-46`)。
- **不碰搜索的运行态分类和文案**(那是 ①,见 §6.1)。

---

## 2. 设计

### 2.1 根治:盐进数据库,与密文同生死

**决定(设计方向由我定,用户 2026-08-07 授权)**:
盐从 `<data_dir>/crypto_salt` **文件**改为存在**数据库里**(一行 `Setting`,base64,明文)。

为什么这是对的:
- 密文住在 DB。盐住在同一个文件里 ⇒ **结构上无法分离**。
  data-dir 分裂、换目录、只拷一半 —— 三条路一起消失。
- 盐不是秘密(§0.6),放 DB 不降低任何强度。
- `_FALLBACK_SALT` 那条 OSError 通道**自动消失**:派生路径不再读文件系统。
- lock-and-box 不变:DB = 密文 + 盐(单独一文不值),`~/.arslan/secret_key` = 钥匙。
  备份文档那句 "TWO pieces" 依然成立,而且现在**第一件是自洽的**。
- 新增一条**可判定的不变量**(§2.4 靠它):
  **有密文行、无盐行 ⇒ 盐丢了。** 今天这个状态在代码里不可观测。

被否掉的备选,连理由一起留档:
- **盐挪到 secret 旁**(`~/.arslan/crypto_salt`):最便宜,两半确实同行了。
  否掉因为 ① `_FALLBACK_SALT` 那条 OSError 通道还在;② 它把「data dir 是唯一不可再生的东西」
  这条备份心智模型改成了两处都不可再生,与 [[arslan-user-data-backup]] 冲突;
  ③ 它对已经分裂的安装没有恢复力。**如果 §3 拍板项①判 §2.1 的启动次序太侵入,这是退路。**
- **盐前缀进每条密文**(PHC 风格):理论最干净,但要改 token 格式 ⇒ 所有既存密文都要迁移,
  比现在的问题更大。

**实现约束(次序,这是 §2.1 唯一真难点)**:
`crypto.py:138-139 _fernet()` 是**同步**的、**不接 DB**,而 `server.crypto` 被
`server.config` 之外的所有层同步调用。方案:

1. `crypto` 模块保留一个**进程级** `_salt: bytes | None`,由启动流程**一次性注入**
   (`crypto.adopt_salt(b)`),派生保持同步。
2. 未注入时 `_fernet()` **不许**猜一个盐 —— 必须 raise 一个明确的
   `CryptoNotInitializedError`。**静默换盐是本轮要杀的东西,不能在修它的过程中再造一个。**
3. 注入点在迁移之后、任何解密之前。启动次序要有一条测试钉住(§4.4)。

**迁移 0039**(三处 lockstep,`server/db/migrations/runner.py:17-20` 写死了规矩:
版本文件 + `MIGRATIONS` + `test_registry_matches_boot_chain_verbatim` 里的硬编码 id 列表;
当前最新是 `_0038_run_has_images.py`):
- 建盐行。**若 `<data_dir>/crypto_salt` 存在,原样收养它的字节**(不是重新生成)——
  这一步让今天正常的安装**零感知**升级。
- 若文件不存在且**已有密文行**,不要造新盐就完事:那正是「盐丢了」状态,交给 §2.2/§2.4。
- 幂等(`runner.py:13-15` 要求)。

### 2.2 两级钥匙串:「我们的」自动迁移,「候选的」只报告

读的时候钥匙串从 2 把扩成 N 把,**顺序固定,并且按 §3① 的裁决分成两组**:

```
组 A —— 「我们的」钥匙(合法派生自当前输入) ⇒ 命中即自动 rekey,无闸
  1. PBKDF2(secret, DB 盐)          ← 主钥匙;写只用这一把;命中 ⇒ 无事可做
  2. SHA256(secret)                 ← legacy 无盐(d6d8afa8 之前);命中 ⇒ 自动迁移

组 B —— 「候选」钥匙(靠找出来的,本质是猜) ⇒ 命中只报告,写要人点头
  3. PBKDF2(secret, 别处找到的盐文件里的盐)   ← 与 DB 行不同的那些
  4. PBKDF2(secret, _FALLBACK_SALT)          ← 历史上被静默用过的那把
```

**组 A 的自动 rekey(无闸)**:用主钥匙重加密回去,**写后立即用主钥匙读回校验**再提交;
失败则回滚并大声。这正是 `d6d8afa8` 跳过的那一步 —— 只做读时回退不做重加密,
就是把「下一次钥匙串再变一次就永久失去」这颗雷留在原地。
🔴 **而它也是「不设人闸」的全部理由**:legacy 密文如果只靠读时回退活着,
那把 legacy 钥匙就永远拆不掉,格式永生。

**组 B 的处理**:`diagnose()` 报「哪一把能开、能开几条」,**一个字节都不写**。
rekey 走一个显式的人闸(§3① 与 §3②)。

覆盖面(两组都一样):`_SECRET_KEYS` 三个 + `ProviderConfig.api_key` + `MCPServer.env`。
一个共享入口 `crypto.open_and_maybe_migrate(enc) -> (plaintext, new_enc | None, key_group)`,
四个消费者共用;`key_group` 就是自动/人闸的分界,**不许由调用方自己判断**。

⚠️ **`_build_multifernet` 有 `@functools.lru_cache(maxsize=16)`**(`crypto.py:124`)。
钥匙串变长后缓存键要跟着变(现在是 `(secret, salt)`),否则会缓存出一个少钥匙的实例。
⚠️ 组 B 的钥匙**不许进那个共用的 `MultiFernet`** —— `MultiFernet.decrypt` 逐把试、
只告诉你成不成,**不告诉你是哪一把成的**,而「是哪一把」正是本节的分界线。
组 B 要单独逐把试,拿到「哪一把」这个信息。

### 2.3 三态:把已有的谓词提成共享的

把 `provider_config_service.py:21-36 _key_status` 挪到 `server/crypto.py`(或
一个 `server/services/secret_state.py`),四个消费者全部改用它:

- `settings_service`:新增 `secret_state(session, key) -> 'unset'|'set'|'undecryptable'`,
  `GET /settings` 为三个键各带一个 `*_status` 字段。
  🔴 **`get_decrypted` 的返回类型不动**(`str`),否则调用面炸开;
  它旁边多一个**并列的**状态查询。这是刻意的最小切口。
- `provider_config_service`:改成 import 共享谓词,行为不变(它已经是对的)。
- `mcp_service` / `discovery`:`{}` 那两处改成**能区分**「本来没有 env」和
  「有 env 但解不开」,后者写进 `MCPServer.last_error`。
  🔴 顺手修一个实测到的形状:`str(InvalidToken())` **是空字符串**
  (`cryptography.fernet.InvalidToken` 是 `class InvalidToken(Exception): pass`,
  用项目 venv 实测 `repr(str(InvalidToken())) == "''"`)。
  所以任何 `str(exc)[:500]` 形状的错误上报(`discovery.py:80`)在这条路上
  会写进一个**空的** `last_error` —— 状态是 error、原因是空白。
- 前端:三个键复用 `ProviderDetailPane.tsx:315-331` 已有的图元和文案键
  (`keySavedReplace` / `keyReenter` / `keyUndecryptableReason`),**不造第二套词汇**。

### 2.4 大声说清哪半丢了 —— 诊断,不是固定句

新增 `crypto.diagnose() -> dict`,由 API 暴露(建议挂在既有的诊断/设置面,不新开页):

| 观测 | 结论 | 文案要点 |
|---|---|---|
| 有密文行、**无盐行**、无 `crypto_salt` 文件 | **盐丢了** | 「你的数据目录换过或被重建过。缺的是盐,不是你的密钥。」 |
| 有盐行、secret 来自**公开 fallback**(`crypto.is_insecure_default()`,`crypto.py:78-84`) | **secret 丢了** | 点名 `ARSLAN_SECRET_KEY` 与 `~/.arslan/secret_key` 两个位置 |
| 盐行与 secret 都在,主钥匙仍解不开,**且候选盐也全不中** | **两半不配对** | 「这份 secret 不是写这些密文的那一份」 |
| 本次派生用了非常规盐(候选命中 / fallback) | **降级可见** | 启动日志 + Settings 可见,并报「已自动重加密 N 条」 |

**硬要求**:`keyUndecryptableReason` 那句必须改掉 —— 它现在把病因写死成
"ARSLAN_SECRET_KEY changed"(§0.2)。改成**由诊断结论选句子**,六语同步。

### 2.5 `_FALLBACK_SALT` 只许读,不许写

- 删掉 `crypto.py:104-110` 和 `:120-121` 两处「OSError → 静默用 fallback 盐」的**写/派生**用途。
  §2.1 之后派生不读文件系统,这两处自然消失。
- `_FALLBACK_SALT` 常量**保留**,只作为 §2.2 的**读候选** —— 历史上真有安装在它下面写过密文,
  删了就是删掉那些人的恢复路径。注释要写明它为什么还在。
- 任何「本次派生没有用主盐」都算降级,走 §2.4 最后一行。

---

## 3. 拍板项 —— **用户已裁决(2026-08-08):①B(人闸) ②A(只读试解) ③A(进 `GET /settings`)**

### ① 自动 rekey 还是人闸? → 🟢 **两种写分开(用户 2026-08-08 拆歧义后裁决)**

我原来问的是一个二选一,而它**问错了** —— 把两种性质不同的写当成一件事。用户拆开了:

> 🔴 **解密已经成功的写是迁移,解密还没成功的写是赌博。**

| | 触发条件 | 裁决 | 理由(用户原话) |
|---|---|---|---|
| **迁移** | **当前钥匙**能解开 ⇒ 重加密进「盐入库」新方案 | 🟢 **允许自动,不设人闸** | **拦它会让 legacy 格式永生** |
| **恢复** | **当前钥匙解不开** ⇒ 去试候选盐 | 🟢 **纯只读 + 报告 + 人闸才 rekey** | 得先看清再动用户的数据 |

**「当前钥匙」的精确定义(实现必须照这个分,§2.2 落地)**:
钥匙串被**划成两半**,而这一刀就是自动/人闸的分界线 ——

- **「我们的」钥匙**(合法派生自当前输入):`PBKDF2(secret, DB 盐)` + `SHA256(secret)`(legacy 无盐)。
  其中任一把解开 ⇒ **迁移**,开机自动重加密到主钥匙,**无闸**。
- **「候选」钥匙**(靠找出来的,本质是猜):在别处找到的盐文件、`_FALLBACK_SALT`。
  其中任一把解开 ⇒ **恢复**,**只报告,不写**;写要人点头。

🔴 **我原来的写法在这里是错的,记一笔**:我把 legacy 无盐那把
**并进了「候选」并一刀切上人闸**。那会让 `d6d8afa8` 之前写入的密文
**永远靠读时回退活着**、永远不被重加密 —— 正是用户点出的「legacy 格式永生」,
也正是这份 spec §0.4 批评 `d6d8afa8` 的那件事本身。**一刀切的保守是错的保守。**

**落到实现上的两条硬约束**(各有测试,§4.4 第 8/9 条):
1. **恢复路径纯只读** —— 诊断和候选试解全程不许有任何写,用「任何写就抛」的 session 钉住。
2. **迁移路径必须真的发生** —— legacy 无盐密文在一次启动后**不再需要 legacy 钥匙**。
   这一条是上面那条的**反面守卫**:少了它,「什么都不写」会被读成「安全」。

### ② 拿你的真库当验收对象吗? → 🟢 **A(只读试解)**

盐A 文件 `Arslan/data/crypto_salt` 今天**还在**(§0.8),所以 §2.2 的候选盐试解
**有可能真的解开你那 164 字符的 `search_api_key`** —— 这是一个能在真数据上做的、
比任何 fixture 都硬的验收。

- 🟢 **A(裁决)**:**只读试解**。一个一次性脚本,只报告「能/不能解开、命中的是哪一把」,
  **一个字节都不写**。拿到「能」这个事实,再由用户点头是否真 rekey。
- **B(已否)**:直接在真库上跑完整 rekey。
  否掉的理由:那是 [[arslan-user-data-backup]] 里那个不可再生的库,而本轮的代码
  在那一刻还一次都没在真数据上跑过。

⚠️ 动之前照 `backup-data.sh` 走一遍备份,且 **`~/arslan-backups/` 一个字节都不碰**。

### ③ 三个 `*_status` 字段进 `GET /settings`,还是单开一个只读端点? → 🟢 **A**

用户「方向全批」覆盖这一条(我原倾向 A)。

- 🟢 **A(采纳)**:进 `GET /settings`,和 provider 那边的 `key_status` 形状对齐。
  一次往返、一个心智模型。
- **B(已否)**:单开 `GET /settings/secret-state`。
  ⚠️ 代价记一笔:走 A 就要碰 §0.7 那条注册表纪律(`get_settings` 从注册表逐个取),
  所以三个新字段要跟着进注册表并被完整性测试覆盖 —— 那正是 `:142-153` 注释里
  「第六个触点」那次事故的教训。

---

## 4. 验收(用户给定三场景,逐条落成可执行断言)

用户原话:**「换目录启动、缺环境变量启动、备份恢复到新机器,三个场景下要么照常解密、
要么大声说清哪半丢了 —— 不许再有静默换钥匙。」**

### 4.1 场景一:换数据目录启动

- 建库、存一个 `search_api_key`、成功读回。
- 把整个 data dir **移动**到新路径,`ARSLAN_DATA_DIR` 指向新路径,重启。
- **断言**:照常解密(盐随 DB 走了)。
- 反向:只带走 DB 文件、不带盐 —— 今天不可能了,盐在 DB 里。**用一条测试钉住这个不可能**:
  断言 `crypto` 派生路径**不读** `<data_dir>` 下的任何文件(mutation:把读加回去,测试必须红)。

### 4.2 场景二:缺环境变量启动

- `ARSLAN_SECRET_KEY` 不设、`ARSLAN_SECRET_KEY_FILE=""`(禁用持久文件)⇒
  `crypto.is_insecure_default()` 为真。
- **断言**:①`secret_state()` 三个键全报 `undecryptable`,不是 `unset`;
  ②`diagnose()` 报「secret 丢了」并点名两个位置;
  ③启动日志有一行;④**没有任何密文被重写**。

### 4.3 场景三:备份恢复到新机器

- 模拟:复制 data dir 到新路径 + **不**带 `~/.arslan/secret_key`(用
  `ARSLAN_SECRET_KEY_FILE` 指到一个空目录)。
- **断言**:诊断报「两半不配对 / secret 丢了」,**不是** `"no API key set"`,
  **不是**空的 `last_error`,**不是**那句 "ARSLAN_SECRET_KEY changed"(它现在是错的)。
- 再把 secret 文件放回 ⇒ 照常解密,零重加密(主钥匙本来就对)。

### 4.4 结构性断言(不靠场景,靠不变量)

1. **有密文、无盐行 ⇒ 报「盐丢了」**。直接构造这个 DB 状态。
2. **`crypto` 未注入盐时 raise,不猜**(§2.1 第 2 条)。mutation:改成 fallback 一个盐,测试必红。
3. **启动次序**:注入在迁移之后、任何解密之前。
4. **四个消费者全接三态**:从一份消费者清单**推导**期望,不手列
   (照 `test_fitness_covers_every_dropdown_option.py` 那个套路:注册表推导而非硬编码)。
5. **rekey 只在解密成功后发生**,且**写后读回校验**。
   mutation:去掉校验 / 让它在失败时也写,必须红。
6. **候选盐命中后,第二次启动走的是主钥匙**(证明 rekey 真落了盘,不是每次都靠回退)。
7. `_looks_masked` 的 GET→PUT 回显守卫不回归(`settings_service.py:35-46`)。
8. 🔴 **恢复路径(组 B)纯只读**(裁决 §3①:「解密还没成功的写是赌博」)。
   断言形状:诊断 + 候选试解全程用一个**会对任何写操作抛异常**的 session(或对
   `_set_raw` / `commit` 打桩计数并断言为 0),跑一遍全部四类诊断分支。
   mutation:在诊断路径里塞一次 `_set_raw`,测试必须红。
   ⚠️ 这一条不能靠「读代码没看见写」来满足 —— 那是源码断言,而缺陷形状恰恰是
   「顺手修一下」这种在别的分支里才触发的写(见 [[arslan-assert-behaviour-not-source]])。
9. 🔴 **迁移路径(组 A)必须真的发生 —— 第 8 条的反面守卫**
   (裁决 §3①:「拦它会让 legacy 格式永生」)。
   断言形状:写一条**legacy 无盐**格式的密文进库 → 启动一次 →
   ①它被重写成主钥匙格式;②**把 legacy 钥匙从钥匙串里拿掉后仍然解得开**
   (这一半才是「真的迁移了」的证据,只断言「读得到」的话读时回退也满足);
   ③迁移条数被报告出来。
   mutation:把组 A 的 rekey 改成只读回退 —— ② 必须红。
   ⚠️ **没有这一条,第 8 条会把「什么都不写」奖励成「安全」** ——
   而一个什么都不迁移的实现,和一个正确的实现在第 8 条下长得一模一样。

### 4.5 行为断言,不是源码断言

三态最容易写出一个**永不触发的分支**,而它坏掉的样子和正常一模一样(见
[[arslan-assert-behaviour-not-source]])。所以:

- 三态的 UI 断言必须**渲染组件、读屏幕上的字**,复用
  `web/src/__tests__/provider-key-input.test.tsx` 的形状(它已经这么做了)。
- 六语文案**逐语言断言非空**,并断言**没有任何语言里还留着 "ARSLAN_SECRET_KEY changed"
  这个病因**(那是本轮要删的那句话,留着就是留着一个假诊断)。
- **每一条 mutation 要带 ⓪ 前置断言证明改动真的落在被测的那一行**
  (上一轮有一条 mutation 改到了注释里,照样绿)。

---

## 5. 风险与未覆盖面(先写出来,不等事后补)

1. 🔴 **启动次序是本轮最可能出事的地方**。`crypto` 现在是同步、无状态、谁都能 import 的模块,
   给它加一个「必须先注入」的生命周期,就给全套测试加了一个前置条件。
   缓解:注入失败必须 raise(不是猜),并且 `conftest` 一处集中注入。
   ⚠️ 全量测试本来就需要 `ARSLAN_SECRET_KEY`(见 [[arslan-mcp-server-expose-round]]),
   这条会和它交互。
2. **迁移 0039 收养文件里的盐 —— 收养错了就是把所有人一起弄坏**。
   幂等 + 只在「盐行不存在」时收养 + 收养后立即用它试解一条真密文再提交。
3. **打包版是这个缺陷的高发地**,而打包版恰恰是本项目历史上「dev 正常/打包版死」的家族
   (见 [[arslan-packaged-only-defect-family]])。⇒ `packaging/fresh_install_check.py`
   要加一条**探针**:全新安装存 key、重启、读回。
   🔴 探针必须与真实消费者同尺(见 [[arslan-probe-must-match-consumer]]):
   走 API 存/读,不要直接调 `crypto`。
4. **未覆盖**:密钥轮换(用户主动换 secret 并希望旧密文跟着走)。本轮只做**恢复**,不做**轮换**。
   两者机制相同(rekey),但 UI 与授权语义不同 —— 单独立项。
5. **未覆盖**:`ProviderConfig.api_key` 之外的 provider 侧字段(`base_url` 等)不加密,不在范围。
6. 盐进 DB 之后,**DB 单独泄露 = 密文 + 盐同时泄露**。这不是新风险(600k PBKDF2 + secret 在外),
   但 README 的备份/安全段落要如实更新,别让「两件套」这句话继续暗示盐在别处。

---

## 6. 接缝与排期

### 6.1 🔴 ⓪ 和 ① 都改 `executors.py` 的搜索错误路径 —— 不是无冲突的

用户裁决时说「①②③ 动的文件互不重叠,可并行」。**⓪ 插进来之后这条对 ① 不再成立**:

- ⓪ 拥有:`executors.py:226-233 _search_provider` 的 `if not key` 那个 gate ——
  把「没设置 / 解不开」分开。
- ① 拥有:同一个函数里的 **provider 选择**(`get_provider(name, ...)` 今天永远不跑,
  因为 gate 在前面),以及 `:215-223 _categorize_exc` 的**运行态**语义
  (429/402/403)和 `web/src/lib/toolHumanize.ts:41-46` 的文案。

⇒ **排期:⓪ 先落 main,① rebase 在它之上。** ② 和 ③ 与两者都不重叠,可以真并行。
第三态(「设了但连不通」)**归 ①**,⓪ 只负责把前两态从「一句话」里拆开,
并留下一个 ① 能填的形状。

### 6.2 与 G1 的关系

无。G1 动 `arslan.py` + 三个 provider + `capability_fitness.py`,与本轮零重叠
(见 [[arslan-g1-parked-rebase-watch]] 的盯盘清单)。

---

## 7. 尚无证据、未声称已验

- **「候选盐试解能真的解开用户 dev 库那条 `search_api_key`」—— 未验,是推断。**
  推断依据:盐A 文件仍在、密文非空、secret 未变。
  能补的动作:§3 拍板项② 的只读试解脚本。**在那之前不许声称「能恢复」。**
- **本轮一行代码都还没写。** 上面所有 FILE:LINE 是**读**出来的,不是改出来的。
- **`_FALLBACK_SALT` 在真实安装上被用过 —— 未验。** 它是 `OSError` 触发的,
  而两个真库的盐文件都在。保留它作为读候选是**保守**而非**已知必需**。
- **打包版的盐位置未实测**。`_default_data_dir()` 在 macOS 返回
  `~/Library/Application Support/Arslan`,而 §0.8 记录的第二个盐路径大小写不同
  (`arslan`)—— macOS 默认大小写不敏感,所以我判定是同一目录,**但没有单独验证过**。
- **启动次序改造的测试影响面未测量**。§5.1 是风险陈述,不是已知规模。

---

关联:[[arslan-four-specs-recon-2026-08-07]]、[[arslan-user-data-backup]]、
[[arslan-oss-migration]]、[[arslan-probe-must-match-consumer]]、
[[arslan-assert-behaviour-not-source]]、[[arslan-packaged-only-defect-family]]、
[[arslan-reaudit-own-conclusions]]、[[arslan-migration-boot-backfill]]。

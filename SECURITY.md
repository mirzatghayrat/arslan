# Security Policy

Arslan is a local-first personal AI orchestrator. By design it runs powerful, potentially dangerous machinery on your machine, so it is worth understanding its threat model before you deploy it beyond localhost.

## What Arslan runs

- **A code sandbox.** Arslan generates and executes code. On macOS this runs under a kernel-enforced seatbelt profile with the network denied.
- **A credential-injecting MITM proxy.** So sandboxed git can reach the network without the raw tokens ever entering the sandbox, a local proxy terminates TLS and injects credentials on the way out. The raw secret lives only in the parent process.
- **Stored BYOK secrets.** Your LLM provider API keys are stored on disk, encrypted at rest.
- **An MCP client.** Arslan can launch configured MCP servers as **stdio subprocesses** — i.e. it runs arbitrary local commands that you configure.

## Safe-by-default posture

- **Environment split.** `ARSLAN_ENV=dev` on **localhost is unauthenticated by design** — zero friction for local, single-user use. This is intended only for a loopback bind on a machine you control.
- **Auth enforced where it matters.** In `prod`, in packaged builds (`ARSLAN_PACKAGED=1`), or on a **non-loopback bind**, Arslan requires a bearer token. If `ARSLAN_API_TOKEN` is empty in those modes, a token is **auto-generated on first run**, persisted to `<data_dir>/api_token` (owner-only), printed once at boot, and viewable/resettable from Settings.
- **Cross-site protections.** TrustedHost, CORS, and WebSocket-Origin checks block cross-site drive-by requests. Non-localhost / prod deployments must configure `ARSLAN_ALLOWED_HOSTS` and `ARSLAN_ALLOWED_ORIGINS`.
- **Secrets encrypted, public key refused.** BYOK secrets are **Fernet-encrypted** with a key derived via **PBKDF2-HMAC-SHA256** (per-install random salt at `<data_dir>/crypto_salt`, high iteration count). The app **refuses to write secrets under the built-in public dev key** — you must set a real `ARSLAN_SECRET_KEY` (the `ARSLAN_ALLOW_INSECURE_SECRETS` escape hatch exists for dev testing only and must never be used for real keys).
- **Sandbox fails closed.** Where the kernel sandbox is unavailable, code execution fails closed rather than silently running unsandboxed.

## Known boundaries

Please read these before exposing Arslan beyond a trusted local machine:

- **The kernel sandbox is macOS seatbelt only.** On non-macOS platforms it is unavailable and fails closed. The dev-only `ARSLAN_ALLOW_UNSANDBOXED_PY=1` escape hatch runs generated Python with the server's full privileges and network access — only enable it on a machine you fully trust.
- **Do not expose the server to an untrusted network without a token + allowlist.** An unauthenticated instance grants full control of the orchestrator, its stored secrets, and code execution to anyone who can reach it. Always set `ARSLAN_API_TOKEN` (or rely on the prod/packaged auto-token) **and** the host/origin allowlists for any non-loopback bind.
- **The MCP client runs arbitrary configured stdio commands by design.** Only configure MCP servers you trust; a malicious server definition can run arbitrary local commands.
- **BYOK secret confidentiality depends on `ARSLAN_SECRET_KEY` and `crypto_salt`.** Anyone with both the ciphertext and these can decrypt stored keys. Protect your data directory accordingly.
- **SSRF protection is delegated to your proxy for `https` + proxy.** Outbound fetches normally resolve the hostname once, reject any non-global address, and pin the connection to that IP — so a name that re-resolves to a private address between the check and the connection cannot be reached. That guarantee **cannot** be carried over an HTTP proxy on `https`: httpcore's CONNECT tunnel ignores the `sni_hostname` extension and hands the tunnel's own origin host to TLS, so pinning would make certificate validation fail against an IP literal. In that one combination Arslan degrades to *the proxy decides where the request goes* and **logs a warning** rather than failing silently. Plain `http` through a proxy, and every non-proxied request, still pin. If `HTTPS_PROXY`/`https_proxy` is set in your environment, your `https` fetches run in this delegated mode — point it at a proxy you trust, or unset it for the pinned path.

## Backup & durability

The `<data_dir>/crypto_salt` and `<data_dir>/api_token` files are part of the backup unit — back them up **together with** the database, not separately. New-scheme (PBKDF2) encrypted secrets are derived from `ARSLAN_SECRET_KEY` **and** the per-install `crypto_salt`: **losing `crypto_salt` (or restoring a mismatched one) makes those stored secrets undecryptable**, even with the correct `ARSLAN_SECRET_KEY`. Restore the whole data directory as a unit. The secret itself deliberately lives **outside** the data dir (your explicit env value, or the dev auto-generated `~/.arslan/secret_key` / `ARSLAN_SECRET_KEY_FILE`), so a complete backup is **two pieces**: the data directory **plus** that secret.

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue for a vulnerability.

- **Primary channel:** use GitHub's private vulnerability reporting — the **"Report a vulnerability"** button on the repository's **Security** tab (`https://github.com/mirzatghayrat/arslan/security/advisories/new`). This opens a private security advisory visible only to the maintainers.
- **That button is the only channel.** Private vulnerability reporting is enabled on this
  repository, so a report filed there reaches the maintainers privately and keeps the whole
  exchange in one place. There is deliberately no email address here: an address in a public
  file is scraped, and a second channel is a second place for a report to be missed.

Please include a description, reproduction steps, affected version/commit, and impact. We will acknowledge your report and coordinate a fix and disclosure timeline with you.

## Supported versions

Arslan is **pre-v1**. Only the `main` branch is supported; security fixes land there. There are no backported release branches yet.

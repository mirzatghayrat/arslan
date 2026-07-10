"""Host-side orchestration for a NETWORK shell command (git/gh over HTTPS). Reads the workspace
repo's remotes + current branch and the GitHub token ON THE HOST, runs the deterministic pre-flight
gates (host allowlist, push-branch), then spins a single-command credential-injecting proxy and runs
the command in the sandbox pointed at that proxy. The real token stays here — it seeds the proxy and
is NEVER placed in the sandbox env or filesystem.

Follow-up (not v1): the workspace UX — a network command runs with cwd = a single workspace dir;
`clone`/`ls-remote` (URL-based) work regardless, but "clone then push in the cloned subdir" needs a
per-repo cwd concept (single-command shell has no `cd`)."""
from __future__ import annotations

import asyncio
from pathlib import Path

from server.services import command_ca, command_policy, command_proxy, command_sandbox


def _data_dir() -> Path:
    # Single resolved root (config.data_dir()): unset ARSLAN_DATA_DIR -> the platform
    # app-data dir, not CWD/data, so the shell workspace co-locates with the brain.
    from server import config
    return config.data_dir()


def _workspace() -> Path:
    ws = _data_dir() / "shell_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


async def _run_host(*cmd: str, timeout: float = 10.0) -> str:
    """Run a read-only helper (git config read / gh auth token) ON THE HOST (unsandboxed). Best-
    effort — returns stdout or "" on any failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (out or b"").decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


async def _git_remotes(workspace: Path) -> dict:
    remotes: dict[str, str] = {}
    for line in (await _run_host("git", "-C", str(workspace), "remote", "-v")).splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] not in remotes:
            remotes[parts[0]] = parts[1]
    return remotes


async def _current_branch(workspace: Path) -> str:
    return (await _run_host("git", "-C", str(workspace), "rev-parse", "--abbrev-ref", "HEAD")).strip()


async def _github_token() -> str | None:
    tok = (await _run_host("gh", "auth", "token")).strip()
    return tok or None


async def run_network_command(command: str, argv: list) -> dict:
    """Pre-flight + proxy + sandboxed run for a network git/gh command. Returns command_sandbox's
    result dict, or {ok: False, error} when a gate refuses."""
    workspace = _workspace()
    remotes = await _git_remotes(workspace)
    branch = await _current_branch(workspace)
    remote_hosts = {h for u in remotes.values() if (h := command_policy._url_host(u))}

    host = command_policy.resolve_target_host(command, argv, repo_remotes=remotes)
    if not command_policy.is_host_allowed(host, repo_remote_hosts=remote_hosts):
        return {"ok": False, "error": (f"网络目标主机不在白名单:{host or '未能解析'}"
                                       "(仅允许 GitHub 及本仓库已配置的 remote)")}
    if command == "git" and not command_policy.push_targets_current_branch(argv, branch):
        return {"ok": False, "error": f"只允许 push 当前分支({branch or '未知'}),拒绝推任意 ref"}

    token = await _github_token()
    ca = command_ca.LocalCA(_data_dir() / "shell_ca")
    ca_path = str(ca.dir / "ca.crt")
    proxy = await command_proxy.start_proxy(allow_hosts=remote_hosts, inject_token=token, ca=ca)
    try:
        purl = f"http://127.0.0.1:{proxy.port}"
        env = {
            "HTTPS_PROXY": purl, "HTTP_PROXY": purl, "ALL_PROXY": purl,
            "GIT_SSL_CAINFO": ca_path,   # git trusts the proxy's MITM leaf
            "SSL_CERT_FILE": ca_path,    # gh (Go) trusts it via the system-pool override
            "GH_TOKEN": "proxied",       # dummy so gh sends an Authorization the proxy then swaps
        }
        return await command_sandbox.run_command(
            command, argv, proxy_port=proxy.port, cwd=str(workspace), extra_env=env)
    finally:
        await proxy.close()

"""NET-a: the sandbox proxy serves only a running command's token (net_policy.start_run). Tests of the proxy's own checks
(public addresses, trusted devices, its answers) send theirs as an unjudged run's, an MCP server's kind, so NET's
judgement stays out of them; that judgement is tests/server/sbx/test_net_a_proxy.py's."""
import base64

from server.services import net_policy

TOKEN = "0" * 24 + "5bx6a7e5"


def register(monkeypatch) -> None:
    """The unjudged run whose token `authed` sends, registered for one test."""
    monkeypatch.setitem(net_policy._runs, TOKEN, net_policy.Run(TOKEN, None, None, "", lambda: False, False,
                                                                judged=False))


def header(token: str = TOKEN) -> bytes:
    return b"Proxy-Authorization: Basic " + base64.b64encode(f"{token}:sandbox".encode()) + b"\r\n"


def authed(request: bytes, token: str = TOKEN) -> bytes:
    """`request` with the token's credentials, right after its request line."""
    line, _, rest = request.partition(b"\r\n")
    return line + b"\r\n" + header(token) + rest

"""SEC1 follow-up (#623 re-check R-7): a credential in an option written as `--name=value`. SEC1 read an argument
that is a URL, `--token=VALUE` by its name, and `--name VALUE` as two arguments; an address given as an option's
value in one argument (`--index-url=https://user:token@host/simple`, `--registry=https://host/?token=…`), and npm's
own `--//host/:_authToken=…`, were neither offered the move nor masked."""
import pytest

from server.services import connection_secrets as cs

TOKEN = "npm_" + "Ab3dE6gH9jK2mN5pQ8sT1vW4yZ7bC0eF3hJ6"          # fake; built at run time so no scanner reads it
PYPI = "pypi-" + "AgEIcHlwaS5vcmcCJDk4ZjM0"


@pytest.mark.parametrize("arg, part, secret", [
    ("--index-url=https://ci:" + PYPI + "@pypi.internal/simple", {"at": "password"}, PYPI),
    ("--extra-index-url=https://__token__:" + PYPI + "@upload.pypi.org/simple", {"at": "password"}, PYPI),
    ("--registry=https://npm.internal/?token=" + TOKEN, {"at": "query", "key": "token", "n": 0}, TOKEN),
    ("--registry=https://" + TOKEN + "@npm.internal/", {"at": "user"}, TOKEN),
    ("--//registry.npmjs.org/:_authToken=" + TOKEN, {"key": "//registry.npmjs.org/:_authtoken"}, TOKEN),
    ("--//npm.internal/:_password=" + "aHVudGVyMnBhc3M=", {"key": "//npm.internal/:_password"}, "aHVudGVyMnBhc3M="),
])
def test_a_credential_in_an_option_value_is_found_masked_and_moved_back_byte_for_byte(arg, part, secret):
    args = ["-y", "notes-mcp@1.0.0", arg, "--port", "8080"]
    [found] = cs.find(None, args)
    assert found == {"where": "arg", "index": 2, **part}
    shown = cs.shown(None, args)[1]
    assert secret not in shown[2] and shown[2].startswith(arg.partition("=")[0] + "=") and shown[3:] == args[3:]
    _, moved, values = cs.move(None, args, found, "NOTES_SECRET", {})
    assert secret not in moved[2] and "${NOTES_SECRET}" in moved[2] and values == {"NOTES_SECRET": secret}
    assert cs.fill(None, moved, values)[1] == args


@pytest.mark.parametrize("arg", [
    "--index-url=https://pypi.org/simple", "--registry=https://registry.npmjs.org/", "--cache=/tmp/npm-cache",
    "--//registry.npmjs.org/:always-auth=true", "--index-url=https://ci:${PIP_TOKEN}@pypi.internal/simple",
    "--//registry.npmjs.org/:_authToken=${NPM_TOKEN}", "--registry=https://npm.internal/?scope=acme&page=2",
    "--//registry.npmjs.org/:_authToken=", "--=x",
])
def test_an_ordinary_option_value_is_not_a_secret(arg):
    assert cs.find(None, ["-y", "notes-mcp@1.0.0", arg]) == []
    assert cs.shown(None, [arg])[1] == [arg]


async def test_a_stored_connection_offers_the_option_value_and_still_starts_with_it(execution_db):
    """End to end: the list offers the part and shows it masked; after the move the stored row holds the
    placeholder, and what the session gets holds the value again."""
    from server.db.models import MCPServer
    from server.mcp.discovery import runtime_dict
    from server.services import mcp_service
    args = ["--index-url=https://ci:" + PYPI + "@pypi.internal/simple", "notes-mcp==1.0.0"]
    added = await mcp_service.add_server("Notes", "uvx", args, {}, transport="stdio")
    [row] = [row for row in await mcp_service.list_servers() if row["id"] == added["id"]]
    [part] = row["secret_parts"]
    assert (part["where"], part["index"], part["at"]) == ("arg", 0, "password") and PYPI not in str(row["args_shown"])
    await mcp_service.move_secret(added["id"], part, part["name"])
    async with execution_db() as db:
        srv = await db.get(MCPServer, added["id"])
    assert PYPI not in str(list(srv.args)) and srv.args[0] == "--index-url=https://ci:${" + part["name"] + "}@pypi.internal/simple"
    assert runtime_dict(srv)["args"] == args

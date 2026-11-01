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


# ── #628 review ─────────────────────────────────────────────────────────────────────────────────────────────


def _round_trip(args, part, secret):
    found = [p for p in cs.find(None, args) if p == part]
    assert found == [part], cs.find(None, args)
    shown = cs.shown(None, args)[1]
    assert all(secret not in a for a in shown)
    _, moved, values = cs.move(None, args, part, "NOTES_SECRET", {})
    assert all(secret not in a for a in moved) and values == {"NOTES_SECRET": secret}
    assert cs.fill(None, moved, values)[1] == args


@pytest.mark.parametrize("arg, key", [
    ("https://mcp.example/oauth/done#access_token=" + TOKEN + "&state=x", "access_token"),
    ("https://mcp.example/sse?view=full#token=" + TOKEN, "token"),
])
def test_a_token_in_a_urls_fragment_is_found_like_one_in_its_query(arg, key):
    """L-1 (from before this PR): `#token=…` and `#access_token=…` were not read."""
    _round_trip([arg], {"where": "arg", "index": 0, "at": "fragment", "key": key, "n": 0}, TOKEN)
    url = "https://mcp.example/sse#token=" + TOKEN
    assert [p["at"] for p in cs.find(url, [])] == ["fragment"] and TOKEN not in cs.shown(url, [])[0]
    assert cs.find("https://mcp.example/docs#install", []) == [] and cs.find("https://mcp.example/x#view=full", []) == []


@pytest.mark.parametrize("args, index", [
    (["--index", "corp=https://bot:" + PYPI + "@pypi.internal/simple", "notes==1.0"], 1),     # uv's named index
    (["--index=corp=https://bot:" + PYPI + "@pypi.internal/simple", "notes==1.0"], 0),
    (["NOTES_URL=https://bot:" + PYPI + "@notes.example/api"], 0),
    (["-y", "notes-mcp@https://bot:" + PYPI + "@files.example/notes.tgz"], 1),
])
def test_an_address_inside_a_value_is_read_from_its_scheme(args, index):
    """L-2: a value that holds an address after a name (`corp=https://…`, `NAME=https://…`, `name@https://…`)."""
    _round_trip(args, {"where": "arg", "index": index, "at": "password"}, PYPI)


def test_a_scopes_registry_option_is_read_as_an_address():
    """L-3: kills the mutant that never reads an npm-style option's value as an address."""
    _round_trip(["--@acme:registry=https://bot:" + TOKEN + "@npm.pkg.github.com/"],
                {"where": "arg", "index": 0, "at": "password"}, TOKEN)


def test_a_value_after_a_secret_flag_stays_a_secret_even_when_it_looks_like_an_option():
    """I-1: `--token --9Ab3…==` was read as an option of its own, and shown. (A value that reads as an ordinary
    option, `--port=8080` after `--api-key`, stays that option: npm and uv would read it so.)"""
    value = "--9" + TOKEN[4:] + "=="
    _round_trip(["--token", value], {"where": "arg", "index": 1, "key": "token"}, value)
    assert cs.find(None, ["--api-key", "--port=8080"]) == []

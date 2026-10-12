"""A tiny MCP stdio server for the real-process tests (0.1.61 PR 4). Standard library only.

Run as `python fake_mcp_server.py MODE`. Every mode first writes "pid is <pid>" to stderr. Each
tools/call runs on its own thread, so a call can be pending while another arrives:
  ok                one tool `a` (readOnlyHint, title "Tool A"); tools/call echoes; tool `die` exits
                    the process at once; tool `slow` answers after $SLOW_CALL_S seconds (default 30)
  slow_init         answers initialize after $SLOW_INIT_S seconds (default 2)
  usage_exit        prints usage text to stdout and exits 2 (a program that does not speak MCP)
  crash_with_stderr writes "Error: REA_TOKEN is not set" to stderr and exits 1 on initialize
  echo_then_crash   writes "token is $FAKE_SECRET" to stderr, then exits 1 on initialize
  echo_env          writes "token is $FAKE_SECRET" and "cwd is <cwd>" to stderr, then like ok
  hang_list         never answers tools/list
  list_changed      first tools/list → [a]; then sends tools/list_changed; later lists → [a, b]
  garbage_then_ok   prints one non-JSON line, then like ok
  paged             tools/list in two pages: [a] with nextCursor "p2", then [b]
"""
import json
import os
import sys
import threading
import time

MODE = sys.argv[1] if len(sys.argv) > 1 else "ok"
_SEND = threading.Lock()


def send(obj):
    with _SEND:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


def tool(name, **hints):
    item = {"name": name, "description": f"tool {name}", "inputSchema": {"type": "object"}}
    if hints:
        item["annotations"] = hints
    return item


def answer_call(mid, name):
    if name == "die":
        os._exit(3)                       # the whole process, from a thread
    if name == "slow":
        time.sleep(float(os.environ.get("SLOW_CALL_S", "30")))
    send({"jsonrpc": "2.0", "id": mid,
          "result": {"content": [{"type": "text", "text": f"called {name}"}]}})


def main():
    sys.stderr.write(f"pid is {os.getpid()}\n")
    sys.stderr.flush()
    if MODE == "usage_exit":
        print("usage: fake [--mcp]", flush=True)
        sys.stderr.write("fake: no command given\n")
        sys.stderr.flush()
        time.sleep(0.2)
        sys.exit(2)
    if MODE == "garbage_then_ok":
        print("starting server (not JSON)", flush=True)
    if MODE in ("echo_env", "echo_then_crash"):
        sys.stderr.write(f"token is {os.environ.get('FAKE_SECRET', '')}\ncwd is {os.getcwd()}\n")
        sys.stderr.flush()
    lists = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        mid, method = msg.get("id"), msg.get("method")
        if method == "initialize":
            if MODE == "slow_init":
                time.sleep(float(os.environ.get("SLOW_INIT_S", "2")))
            if MODE == "crash_with_stderr":
                sys.stderr.write("Error: REA_TOKEN is not set\n")
                sys.stderr.flush()
                sys.exit(1)
            if MODE == "echo_then_crash":
                sys.exit(1)
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": msg["params"]["protocolVersion"],
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "fake", "version": "1"}}})
        elif method == "tools/list":
            if MODE == "hang_list":
                continue
            lists += 1
            cursor = (msg.get("params") or {}).get("cursor")
            if MODE == "paged":
                page = ({"tools": [tool("a")], "nextCursor": "p2"} if cursor is None
                        else {"tools": [tool("b")]})
                send({"jsonrpc": "2.0", "id": mid, "result": page})
                continue
            tools = [tool("a", readOnlyHint=True, title="Tool A")]
            if MODE == "list_changed" and lists > 1:
                tools.append(tool("b", destructiveHint=True))
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}})
            if MODE == "list_changed" and lists == 1:
                send({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        elif method == "tools/call":
            threading.Thread(target=answer_call, args=(mid, msg["params"]["name"]),
                             daemon=True).start()
        elif mid is not None:
            send({"jsonrpc": "2.0", "id": mid, "result": {}})


if __name__ == "__main__":
    main()

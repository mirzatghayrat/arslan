"""0.1.49 S10: DeepSeek native tool-protocol contract probe (paid, tiny).

Runs through the metering proxy (the only process holding the key). Answers the
questions the P1 design could not settle from documentation alone:

  a  two-step tool loop with reasoning_content echoed back      -> 200?
  b1 earlier user turn: plain assistant reply, no reasoning      -> 200 or 400?
  b2 earlier user turn: assistant tool_calls without reasoning   -> 200 or 400?
  c  current turn: tool_calls assistant WITHOUT reasoning        -> 400 body (degrade trigger)
  d  forced step: same tools + tool_choice "none"                -> no tool_calls?
  e1 thinking on, max_tokens=64                                  -> where is it cut?
  e2 thinking off, long prose, max_tokens=64                     -> length in content
  e3 thinking off, long write_file call, max_tokens=64           -> length inside arguments

Usage: python -m scripts.kernel_bench.contract_probe [proxy_base] [out.json]
"""
from __future__ import annotations

import json
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8900/c/probe"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/arslan-kernel-bench/contract_probe.json"
MODEL = "deepseek-v4-flash"
TOOLS = [
    {"type": "function", "function": {"name": "read_file", "description": "Read a text file.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Write a text file.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"},
                    "content": {"type": "string"}}, "required": ["path", "content"]}}},
]
SYSTEM = {"role": "system", "content": "You are a file assistant. Use tools when a file is mentioned."}
TASK = {"role": "user", "content": "What is the first word in notes.txt? Read it, then answer in one word."}
results: dict = {}


def call(name, messages, **extra):
    body = {"model": MODEL, "messages": messages, "max_tokens": extra.pop("max_tokens", 1024), **extra}
    r = httpx.post(f"{BASE}/chat/completions", json=body, timeout=180)
    rec: dict = {"status": r.status_code}
    if r.status_code != 200:
        rec["error"] = r.text[:600]
    else:
        data = r.json()
        choice = data["choices"][0]
        msg = choice["message"]
        rec.update({
            "finish_reason": choice.get("finish_reason"),
            "reasoning_chars": len(msg.get("reasoning_content") or ""),
            "content_chars": len(msg.get("content") or ""),
            "content_head": (msg.get("content") or "")[:120],
            "tool_calls": [{"id": t.get("id"), "name": t["function"]["name"],
                            "arguments_raw": t["function"]["arguments"][:240],
                            "arguments_len": len(t["function"]["arguments"])}
                           for t in msg.get("tool_calls") or []],
            "usage": data.get("usage"),
        })
        rec["_message"] = msg
    results[name] = rec
    print(name, {k: v for k, v in rec.items() if k not in ("_message", "usage")}, flush=True)
    return rec


def tool_msg(call_id, content):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


a1 = call("a1_first_step", [SYSTEM, TASK], tools=TOOLS)
m1 = a1.get("_message")
if m1 and m1.get("tool_calls"):
    cid = m1["tool_calls"][0]["id"]
    turn = [SYSTEM, TASK, m1, tool_msg(cid, "Lighthouse keepers log the weather daily.")]
    call("a2_reasoning_echoed", turn, tools=TOOLS)
    stripped = {k: v for k, v in m1.items() if k != "reasoning_content"}
    call("c_reasoning_dropped", [SYSTEM, TASK, stripped, tool_msg(cid, "Lighthouse keepers log the weather daily.")],
         tools=TOOLS)
    call("d_forced_tool_choice_none", turn, tools=TOOLS, tool_choice="none")
    prior_tool_turn = [SYSTEM, {"role": "user", "content": "Read todo.txt."},
                       {"role": "assistant", "content": "", "tool_calls": [{"id": "old_1", "type": "function",
                        "function": {"name": "read_file", "arguments": "{\"path\": \"todo.txt\"}"}}]},
                       tool_msg("old_1", "buy milk"), {"role": "assistant", "content": "It says: buy milk."}, TASK]
    call("b2_prior_turn_tool_calls_no_reasoning", prior_tool_turn, tools=TOOLS)
call("b1_prior_turn_plain_no_reasoning",
     [SYSTEM, {"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello! How can I help?"}, TASK],
     tools=TOOLS)
long_prose = {"role": "user", "content": "Write a 600-word essay about lighthouses. No tools."}
call("e1_thinking_on_cap64", [SYSTEM, long_prose], tools=TOOLS, max_tokens=64)
off = {"thinking": {"type": "disabled"}}
call("e2_thinking_off_prose_cap64", [SYSTEM, long_prose], tools=TOOLS, max_tokens=64, **off)
call("e3_thinking_off_write_cap64", [SYSTEM, {"role": "user", "content":
     "Save a 400-word essay about lighthouses to essay.md using write_file. Do not answer in chat."}],
     tools=TOOLS, max_tokens=64, tool_choice="required", **off)

for rec in results.values():
    rec.pop("_message", None)
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(results, fh, ensure_ascii=False, indent=2)
print("saved", OUT)

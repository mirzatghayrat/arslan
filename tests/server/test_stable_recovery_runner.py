"""Exact M4 two-process harness with scripted replies and prohibited network."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CHILD = r'''
import asyncio, json, os, sys
import httpx
from pathlib import Path
def audit(event, args):
    if event in {"socket.connect", "socket.bind", "socket.getaddrinfo"}:
        raise RuntimeError("offline_recovery_network_forbidden")
sys.addaudithook(audit)
from arslan.llm.adapter import LLMAdapter
from evals.companion.stable_recovery import run_phase

phase = sys.argv[1]
class Transport:
    step = 0
    async def post(self, client, url, **kwargs):
        self.step += 1
        if phase == "crash" and self.step == 1:
            name, args = "write_file", {"path": "brief.md", "content": "Cedar — owner Mira; deadline Monday (calendar date unknown).\nSource: Synthetic Project Cedar brief, revision 1.\n"}
        elif (phase == "crash" and self.step == 2) or (phase == "resume" and self.step == 1):
            name, args = "read_file", {"path": "brief.md"}
        else:
            return self.response(url, {"role": "assistant", "content": "Cedar: Mira; Monday, calendar date unknown. Source: Synthetic Project Cedar brief, revision 1. Saved brief.md retained."})
        return self.response(url, {"role": "assistant", "content": "", "tool_calls": [
            {"id": str(self.step), "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]})
    def response(self, url, message):
        return httpx.Response(200, request=httpx.Request("POST", url), json={"choices": [{"message": message}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
transport = Transport()
async def post(client, url, **kwargs): return await transport.post(client, url, **kwargs)
httpx.AsyncClient.post = post
adapter = LLMAdapter("openai", "offline-fixture", api_key="synthetic", base_url="https://example.invalid")
asyncio.run(run_phase(phase, Path(os.environ["ARSLAN_DATA_DIR"]), Path(sys.argv[2]), adapter))
'''


def test_exact_m4_host_survives_two_processes_without_rewriting(tmp_path):
    home, profile, evidence = tmp_path / "home", tmp_path / "profile", tmp_path / "evidence"
    home.mkdir()
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
        "ARSLAN_DATA_DIR": str(profile), "ARSLAN_DB_PATH": str(profile / "arslan.db"),
        "ARSLAN_SECRET_KEY": "stable-recovery-synthetic-only", "ARSLAN_SECRET_KEY_FILE": "",
        "ARSLAN_ENV": "prod", "ARSLAN_LIVE_LLM": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    for phase, expected in (("crash", 73), ("resume", 0)):
        child = subprocess.run([sys.executable, "-c", CHILD, phase, str(evidence)], cwd=ROOT,
            env=environment, text=True, capture_output=True, timeout=45)
        assert child.returncode == expected, child.stdout + child.stderr
    before = json.loads((evidence / "before-crash.json").read_bytes())
    recovered = json.loads((evidence / "recovered-no-resume.json").read_bytes())
    after = json.loads((evidence / "after-resume.json").read_bytes())
    assert before["budget"]["used"]["model_requests"] == 3
    assert recovered["budget"] == before["budget"]
    assert after["budget"]["used"]["model_requests"] == 5
    assert after["file_unchanged"] and after["quality_status"] == "not_run"
    assert after["native_status"] == "not_run"
    assert json.loads((evidence / "crash-started.json").read_bytes())["pid"] != json.loads(
        (evidence / "resume-started.json").read_bytes())["pid"]
    repeat = subprocess.run([sys.executable, "-c", CHILD, "resume", str(evidence)], cwd=ROOT,
        env=environment, text=True, capture_output=True, timeout=10)
    assert repeat.returncode != 0 and "FileExistsError" in repeat.stderr

"""SMART-2 (v0.1.64, docs/plans/0164/SMART-feels-smart.md): Arslan knows its own state. `my_status` answers "which
version / which model / what's my sandbox / what can you reach / what failed" from live state, and says where its own
source lives (GitHub main and the plan folder there), never a folder guessed on this Mac. Each field is read when the
tool runs: a test changes the state underneath and the answer follows."""
import json
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from server.db.models import ApprovalEvent, ConversationModel, ProviderConfig, Run, RunStep, Setting, SshNode
from server.services import phone_bridge, self_status


async def _add(client, rows):
    async with client.db_maker() as db:
        for row in rows:
            db.add(row)
            await db.flush()
        await db.commit()


@pytest.fixture(autouse=True)
def _no_phones(monkeypatch):
    monkeypatch.setattr(phone_bridge.hub, "devices", [])
    monkeypatch.setattr(phone_bridge.hub, "socket", None)


async def test_the_version_and_whats_new_are_the_running_ones(client, monkeypatch):
    monkeypatch.setattr(self_status.release_notes, "settings", replace(self_status.release_notes.settings, app_version="9.8.7"))
    monkeypatch.setattr(self_status.release_notes, "recent",
                        lambda count=3, version=None: [{"version": "9.8.7", "title": "Faster", "notes": "x"}][:count])
    got = await self_status.snapshot()
    assert got["version"] == "9.8.7"
    assert got["whats_new"][0]["version"] == "9.8.7"


async def test_the_models_are_the_configured_ones(client):
    await _add(client, [ProviderConfig(id=1, label="Work", provider="anthropic", model="claude-opus-5-5", api_key="x"),
                        ProviderConfig(id=2, label="Home", provider="deepseek", model="deepseek-v4-pro", api_key="x",
                                       is_primary=True),
                        ConversationModel(conversation_id="picked", config_id=1, model="claude-haiku-5-5")])
    plain = await self_status.snapshot()
    assert plain["models"]["chat"] == {"model": "deepseek-v4-pro", "provider": "deepseek"}
    assert plain["models"]["quick_ask"] == "same as chat"
    assert "this_conversation" not in plain["models"]
    picked = await self_status.snapshot(conversation_id="picked")
    assert picked["models"]["this_conversation"] == {"model": "claude-haiku-5-5", "provider": "anthropic"}


async def test_no_model_configured_says_so(client):
    assert (await self_status.snapshot())["models"]["chat"] is None


@pytest.mark.parametrize("sandbox, policy, lan, expected", [
    (None, None, None, {"command_sandbox": "on", "approvals": "every command asks", "local_network_scan": "off"}),
    ("false", "ask_risky", "true", {"command_sandbox": "off", "approvals": "harmless commands run, the rest ask", "local_network_scan": "on"}),
])
async def test_the_safety_settings_are_the_stored_ones(client, sandbox, policy, lan, expected):
    rows = [Setting(key=k, value=v) for k, v in (("terminal_sandbox_enabled", sandbox), ("shell_confirm_policy", policy),
                                                   ("lan_discovery_enabled", lan)) if v is not None]
    await _add(client, rows)
    assert (await self_status.snapshot())["safety"] == expected


async def test_reach_is_the_paired_phones_and_the_ssh_hosts(client, monkeypatch):
    monkeypatch.setattr(phone_bridge.hub, "socket", object())
    monkeypatch.setattr(phone_bridge.hub, "devices", [
        {"device_id": "dev-secret-1", "name": "Alex's iPhone", "paired_at": "2026-10-01T00:00:00Z", "state": "active"}])
    await _add(client, [SshNode(name="mac-mini", host="192.168.1.20", username="u", host_keys="k")])
    reach = (await self_status.snapshot())["reach"]
    assert reach == {"iphone_bridge": "connected", "phones": ["Alex's iPhone"], "ssh_hosts": ["mac-mini"]}
    assert "dev-secret-1" not in json.dumps(reach) and "192.168.1.20" not in json.dumps(reach)


async def test_the_last_failures_are_the_recorded_ones_newest_first(client):
    now = datetime.utcnow()
    older, newer = now - timedelta(hours=2), now - timedelta(minutes=5)
    rows = [Run(id=1, conversation_id="c", user_message="x", started_at=older, status="recorded", error_kind="ProviderError"),
            Run(id=2, conversation_id="c", user_message="y", started_at=newer, status="recorded")]
    await _add(client, rows)
    await _add(client, [
        RunStep(run_id=2, seq=0, kind="tool_call", ref={"tool": "run_command", "ok": False}, started_at=newer,
                detail={"summary": "rm: secret.txt: Permission denied"}),
        RunStep(run_id=2, seq=1, kind="tool_call", ref={"tool": "read_file", "ok": True}, started_at=newer),
        ApprovalEvent(created_at=now - timedelta(minutes=30), conversation_id="c", kind="command", target="curl x",
                      mode="standard", decided_by="user", decision="deny"),
        ApprovalEvent(created_at=now - timedelta(minutes=20), conversation_id="c", kind="command", target="ls",
                      mode="standard", decided_by="user", decision="allow")])
    failures = (await self_status.snapshot())["recent_failures"]
    assert [f["what"] for f in failures] == ["tool run_command failed", "refused: command (by user)", "run failed: ProviderError"]
    assert all(f["at"].endswith("Z") for f in failures)
    assert "secret.txt" not in json.dumps(failures) and "curl x" not in json.dumps(failures), "what failed, never its text"


async def test_at_most_five_failures(client):
    now = datetime.utcnow()
    await _add(client, [Run(id=k, conversation_id="c", user_message="x", started_at=now - timedelta(minutes=k),
                            status="recorded", error_kind=f"E{k}") for k in range(1, 9)])
    failures = (await self_status.snapshot())["recent_failures"]
    assert [f["what"] for f in failures] == [f"run failed: E{k}" for k in range(1, 6)]


async def test_five_in_all_when_every_kind_failed(client):
    now = datetime.utcnow()
    await _add(client, [Run(id=k, conversation_id="c", user_message="x", started_at=now - timedelta(minutes=3 * k),
                            status="recorded", error_kind=f"E{k}") for k in range(1, 4)])
    await _add(client, [RunStep(run_id=1, seq=k, kind="tool_call", ref={"tool": f"t{k}", "ok": False},
                                started_at=now - timedelta(minutes=3 * k + 1)) for k in range(3)]
               + [ApprovalEvent(created_at=now - timedelta(minutes=3 * k + 2), kind="file", target="x", mode="standard",
                                decided_by="user", decision="deny") for k in range(3)])
    failures = (await self_status.snapshot())["recent_failures"]
    assert len(failures) == 5, "the newest five across the three kinds, not five of each"
    assert failures[0]["what"] == "tool t0 failed"


async def test_no_bridge_says_not_connected(client):
    reach = (await self_status.snapshot())["reach"]
    assert reach == {"iphone_bridge": "not connected", "phones": [], "ssh_hosts": []}


async def test_its_own_source_is_github_main_never_a_local_folder(client):
    source = (await self_status.snapshot())["source"]
    assert source["repository"] == "https://github.com/mirzatghayrat/arslan"
    assert source["branch"] == "main"
    assert source["plans"].startswith("docs/plans/")
    text = json.dumps(source)
    assert "/Users/" not in text and "~/" not in text


async def test_my_status_is_a_tool_arslan_can_call(client):
    from server.orchestrator import arslan
    from server.registry.executors import EXECUTORS
    assert "my_status" in {t["key"] for t in await arslan._callable_tools()}
    assert "my_status" in EXECUTORS
    got = await EXECUTORS["my_status"].execute({})
    assert got["ok"] is True and got["version"]


def test_the_prompt_sends_self_questions_to_my_status_and_plan_questions_to_github():
    from server.orchestrator import arslan
    prefix = arslan._ANSWER_STABLE_PREFIX
    assert "my_status" in prefix and "whats_new" in prefix
    assert "github.com/mirzatghayrat/arslan" in prefix and "docs/plans" in prefix
    assert "older than your own version" in prefix
    assert str(arslan._build_answer_system()) == str(arslan._build_answer_system()), "the prefix stays byte-stable (K3)"

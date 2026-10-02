"""0.1.50 P2 S4: answers that deny a capability the turn had are corrected once.
Positive texts are the ones the kernel bench recorded."""
import pytest

from server.orchestrator import tool_loop
from server.orchestrator.capability_truth import denied_capability
from tests.server import test_trajectory_golden as golden

WRITE = {"write_file", "edit_file", "run_command", "web_search"}


@pytest.mark.parametrize("answer", [
    "我无法直接把文件写入 `/private/tmp/x`：当前环境没有提供文件系统写入能力，所以不能声称已经保存。",
    "我无法完成“存成表格到指定文件夹”的操作：当前环境没有写入的权限/工具，所以文件没有保存。",
    "我无法在当前对话环境中直接写入这个文件夹，所以不能替你实际保存文件。",
    "I cannot write the file to your folder, but here is the CSV.",
    "I don't have file system access in this environment.",
])
def test_bench_denials_are_caught(answer):
    assert denied_capability(answer, WRITE, []) == "write"


@pytest.mark.parametrize("answer", [
    "我不能保存你的密码，请自己登录。",
    "已保存到 report.md。",
    "我可以写入文件，已经存好了。",
    "这个页面无法访问（403），我换了另一个来源。",
    "The table is saved as jobs.csv.",
])
def test_ordinary_answers_pass(answer):
    assert denied_capability(answer, WRITE, []) is None


def test_a_genuine_write_failure_is_not_overruled():
    trace = [{"tool": "write_file", "result": {"ok": False, "error": "Permission denied: /Library/x"}}]
    assert denied_capability("我无法写入这个文件夹：权限被拒绝。", WRITE, trace) is None


def test_no_write_tools_means_no_correction():
    assert denied_capability("我无法把文件写入你的文件夹。", {"web_search"}, []) is None


def test_web_denial_needs_web_tools():
    assert denied_capability("我没有联网能力。", {"web_search"}, []) == "web"
    assert denied_capability("我没有联网能力。", {"write_file"}, []) is None


async def _run(monkeypatch, replies):
    adapter = golden._Recorder(replies)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    result = await tool_loop.run_native(system="S", user_content="save a table", history=[],
                                        emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=golden._resolve)
    return result, adapter


async def test_denial_is_bounced_once_then_the_real_answer_is_kept(monkeypatch):
    result, adapter = await _run(monkeypatch, [golden._Resp("我无法把文件写入你的文件夹，没有写入权限。"),
                                               golden._Resp("已保存到 jobs.csv。")])
    assert result["final"] == "已保存到 jobs.csv。"
    assert "write_file" in adapter.calls[1]["user"] and "Save the deliverable now" in adapter.calls[1]["user"]


async def test_the_correction_happens_only_once_per_turn(monkeypatch):
    second = "我还是无法把文件写入文件夹。"
    result, adapter = await _run(monkeypatch, [golden._Resp("我无法把文件写入你的文件夹。"), golden._Resp(second)])
    assert result["final"] == second and len(adapter.calls) == 2

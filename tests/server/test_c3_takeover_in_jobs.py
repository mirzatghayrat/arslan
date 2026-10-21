"""C3a: `desktop_takeover` is offered only inside background work (card C3).

Its executor refuses it outside a job ("act_in_background", hands_tools), and its own description
says "Background work only", yet a chat turn's tool table carried it. Now only a job's does. Hands'
files are untouched; ③Hands is told.
"""
import sys

from server.orchestrator import arslan
from server.registry import hands_tools
from server.services import background_jobs, task_service


def _mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(hands_tools, "desktop_available", lambda: True)
    monkeypatch.setattr(task_service, "current", lambda: object())


async def test_a_chat_turn_is_not_offered_the_takeover(execution_db, monkeypatch):
    _mac(monkeypatch)
    keys = {t["key"] for t in await arslan._arslan_tools()}
    assert "desktop_click" in keys                  # H3: acting is offered in chat
    assert "desktop_takeover" not in keys


async def test_a_background_job_is_offered_the_takeover(execution_db, monkeypatch):
    _mac(monkeypatch)
    token = background_jobs._inside_job.set("job-1")
    try:
        keys = {t["key"] for t in await arslan._arslan_tools()}
    finally:
        background_jobs._inside_job.reset(token)
    assert "desktop_takeover" in keys

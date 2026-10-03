"""What the Bridge reads for a paired phone (mobile-bridge-protocol §5.3): the conversation
list, a conversation's history with each reply's files, the files a turn made, and one file's
bytes — checked against the reference the phone already holds."""
import base64
import hashlib
from datetime import datetime

import pytest

from server.db.models import ArslanMessage, Run
from server.services import artifact_store


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_store, "root", lambda: tmp_path / "artifacts")
    return tmp_path / "artifacts"


async def _seed(client, rows):
    async with client.db_maker() as db:
        db.add(Run(id=7, conversation_id="trip", user_message="plan"))
        db.add(Run(id=8, conversation_id="trip", user_message="big"))
        for row in rows:
            db.add(row)
        await db.commit()


def _message(id_, cid, role, text, at, run_id=None, display=None):
    return ArslanMessage(id=id_, conversation_id=cid, role=role, content=text, display_content=display,
                         timestamp=datetime.fromisoformat(at), run_id=run_id)


async def test_the_list_is_newest_first_with_protocol_timestamps(client):
    await _seed(client, [
        _message(1, "trip", "user", "Plan a  trip to Kashgar", "2026-10-01T08:00:00"),
        _message(2, "pocket", "user", "remind me", "2026-10-03T09:30:15.123456"),
        _message(3, "trip", "arslan", "Sure", "2026-10-02T08:00:00"),
    ])
    got = (await client.get("/api/v1/phone/conversations")).json()
    assert got == {"conversations": [
        {"id": "pocket", "title": "remind me", "updated_at": "2026-10-03T09:30:15Z"},
        {"id": "trip", "title": "Plan a trip to Kashgar", "updated_at": "2026-10-02T08:00:00Z"},
    ]}
    assert [c["id"] for c in (await client.get("/api/v1/phone/conversations?limit=1")).json()["conversations"]] == ["pocket"]
    assert (await client.get("/api/v1/phone/conversations?limit=0")).status_code == 422


async def test_history_is_the_latest_messages_oldest_first_with_reply_files(client, artifacts):
    item = artifact_store.store_bytes(7, "notes/itinerary.md", b"# Day 1\n")
    artifact_store.store_bytes(8, "huge.bin", b"x")                      # another run's file
    await _seed(client, [
        _message(1, "trip", "user", "old", "2026-10-01T08:00:00"),
        _message(2, "trip", "user", "Plan a trip", "2026-10-01T08:01:00"),
        _message(3, "trip", "arslan", "raw", "2026-10-01T08:02:00", run_id=7, display="Here is the plan"),
        _message(4, "trip", "spawn_summary", "from a helper", "2026-10-01T08:03:00"),
        _message(5, "other", "user", "elsewhere", "2026-10-01T08:04:00"),
    ])
    got = (await client.get("/api/v1/phone/conversations/trip/history?limit=3")).json()
    assert got["conversation_id"] == "trip"
    assert [(m["id"], m["role"], m["text"]) for m in got["messages"]] == [
        ("2", "user", "Plan a trip"), ("3", "assistant", "Here is the plan"), ("4", "assistant", "from a helper")]
    assert got["messages"][1]["ts"] == "2026-10-01T08:02:00Z"
    assert got["messages"][1]["attachments"] == [{
        "id": item["filename"], "name": "itinerary.md", "size": 8, "mime_type": item["media_type"],
        "sha256": hashlib.sha256(b"# Day 1\n").hexdigest()}]
    assert got["messages"][0]["attachments"] == [] and got["messages"][2]["attachments"] == []


async def test_a_turns_files_and_a_files_bytes_match_the_reference(client, artifacts):
    item = artifact_store.store_bytes(7, "report.pdf", b"%PDF-1.7 tiny")
    await _seed(client, [])
    offered = (await client.get("/api/v1/phone/runs/7/files")).json()["files"]
    assert [f["id"] for f in offered] == [item["filename"]]
    got = (await client.get(f"/api/v1/phone/files/{item['filename']}")).json()
    assert got["file"] == offered[0]
    assert base64.b64decode(got["data"]) == b"%PDF-1.7 tiny"
    assert (await client.get("/api/v1/phone/runs/99/files")).status_code == 404


async def test_a_file_that_is_too_big_never_travels(client, artifacts, monkeypatch):
    import server.api.phone as phone
    monkeypatch.setattr(phone, "PHONE_FILE_MAX", 4)
    small = artifact_store.store_bytes(7, "a.txt", b"abcd")
    big = artifact_store.store_bytes(7, "b.txt", b"abcde")
    await _seed(client, [])
    assert [f["id"] for f in (await client.get("/api/v1/phone/runs/7/files")).json()["files"]] == [small["filename"]]
    response = await client.get(f"/api/v1/phone/files/{big['filename']}")
    assert (response.status_code, response.json()["detail"]) == (413, "too_large")


async def test_only_an_intact_artifact_of_a_real_run_is_served(client, artifacts):
    item = artifact_store.store_bytes(7, "a.txt", b"original")
    orphan = artifact_store.store_bytes(42, "b.txt", b"no run row")
    await _seed(client, [])
    for file_id in ("../app.db", "run_7_nothing_here.txt", orphan["filename"], "a.txt"):
        response = await client.get(f"/api/v1/phone/files/{file_id}")
        assert response.status_code == 404, file_id
    (artifacts / item["filename"]).write_bytes(b"tampered")
    response = await client.get(f"/api/v1/phone/files/{item['filename']}")
    assert (response.status_code, response.json()["detail"]) == (404, "file_unavailable")

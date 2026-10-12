"""Files from the iPhone, live conversations and a history that fits one envelope
(mobile-bridge-protocol §5.7, 2026-10-13).

- POST /api/v1/phone/inbox: a file the phone sent lands in the workspace under
  Inbox/iPhone/<date>/<name>, so the agent can open the original with its own tools.
- GET /api/v1/phone/live: the conversations the Bridge keeps a socket open on.
- The history the phone asks for (up to 200 messages) is trimmed from the oldest end so the
  sealed envelope stays under the Bridge's record limit, and says so (`truncated`)."""
import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

import server.api.phone as phone
from server.db.companion_models import ConversationContext
from server.db.models import ArslanMessage
from server.services import background_jobs, phone_reads
from server.services.background_jobs import Job


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    home = tmp_path / "Arslan"
    monkeypatch.setenv("ARSLAN_DEFAULT_WORKSPACE", str(home))
    return home


@pytest.fixture(autouse=True)
def _clean():
    background_jobs._jobs.clear()
    yield
    background_jobs._jobs.clear()


def _upload(name, data, mime="image/jpeg", sha=None):
    return {"name": name, "mime_type": mime, "data": base64.b64encode(data).decode(),
            "sha256": sha or hashlib.sha256(data).hexdigest()}


# ------------------------------------------------------------------ the inbox

async def test_a_file_from_the_phone_lands_in_todays_inbox_folder(client, workspace):
    got = await client.post("/api/v1/phone/inbox", json=_upload("IMG_0042.jpg", b"\xff\xd8jpeg"))
    assert got.status_code == 200
    body = got.json()
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    expected = workspace.resolve() / "Inbox" / "iPhone" / today / "IMG_0042.jpg"
    assert body == {"path": str(expected), "name": "IMG_0042.jpg", "mime_type": "image/jpeg", "size": 6}
    assert expected.read_bytes() == b"\xff\xd8jpeg"


async def test_the_same_name_twice_keeps_both(client, workspace):
    first = (await client.post("/api/v1/phone/inbox", json=_upload("notes.txt", b"one", "text/plain"))).json()
    second = (await client.post("/api/v1/phone/inbox", json=_upload("notes.txt", b"two", "text/plain"))).json()
    third = (await client.post("/api/v1/phone/inbox", json=_upload("notes.txt", b"three", "text/plain"))).json()
    assert [Path(r["path"]).name for r in (first, second, third)] == ["notes.txt", "notes (2).txt", "notes (3).txt"]
    assert Path(first["path"]).read_bytes() == b"one" and Path(second["path"]).read_bytes() == b"two"
    assert second["name"] == "notes (2).txt"


@pytest.mark.parametrize("sent, saved", [
    ("../../etc/passwd", "passwd"),
    ("..\\..\\boot.ini", "boot.ini"),
    ("/abs/path/report.pdf", "report.pdf"),
    ("...hidden", "hidden"),
    ("  spaced  .txt", "spaced  .txt"),
    ("a:b\x00c.txt", "a_b_c.txt"),
    ("", "file"),
    ("..", "file"),
    ("/", "file"),
])
def test_a_name_is_one_plain_file_name(sent, saved):
    assert phone.inbox_name(sent) == saved


def test_a_long_name_is_capped_and_keeps_its_extension():
    name = phone.inbox_name("x" * 400 + ".pdf")
    assert len(name) <= phone.INBOX_NAME_MAX and name.endswith(".pdf") and name.startswith("xxx")
    assert len(phone.inbox_name("y" * 400)) <= phone.INBOX_NAME_MAX


async def test_a_path_in_the_name_never_leaves_the_inbox(client, workspace):
    body = (await client.post("/api/v1/phone/inbox", json=_upload("../../../escape.sh", b"#!", "text/x-sh"))).json()
    inbox = workspace.resolve() / "Inbox" / "iPhone"
    assert Path(body["path"]).parent.parent == inbox and Path(body["path"]).name == "escape.sh"
    assert not (workspace.parent / "escape.sh").exists()


async def test_too_big_wrong_hash_or_not_base64_is_refused_and_nothing_is_written(client, workspace, monkeypatch):
    assert phone.PHONE_FILE_MAX == 20 * 1024 * 1024, "one CloudKit asset (§4.6)"
    monkeypatch.setattr(phone, "PHONE_FILE_MAX", 4)
    assert (await client.post("/api/v1/phone/inbox", json=_upload("big.bin", b"12345"))).status_code == 413
    assert (await client.post("/api/v1/phone/inbox", json=_upload("a.bin", b"1234"))).status_code == 200
    bad_hash = _upload("b.bin", b"12", sha="0" * 64)
    assert (await client.post("/api/v1/phone/inbox", json=bad_hash)).status_code == 422
    not_b64 = {**_upload("c.bin", b"12"), "data": "not base64!!"}
    assert (await client.post("/api/v1/phone/inbox", json=not_b64)).status_code == 422
    saved = [p.name for p in (workspace / "Inbox").rglob("*") if p.is_file()]
    assert saved == ["a.bin"]


async def test_no_workspace_means_busy_not_somewhere_else(client, workspace, monkeypatch):
    async def gone(_db):
        return None
    monkeypatch.setattr(phone.settings_service, "workspace_dir", gone)
    assert (await client.post("/api/v1/phone/inbox", json=_upload("a.txt", b"x", "text/plain"))).status_code == 503
    assert not (workspace / "Inbox").exists()


# ------------------------------------------------------------------ live conversations

def _message(id_, cid, role, text, at, source=None):
    return ArslanMessage(id=id_, conversation_id=cid, role=role, content=text, source=source,
                         timestamp=datetime.fromisoformat(at))


async def test_live_is_the_newest_conversations_plus_running_jobs_never_a_temporary_one(client):
    async with client.db_maker() as db:
        for n in range(5):
            db.add(_message(n + 1, f"c{n}", "user", f"hi {n}", f"2026-10-0{n + 1}T08:00:00"))
        db.add(_message(10, "secret", "user", "off the record", "2026-10-09T08:00:00"))
        db.add(ConversationContext(id="secret", temporary=True))
        await db.commit()
    background_jobs._jobs["j1"] = Job("j1", "c0", "long job", [], phase="running")
    background_jobs._jobs["j2"] = Job("j2", "c4", "also newest", [], phase="running")
    background_jobs._jobs["j3"] = Job("j3", "c1", "done", [], phase="finished", outcome="done")
    got = (await client.get("/api/v1/phone/live?limit=2")).json()
    assert got == {"conversation_ids": ["c4", "c3", "c0"]}, \
        "newest two (the temporary one skipped), then a running job's, each once; a finished job's is not kept"
    assert (await client.get("/api/v1/phone/live?limit=0")).status_code == 422
    assert len((await client.get("/api/v1/phone/live")).json()["conversation_ids"]) == 5


# ------------------------------------------------------------------ history: who typed it, and one envelope

async def test_history_says_whether_the_phone_or_the_mac_typed_each_message(client):
    async with client.db_maker() as db:
        db.add(_message(1, "c", "user", "from the phone", "2026-10-01T08:00:00", source="phone"))
        db.add(_message(2, "c", "arslan", "answer", "2026-10-01T08:01:00"))
        db.add(_message(3, "c", "user", "typed on the Mac", "2026-10-01T08:02:00"))
        await db.commit()
    got = (await client.get("/api/v1/phone/conversations/c/history?limit=200")).json()
    assert [(m["id"], m.get("source")) for m in got["messages"]] == [("1", "phone"), ("2", None), ("3", "mac")]
    assert "truncated" not in got, "nothing was left out"


def _size(messages):
    return len(json.dumps({"conversation_id": "c", "messages": messages}, ensure_ascii=False,
                          separators=(",", ":")).encode())


def test_a_history_over_budget_loses_its_oldest_messages_first():
    messages = [{"id": str(n), "role": "user", "text": "字" * 1000, "ts": "t", "attachments": []} for n in range(400)]
    kept, truncated = phone_reads.fit_history("c", messages)
    assert truncated is True
    assert kept == messages[-len(kept):], "the newest ones, in order"
    assert _size(kept) <= phone_reads.HISTORY_BUDGET < _size(messages[-len(kept) - 1:])
    small = messages[:3]
    assert phone_reads.fit_history("c", small) == (small, False)


def test_one_message_bigger_than_the_budget_is_cut_not_dropped():
    huge = [{"id": "9", "role": "assistant", "text": "a" * (phone_reads.HISTORY_BUDGET * 2), "ts": "t",
             "attachments": []}]
    kept, truncated = phone_reads.fit_history("c", huge)
    assert truncated is True and len(kept) == 1 and kept[0]["id"] == "9"
    assert _size(kept) <= phone_reads.HISTORY_BUDGET and kept[0]["text"].endswith("…")


def test_the_budget_fits_one_sealed_envelope():
    # A body of B bytes travels as base64(ChaCha20-Poly1305(envelope)) inside the packet JSON:
    # ~4/3 of it plus headers must stay under the Bridge's 800,000-byte record (Wire.maxSealedBytes).
    assert phone_reads.HISTORY_BUDGET * 4 / 3 + 4_000 < 800_000


async def test_the_history_route_trims_and_says_so(client, monkeypatch):
    monkeypatch.setattr(phone_reads, "HISTORY_BUDGET", 2_000)
    async with client.db_maker() as db:
        for n in range(1, 41):
            db.add(_message(n, "c", "user", f"message number {n} " + "x" * 80, f"2026-10-01T08:{n:02d}:00"))
        await db.commit()
    got = (await client.get("/api/v1/phone/conversations/c/history?limit=200")).json()
    assert got["truncated"] is True
    ids = [int(m["id"]) for m in got["messages"]]
    assert ids == list(range(ids[0], 41)) and ids[0] > 1, "the newest, oldest first, the start cut off"
    assert _size(got["messages"]) <= 2_000

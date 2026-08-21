"""The enrolment endpoints (spec P3c).

Enrolment lands here and nowhere else. The proposal card's button is what calls
POST, so this is the only code in the product that creates a node — which is
what makes "a person did this deliberately" a property of the architecture.
"""
import pytest

from server.services import ssh_exec, ssh_nodes

KEY = "192.168.1.8 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
FP = "256 SHA256:aaaa (ED25519)"
OTHER_FP = "256 SHA256:zzzz (ED25519)"


@pytest.fixture
def probe_ok(monkeypatch):
    async def _probe(host):
        return {"ok": True, "host": host, "keys": [KEY], "fingerprints": [FP]}
    monkeypatch.setattr(ssh_exec, "probe", _probe)


async def _enable(client):
    await client.put("/api/v1/settings", json={"ssh_enabled": "true"})


async def test_enrolling_stores_the_machine(client, probe_ok):
    await _enable(client)
    r = await client.post("/api/v1/ssh-nodes",
                          json={"name": "studio", "host": "192.168.1.8",
                                "user": "someone", "fingerprints": [FP]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "studio" and body["host"] == "192.168.1.8"
    listed = (await client.get("/api/v1/ssh-nodes")).json()["nodes"]
    assert [n["name"] for n in listed] == ["studio"]


async def test_a_machine_presenting_a_different_key_is_refused(client, probe_ok):
    """What the user approved was a specific machine — the one whose fingerprint
    was on the card. Between the card and the click, the address could be
    answered by something else; trusting whatever replies would make the
    fingerprint decorative."""
    await _enable(client)
    r = await client.post("/api/v1/ssh-nodes",
                          json={"name": "studio", "host": "192.168.1.8",
                                "user": "someone", "fingerprints": [OTHER_FP]})
    assert r.status_code == 409
    assert "different host key" in r.json()["detail"]
    assert (await client.get("/api/v1/ssh-nodes")).json()["nodes"] == []


async def test_enrolling_is_refused_while_ssh_is_off(client, probe_ok):
    r = await client.post("/api/v1/ssh-nodes",
                          json={"name": "studio", "host": "192.168.1.8",
                                "user": "someone", "fingerprints": [FP]})
    assert r.status_code == 400
    assert (await client.get("/api/v1/ssh-nodes")).json()["nodes"] == []


@pytest.mark.parametrize("body,status", [
    ({"name": "studio", "host": "nas.local", "user": "someone"}, 400),
    ({"name": "studio", "host": "192.168.1.8", "user": "Bad Name"}, 400),
    ({"name": "", "host": "192.168.1.8", "user": "someone"}, 400),
])
async def test_bad_input_is_refused(client, probe_ok, body, status):
    await _enable(client)
    r = await client.post("/api/v1/ssh-nodes", json=body)
    assert r.status_code == status
    assert (await client.get("/api/v1/ssh-nodes")).json()["nodes"] == []


async def test_the_same_name_cannot_be_used_twice(client, probe_ok):
    await _enable(client)
    first = {"name": "studio", "host": "192.168.1.8", "user": "someone",
             "fingerprints": [FP]}
    assert (await client.post("/api/v1/ssh-nodes", json=first)).status_code == 200
    again = dict(first, host="192.168.1.9")
    assert (await client.post("/api/v1/ssh-nodes", json=again)).status_code == 409


async def test_revoking_removes_it(client, probe_ok):
    await _enable(client)
    node = (await client.post("/api/v1/ssh-nodes",
                              json={"name": "studio", "host": "192.168.1.8",
                                    "user": "someone", "fingerprints": [FP]})).json()
    r = await client.delete(f"/api/v1/ssh-nodes/{node['id']}")
    assert r.status_code == 200
    assert (await client.get("/api/v1/ssh-nodes")).json()["nodes"] == []


async def test_revoking_something_that_is_not_there_says_so(client):
    await _enable(client)
    assert (await client.delete("/api/v1/ssh-nodes/999")).status_code == 404


async def test_the_audit_endpoint_returns_what_ran(client):
    await _enable(client)
    from server.db import session as db_session
    async with db_session.AsyncSessionLocal() as s:
        await ssh_nodes.record(s, host="192.168.1.8", username="someone",
                               command="git", argv=["status"],
                               result={"ok": True, "exit_code": 0})
    entries = (await client.get("/api/v1/ssh-audit")).json()["entries"]
    assert len(entries) == 1
    assert entries[0]["host"] == "192.168.1.8" and entries[0]["ok"] is True
    assert "status" in entries[0]["command"]

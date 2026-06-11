"""PUT /spawns/{id}/equipment — declarative replace of user-managed grants."""
import pytest

from server.db.models import SpawnCapability


async def _seed(client) -> int:
    await client.post("/api/v1/_test/seed_spawn", json={"name": "researcher"})
    return (await client.get("/api/v1/spawns")).json()[0]["id"]


async def _keys(client):
    """Derive assignable/non-assignable keys from the registry API (no hardcoding)."""
    cat = (await client.get("/api/v1/registry")).json()
    ts = [t["key"] for t in cat["toolsets"] if t["assignable"]]
    sk = [s["key"] for s in cat["skills"] if s["assignable"]]
    bad = [t["key"] for t in cat["toolsets"] if not t["assignable"]]
    assert len(ts) >= 2 and sk and bad, "seed catalog must provide these"
    return ts, sk, bad


@pytest.mark.asyncio
async def test_put_equipment_replaces_user_grants(client):
    sid = await _seed(client)
    ts, sk, _ = await _keys(client)
    resp = await client.put(
        f"/api/v1/spawns/{sid}/equipment", json={"toolsets": [ts[0]], "skills": [sk[0]]}
    )
    assert resp.status_code == 200
    eq = resp.json()["equipment"]
    assert [t["key"] for t in eq["toolsets"]] == [ts[0]]
    assert [s["key"] for s in eq["skills"]] == [sk[0]]
    assert all(t["granted_by"] == "user" for t in eq["toolsets"] + eq["skills"])


@pytest.mark.asyncio
async def test_put_equipment_empty_clears(client):
    sid = await _seed(client)
    resp = await client.put(f"/api/v1/spawns/{sid}/equipment", json={"toolsets": [], "skills": []})
    assert resp.status_code == 200
    assert resp.json()["equipment"] == {"toolsets": [], "skills": []}


@pytest.mark.asyncio
async def test_put_equipment_non_assignable_is_422_all_or_nothing(client):
    sid = await _seed(client)
    ts, _, bad = await _keys(client)
    before = (await client.get(f"/api/v1/spawns/{sid}")).json()["equipment"]
    resp = await client.put(
        f"/api/v1/spawns/{sid}/equipment", json={"toolsets": [ts[0], bad[0]], "skills": []}
    )
    assert resp.status_code == 422
    assert bad[0] in resp.json()["detail"]
    after = (await client.get(f"/api/v1/spawns/{sid}")).json()["equipment"]
    assert after == before  # no partial write


@pytest.mark.asyncio
async def test_put_equipment_unknown_spawn_404(client):
    resp = await client.put("/api/v1/spawns/9999/equipment", json={"toolsets": [], "skills": []})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_put_equipment_preserves_temporary_grants(client):
    sid = await _seed(client)
    ts, _, _ = await _keys(client)
    async with client.db_maker() as s:
        s.add(SpawnCapability(spawn_id=sid, kind="toolset", ref_key=ts[1],
                              grant="temporary", granted_by="escalation", expires_turn=99))
        await s.commit()
    resp = await client.put(f"/api/v1/spawns/{sid}/equipment",
                            json={"toolsets": [ts[0]], "skills": []})
    assert resp.status_code == 200
    by_key = {t["key"]: t for t in resp.json()["equipment"]["toolsets"]}
    assert by_key[ts[1]]["grant"] == "temporary"
    assert by_key[ts[1]]["granted_by"] == "escalation"
    assert by_key[ts[1]]["expires_turn"] == 99


@pytest.mark.asyncio
async def test_put_equipment_idempotent(client):
    sid = await _seed(client)
    ts, sk, _ = await _keys(client)
    body = {"toolsets": [ts[0]], "skills": [sk[0]]}
    first = await client.put(f"/api/v1/spawns/{sid}/equipment", json=body)
    assert first.status_code == 200
    second = await client.put(f"/api/v1/spawns/{sid}/equipment", json=body)
    assert second.status_code == 200
    assert second.json()["equipment"] == first.json()["equipment"]


@pytest.mark.asyncio
async def test_put_equipment_dedupes_request_keys(client):
    sid = await _seed(client)
    ts, _, _ = await _keys(client)
    resp = await client.put(f"/api/v1/spawns/{sid}/equipment",
                            json={"toolsets": [ts[0], ts[0]], "skills": []})
    assert resp.status_code == 200
    assert [t["key"] for t in resp.json()["equipment"]["toolsets"]] == [ts[0]]


@pytest.mark.asyncio
async def test_put_equipment_promotes_temporary_grant(client):
    sid = await _seed(client)
    ts, _, _ = await _keys(client)
    async with client.db_maker() as s:
        s.add(SpawnCapability(spawn_id=sid, kind="toolset", ref_key=ts[0],
                              grant="temporary", granted_by="escalation", expires_turn=99))
        await s.commit()
    resp = await client.put(f"/api/v1/spawns/{sid}/equipment",
                            json={"toolsets": [ts[0]], "skills": []})
    assert resp.status_code == 200
    rows = [t for t in resp.json()["equipment"]["toolsets"] if t["key"] == ts[0]]
    assert len(rows) == 1
    assert rows[0]["grant"] == "permanent"
    assert rows[0]["granted_by"] == "user"

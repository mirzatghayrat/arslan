"""Settings › iPhone (docs/specs/mobile-bridge-protocol.md §6.1): the connected Bridge, paired
phones, a new pairing code, accepting or declining a request, revoking a phone. Behind the
API token like every setting; accepting is the user's click in Arslan's window."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.auth import require_auth
from server.services.phone_bridge import BridgeUnavailable, hub

router = APIRouter(dependencies=[Depends(require_auth)])


class Decision(BaseModel):
    accept: bool


@router.get("/phone")
async def phone_status():
    return hub.status()


@router.post("/phone/pairing")
async def new_pairing_code():
    try:
        return await hub.request_code()
    except BridgeUnavailable:
        raise HTTPException(503, "bridge_unavailable") from None


@router.post("/phone/requests/{request_id}")
async def decide(request_id: str, body: Decision):
    try:
        if not await hub.decide(request_id, body.accept):
            raise HTTPException(404, "request_not_found")
    except BridgeUnavailable:
        raise HTTPException(503, "bridge_unavailable") from None
    return {"request_id": request_id, "accepted": body.accept}


@router.delete("/phone/devices/{device_id}")
async def revoke(device_id: str):
    try:
        if not await hub.revoke(device_id):
            raise HTTPException(404, "device_not_found")
    except BridgeUnavailable:
        raise HTTPException(503, "bridge_unavailable") from None
    return {"device_id": device_id, "revoked": True}

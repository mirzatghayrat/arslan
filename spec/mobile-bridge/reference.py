"""Reference implementation of the Arslan mobile bridge wire format (protocol v1).

The executable form of docs/specs/mobile-bridge-protocol.md §4–§6, used to generate and
check the shared vectors in spec/mobile-bridge/vectors/. It is an independent oracle
(Python `cryptography`), not the Mac Bridge (Swift) nor the iOS BridgeKit (Swift): all
three must agree on the vectors. Test keys only; nothing here runs in the app.
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct
from collections import OrderedDict
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PROTOCOL = "arslan-bridge/v1"
VERSION = 1
KINDS = ("msg", "ack", "control")
MAX_SEALED_BYTES = 800_000          # the whole SecurePacket JSON in Envelope.sealed
MAX_FILE_BYTES = 20 * 1024 * 1024
REPLAY_WINDOW = 1024


class BridgeError(Exception):
    """A packet or payload the receiver must drop. `code` is the protocol error code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def unb64(text: str, size: int | None = None) -> bytes:
    try:
        raw = base64.b64decode(text, validate=True)
    except (ValueError, TypeError):
        raise BridgeError("malformed") from None
    if size is not None and len(raw) != size:
        raise BridgeError("malformed")
    return raw


def lp(value: str) -> bytes:
    raw = value.encode()
    return struct.pack(">I", len(raw)) + raw


def header_bytes(header: dict, *, include_asset: bool = True) -> bytes:
    """§4.3: twelve length-prefixed UTF-8 fields in a fixed order. No JSON canonicalisation."""
    return b"".join(lp(v) for v in (
        PROTOCOL, str(header["v"]), header["id"].lower(), header["from"], header["to"], str(header["seq"]),
        header["kind"], header["ephemeral"], (header.get("pairing_id") or "").lower(),
        (header.get("asset_hash") or "") if include_asset else "", header.get("signing_key") or "",
        "1" if header.get("notify") else "0"))


def derive(shared: bytes, salt: bytes, purpose: str, sender: str, recipient: str) -> bytes:
    info = f"{PROTOCOL}/{purpose}".encode() + lp(sender) + lp(recipient)
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(shared)


def public_exchange(private: bytes) -> bytes:
    return x25519.X25519PrivateKey.from_private_bytes(private).public_key().public_bytes_raw()


def public_signing(private: bytes) -> bytes:
    return ed25519.Ed25519PrivateKey.from_private_bytes(private).public_key().public_bytes_raw()


def encode_plaintext(envelope: dict) -> bytes:
    """Senders write compact UTF-8 JSON (the vectors use sorted keys); receivers never
    depend on key order or whitespace."""
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


@dataclass
class Sealed:
    packet: dict
    header_bytes: bytes
    plaintext: bytes
    asset: bytes | None = None


def seal(envelope: dict, *, kind: str, notify: bool, sender_signing: bytes, recipient_exchange_public: bytes,
         ephemeral: bytes, nonce: bytes, psk: bytes = b"", pairing_id: str | None = None,
         signing_key_in_header: bool = False, asset: bytes | None = None, asset_nonce: bytes | None = None) -> Sealed:
    """§4.4–§4.6. `ephemeral` and nonces are inputs so vectors are reproducible; a real
    sender draws them fresh for every new message and reuses them only for a retry."""
    if kind not in KINDS:
        raise BridgeError("malformed")
    eph = x25519.X25519PrivateKey.from_private_bytes(ephemeral)
    header = {"v": VERSION, "id": envelope["id"], "from": envelope["from"], "to": envelope["to"],
              "seq": envelope["seq"], "kind": kind, "ephemeral": b64(eph.public_key().public_bytes_raw()),
              "notify": notify}
    if pairing_id:
        header["pairing_id"] = pairing_id
    if signing_key_in_header:
        header["signing_key"] = b64(public_signing(sender_signing))
    shared = eph.exchange(x25519.X25519PublicKey.from_public_bytes(recipient_exchange_public))
    sealed_asset = None
    if asset is not None:
        if len(asset) > MAX_FILE_BYTES:
            raise BridgeError("too_large")
        key = derive(shared, psk, "asset", header["from"], header["to"])
        sealed_asset = asset_nonce + ChaCha20Poly1305(key).encrypt(asset_nonce, asset, header_bytes(header, include_asset=False))
        header["asset_hash"] = b64(hashlib.sha256(sealed_asset).digest())
    hb = header_bytes(header)
    plain = encode_plaintext(envelope)
    body = nonce + ChaCha20Poly1305(derive(shared, psk, "message", header["from"], header["to"])).encrypt(nonce, plain, hb)
    signature = ed25519.Ed25519PrivateKey.from_private_bytes(sender_signing).sign(hb + body)
    packet = {"header": header, "sealed": b64(body), "signature": b64(signature)}
    if len(json.dumps(packet).encode()) > MAX_SEALED_BYTES:
        raise BridgeError("too_large")
    return Sealed(packet, hb, plain, sealed_asset)


def open_packet(packet: dict, *, recipient_id: str, recipient_exchange: bytes, sender_signing_public: bytes,
                psk: bytes = b"", asset: bytes | None = None) -> tuple[dict, bytes | None]:
    """§4.7, in this order: shape → recipient → signature → decrypt → header/plaintext
    agreement → asset. Raises BridgeError with the protocol code; never returns partial data."""
    try:
        header, sealed, signature = packet["header"], unb64(packet["sealed"]), unb64(packet["signature"], 64)
        if header["v"] != VERSION:
            raise BridgeError("unsupported_version")
        if header["kind"] not in KINDS or not isinstance(header["seq"], int) or not 0 < header["seq"] < 2**63:
            raise BridgeError("malformed")
        ephemeral = unb64(header["ephemeral"], 32)
    except (KeyError, TypeError):
        raise BridgeError("malformed") from None
    if header["to"] != recipient_id:
        raise BridgeError("not_for_me")
    if len(sealed) < 12 + 16:
        raise BridgeError("malformed")
    hb = header_bytes(header)
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(sender_signing_public).verify(signature, hb + sealed)
    except InvalidSignature:
        raise BridgeError("bad_signature") from None
    shared = x25519.X25519PrivateKey.from_private_bytes(recipient_exchange).exchange(
        x25519.X25519PublicKey.from_public_bytes(ephemeral))
    try:
        plain = ChaCha20Poly1305(derive(shared, psk, "message", header["from"], header["to"])).decrypt(
            sealed[:12], sealed[12:], hb)
    except InvalidTag:
        raise BridgeError("decrypt_failed") from None
    try:
        envelope = json.loads(plain)
    except ValueError:
        raise BridgeError("malformed") from None
    for key in ("v", "from", "to", "seq"):
        if envelope.get(key) != header[key]:
            raise BridgeError("header_mismatch")
    if str(envelope.get("id", "")).lower() != header["id"].lower():
        raise BridgeError("header_mismatch")
    if kind_of(envelope.get("type", "")) != header["kind"]:
        raise BridgeError("header_mismatch")
    opened_asset = None
    if header.get("asset_hash"):
        if asset is None or b64(hashlib.sha256(asset).digest()) != header["asset_hash"]:
            raise BridgeError("asset_mismatch")
        try:
            opened_asset = ChaCha20Poly1305(derive(shared, psk, "asset", header["from"], header["to"])).decrypt(
                asset[:12], asset[12:], header_bytes(header, include_asset=False))
        except InvalidTag:
            raise BridgeError("asset_mismatch") from None
        body = envelope.get("body") or {}
        if envelope.get("type") != "file.offer" or body.get("size") != len(opened_asset) \
                or body.get("sha256") != hashlib.sha256(opened_asset).hexdigest():
            raise BridgeError("asset_mismatch")
    return envelope, opened_asset


CONTROL_TYPES = {"pair.request", "pair.accept", "pair.reject", "hello", "device.revoked"}


def kind_of(message_type: str) -> str:
    """§5.1: the clear-text coarse kind each message type travels under."""
    if message_type == "ack":
        return "ack"
    return "control" if message_type in CONTROL_TYPES else "msg"


TERMINAL_JOB_STATES = {"done", "partial", "stuck", "stopped"}


def should_notify(envelope: dict) -> bool:
    """§5.2: the one clear-text bit that asks for a user-visible alert."""
    t, body = envelope.get("type"), envelope.get("body") or {}
    if t in ("approval.request", "device.revoked", "error", "approval.result"):
        return t != "approval.result" or body.get("outcome") in ("failed", "expired")
    if t == "chat.event":
        return body.get("kind") == "error" or (body.get("kind") == "message" and body.get("final") is True)
    if t == "job.event":
        return body.get("state") in TERMINAL_JOB_STATES
    return False


@dataclass
class ReplayWindow:
    """§4.8: per sender, the last REPLAY_WINDOW sequence numbers. Out-of-order arrival is
    fine; a repeat, or anything at or below the window's lower edge, is dropped."""
    size: int = REPLAY_WINDOW
    seen: OrderedDict = field(default_factory=OrderedDict)
    highest: int = 0

    def accept(self, seq: int) -> bool:
        if seq in self.seen or seq <= self.highest - self.size:
            return False
        self.seen[seq] = True
        self.highest = max(self.highest, seq)
        for old in [s for s in self.seen if s <= self.highest - self.size]:
            del self.seen[old]
        return True


# -- pairing QR (§3.1) ---------------------------------------------------------

QR_SCHEME = "arslan://pair?payload="
QR_MAX_BYTES = 8192
QR_MAX_VALIDITY_S = 600
QR_CLOCK_SKEW_S = 30
ZONE = "ArslanBridge"


def encode_pair_uri(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return QR_SCHEME + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_pair_uri(uri: str, *, now: float, container_id: str) -> dict:
    """The phone's checks on a scanned code. `now` is Unix seconds."""
    from datetime import datetime
    from urllib.parse import parse_qs, urlsplit
    if len(uri.encode()) > QR_MAX_BYTES:
        raise BridgeError("too_large")
    parts = urlsplit(uri)
    query = parse_qs(parts.query, keep_blank_values=True)
    if parts.scheme != "arslan" or parts.netloc != "pair" or parts.path not in ("", "/") \
            or list(query) != ["payload"] or len(query["payload"]) != 1:
        raise BridgeError("malformed")
    text = query["payload"][0]
    try:
        payload = json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
    except ValueError:
        raise BridgeError("malformed") from None
    try:
        if payload["v"] != VERSION:
            raise BridgeError("unsupported_version")
        for key in ("mac_device_id", "device_name"):
            if not 1 <= len(payload[key].encode()) <= (128 if key == "mac_device_id" else 256):
                raise BridgeError("malformed")
        for key in ("signing_public_key", "exchange_public_key", "pairing_key"):
            unb64(payload[key], 32)
        import uuid
        if str(uuid.UUID(payload["pairing_id"])) != payload["pairing_id"].lower():
            raise BridgeError("malformed")
        issued = datetime.fromisoformat(payload["issued_at"].replace("Z", "+00:00")).timestamp()
        expires = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00")).timestamp()
    except (KeyError, TypeError, AttributeError, ValueError):
        raise BridgeError("malformed") from None
    if payload["container_id"] != container_id:
        raise BridgeError("wrong_container")
    if payload["zone"] != ZONE:
        raise BridgeError("malformed")
    if expires <= issued or expires - issued > QR_MAX_VALIDITY_S or issued > now + QR_CLOCK_SKEW_S:
        raise BridgeError("pairing_invalid")
    if now >= expires:
        raise BridgeError("pairing_expired")
    return payload


# -- plaintext bodies (§5.3) ------------------------------------------------------

# Required body fields per type ("?" suffix = optional). The table is the spec's §5.3
# in machine form; the vectors' message examples are checked against it.
BODY_FIELDS: dict[str, tuple[str, ...]] = {
    "pair.request": ("device_name", "signing_public_key", "exchange_public_key"),
    "pair.accept": ("phone_device_id", "mac_device_id", "device_name", "signing_public_key", "exchange_public_key"),
    "pair.reject": ("reason",),
    "hello": ("app_version", "protocol_version", "capabilities"),
    "ack": ("ids",),
    "status.snapshot": ("presence", "mascot", "device_name", "last_seen", "jobs", "waiting_approvals",
                        "high_risk_mac_only", "activity?"),
    "conversations.list": ("limit?",),
    "conversations.result": ("conversations",),
    "chat.history": ("conversation_id", "limit"),
    "chat.history.result": ("conversation_id", "messages"),
    "chat.send": ("conversation_id?", "text", "attachments", "client_msg_id"),
    "chat.event": ("conversation_id", "kind", "message_id", "text", "final", "job_id?", "run_id?"),
    "job.event": ("id", "conversation_id", "state", "title", "current_step", "completed", "total", "plan",
                  "summary?", "files", "run_id?", "origin?"),
    "approval.request": ("approval_id", "action", "target", "risk", "task_id", "task_title", "expires_at"),
    "approval.answer": ("approval_id", "decision", "auth", "ts"),
    "approval.result": ("approval_id", "outcome", "detail?"),
    "file.offer": ("id", "name", "size", "mime_type", "sha256"),
    "file.get": ("file_id",),
    "run.get": ("run_id",),
    "run.result": ("run_id", "conversation_id", "title", "state", "started_at", "duration_ms", "total", "steps", "files"),
    "task.start": ("goal", "criteria?", "client_task_id"),
    "task.started": ("conversation_id", "job_id", "client_task_id"),
    "task.stop": ("job_id", "conversation_id?"),
    "device.revoked": ("reason",),
    "error": ("code", "message", "related_id?"),
}


def check_body(envelope: dict) -> None:
    fields = BODY_FIELDS.get(envelope.get("type", ""))
    if fields is None:
        raise BridgeError("unknown_type")
    body = envelope.get("body")
    if not isinstance(body, dict):
        raise BridgeError("malformed")
    required = {f for f in fields if not f.endswith("?")}
    allowed = required | {f[:-1] for f in fields if f.endswith("?")}
    if not required <= set(body) or not set(body) <= allowed:
        raise BridgeError("malformed")
    if envelope["type"] == "approval.answer":
        expected_auth = "faceid" if body["decision"] == "approve" else "none"
        if body["decision"] not in ("approve", "deny") or body["auth"] != expected_auth:
            raise BridgeError("malformed")

"""Write spec/mobile-bridge/vectors/*.json from the reference implementation.

    .venv/bin/python spec/mobile-bridge/make_vectors.py

Deterministic: every key, nonce and ephemeral key is a fixed TEST input (never use them on
a device). tests/test_mobile_bridge_vectors.py regenerates and compares, so the committed
files cannot drift from the reference. The first four crypto vectors are byte-identical to
the iOS proposal's (arslan-ios BridgeKit SecurityVectors, 2026-10-03).
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reference as r  # noqa: E402

CONTRACT = "arslan-bridge-v1"
OUT = HERE / "vectors"


def identity(name: str, offset: int) -> dict:
    return {"deviceID": name, "signingKey": r.b64(bytes(range(offset, offset + 32))),
            "exchangeKey": r.b64(bytes(range(offset + 32, offset + 64))), "storageKey": r.b64(bytes([0xAA]) * 32)}


PHONE, MAC = identity("iphone-vector", 0), identity("mac-vector", 64)
EPHEMERAL = bytes(range(160, 192))
NONCE, ASSET_NONCE = bytes(range(12)), bytes(range(12, 24))
PSK = bytes([0xD3]) * 32
PAIRING_ID = "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC"
ID = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
TS = "2026-10-03T00:00:00Z"
FILE_DATA = b"Independent encrypted result fixture\n"


def raw(device: dict, key: str) -> bytes:
    return base64.b64decode(device[key])


def envelope(sender: dict, recipient: dict, type_: str, body: dict, seq: int = 42, id_: str = ID) -> dict:
    return {"v": 1, "id": id_, "seq": seq, "ts": TS, "from": sender["deviceID"], "to": recipient["deviceID"],
            "type": type_, "body": body}


def crypto_vector(name: str, sender: dict, recipient: dict, env: dict, *, pair: bool = False, asset: bytes | None = None,
                  signing_key_in_header: bool = False, note: str = "") -> dict:
    sealed = r.seal(env, kind=r.kind_of(env["type"]), notify=r.should_notify(env), sender_signing=raw(sender, "signingKey"),
                    recipient_exchange_public=r.public_exchange(raw(recipient, "exchangeKey")), ephemeral=EPHEMERAL,
                    nonce=NONCE, psk=PSK if pair else b"", pairing_id=PAIRING_ID if pair else None,
                    signing_key_in_header=signing_key_in_header, asset=asset, asset_nonce=ASSET_NONCE if asset else None)
    out = {"contract": CONTRACT, "name": name, "note": note, "sender": sender, "recipient": recipient,
           "ephemeral_private": r.b64(EPHEMERAL), "nonce": r.b64(NONCE), "psk": r.b64(PSK if pair else b""),
           "plaintext": r.b64(sealed.plaintext), "header_bytes": r.b64(sealed.header_bytes), "packet": sealed.packet}
    if asset is not None:
        out.update(asset=r.b64(sealed.asset), asset_plaintext=r.b64(asset), asset_nonce=r.b64(ASSET_NONCE))
    return out


def positives() -> list[dict]:
    hello = {"app_version": "0.1.0", "protocol_version": 1, "capabilities": ["cloudkit", "files"]}
    file_body = {"id": "vector-file", "name": "result.txt", "size": len(FILE_DATA), "mime_type": "text/plain",
                 "sha256": hashlib.sha256(FILE_DATA).hexdigest()}
    pair_body = {"device_name": "Vector iPhone", "signing_public_key": r.b64(r.public_signing(raw(PHONE, "signingKey"))),
                 "exchange_public_key": r.b64(r.public_exchange(raw(PHONE, "exchangeKey")))}
    accept_body = {"phone_device_id": PHONE["deviceID"], "mac_device_id": MAC["deviceID"], "device_name": "Vector Mac",
                   "signing_public_key": r.b64(r.public_signing(raw(MAC, "signingKey"))),
                   "exchange_public_key": r.b64(r.public_exchange(raw(MAC, "exchangeKey")))}
    approval = {"approval_id": "appr-1", "action": "Delete 3 files", "target": "~/Arslan/old", "risk": "delete",
                "task_id": "task-1", "task_title": "Tidy downloads", "expires_at": "2026-10-03T00:05:00Z"}
    return [
        crypto_vector("phone-message", PHONE, MAC, envelope(PHONE, MAC, "chat.send", {
            "text": "Vector request", "attachments": [], "client_msg_id": "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB"}),
            note="iOS proposal vector, unchanged"),
        crypto_vector("mac-message", MAC, PHONE, envelope(MAC, PHONE, "chat.event", {
            "conversation_id": "pocket", "kind": "message", "message_id": "reply-1", "text": "Vector reply",
            "final": True}), note="iOS proposal vector, unchanged; a final reply sets notify"),
        crypto_vector("pair-request", PHONE, MAC, envelope(PHONE, MAC, "pair.request", pair_body), pair=True,
                      signing_key_in_header=True, note="iOS proposal vector, unchanged; the pairing key is the HKDF salt"),
        crypto_vector("file-asset", MAC, PHONE, envelope(MAC, PHONE, "file.offer", file_body), asset=FILE_DATA,
                      note="iOS proposal vector, unchanged; the encrypted file's sha256 is bound in the header"),
        crypto_vector("pair-accept", MAC, PHONE, envelope(MAC, PHONE, "pair.accept", accept_body, seq=1), pair=True,
                      note="the Mac's answer, under the same pairing_id and salt"),
        crypto_vector("hello", PHONE, MAC, envelope(PHONE, MAC, "hello", hello, seq=43)),
        crypto_vector("ack", MAC, PHONE, envelope(MAC, PHONE, "ack", {"ids": [ID.lower()]}, seq=2,
                                                     id_="DDDDDDDD-DDDD-4DDD-8DDD-DDDDDDDDDDDD"),
                      note="kind ack, notify 0"),
        crypto_vector("approval-request", MAC, PHONE, envelope(MAC, PHONE, "approval.request", approval, seq=3),
                      note="notify 1"),
        crypto_vector("approval-answer", PHONE, MAC, envelope(PHONE, MAC, "approval.answer", {
            "approval_id": "appr-1", "decision": "approve", "auth": "faceid", "ts": TS}, seq=44)),
        crypto_vector("job-progress", MAC, PHONE, envelope(MAC, PHONE, "job.event", {
            "id": "job-1", "conversation_id": "pocket", "state": "running", "title": "Tidy downloads",
            "current_step": "Sorting by type", "completed": 1, "total": 3, "plan": [], "files": []}, seq=4),
            note="progress: notify 0"),
        crypto_vector("job-done", MAC, PHONE, envelope(MAC, PHONE, "job.event", {
            "id": "job-1", "conversation_id": "pocket", "state": "done", "title": "Tidy downloads",
            "current_step": "", "completed": 3, "total": 3, "plan": [], "summary": "Moved 41 files", "files": []},
            seq=5), note="terminal state: notify 1"),
    ]


def resign(vector: dict, header_change: dict) -> dict:
    """A packet whose header was changed and then validly re-signed by the sender: the
    signature passes, so the receiver must catch the change later (AEAD or agreement)."""
    import reference as ref
    from cryptography.hazmat.primitives.asymmetric import ed25519
    packet = copy.deepcopy(vector["packet"])
    packet["header"].update(header_change)
    hb = ref.header_bytes(packet["header"])
    key = ed25519.Ed25519PrivateKey.from_private_bytes(raw(vector["sender"], "signingKey"))
    packet["signature"] = ref.b64(key.sign(hb + base64.b64decode(packet["sealed"])))
    return packet


def negatives(pos: dict[str, dict]) -> list[dict]:
    phone_msg, mac_msg, asset_v = pos["phone-message"], pos["mac-message"], pos["file-asset"]
    out = []

    def case(name, base, packet, expect, note, **extra):
        out.append({"contract": CONTRACT, "name": name, "base": base["name"], "note": note, "packet": packet,
                    "expect_error": expect, **extra})
    p = copy.deepcopy(mac_msg["packet"])
    p["header"]["notify"] = False
    case("notify-flipped", mac_msg, p, "bad_signature", "the clear-text notify bit is signed")
    p = copy.deepcopy(phone_msg["packet"])
    sealed = bytearray(base64.b64decode(p["sealed"]))
    sealed[20] ^= 1
    p["sealed"] = r.b64(bytes(sealed))
    case("sealed-bit-flip", phone_msg, p, "bad_signature", "the signature covers the ciphertext")
    p = copy.deepcopy(phone_msg["packet"])
    p["header"]["seq"] = 43
    case("seq-changed", phone_msg, p, "bad_signature", "the sequence number is signed")
    case("resigned-seq-changed", phone_msg, resign(phone_msg, {"seq": 43}), "decrypt_failed",
         "re-signed by the sender, but the header is also the AEAD's associated data")
    p = copy.deepcopy(phone_msg["packet"])
    p["header"]["to"] = "mac-other"
    case("not-for-me", phone_msg, p, "not_for_me", "a packet addressed to another device")
    p = copy.deepcopy(phone_msg["packet"])
    p["header"]["v"] = 2
    case("unsupported-version", phone_msg, p, "unsupported_version", "an unknown protocol version")
    p = copy.deepcopy(phone_msg["packet"])
    p["header"]["kind"] = "data"
    case("unknown-kind", phone_msg, p, "malformed", "kind is msg, ack or control")
    case("wrong-signer", phone_msg, phone_msg["packet"], "bad_signature",
         "a valid packet checked against another device's key", signer="mac-vector")
    case("asset-swapped", asset_v, asset_v["packet"], "asset_mismatch",
         "the encrypted file does not match the hash in the header",
         asset=r.b64(base64.b64decode(asset_v["asset"])[:-1] + b"\x00"))
    # A packet whose plaintext disagrees with its header, sealed and signed properly.
    env = json.loads(base64.b64decode(phone_msg["plaintext"]))
    env["type"] = "hello"
    env["body"] = {"app_version": "0.1.0", "protocol_version": 1, "capabilities": []}
    lying = r.seal(env, kind="msg", notify=False, sender_signing=raw(PHONE, "signingKey"),
                   recipient_exchange_public=r.public_exchange(raw(MAC, "exchangeKey")),
                   ephemeral=EPHEMERAL, nonce=NONCE)
    case("kind-disagrees", phone_msg, lying.packet, "header_mismatch",
         "a hello (control) sent under kind msg: the clear-text kind must match the real type")
    return out


def replay() -> dict:
    seqs = [5, 3, 5, 1030, 6, 7, 1029, 1028, 2000, 976, 977, 1500]
    window = r.ReplayWindow()
    return {"contract": CONTRACT, "window": r.REPLAY_WINDOW, "note": "one sender; in arrival order",
            "steps": [{"seq": s, "accept": window.accept(s)} for s in seqs]}


def qr() -> dict:
    container = "iCloud.vector.arslan"
    base = {"v": 1, "pairing_id": PAIRING_ID.lower(), "mac_device_id": MAC["deviceID"], "device_name": "Vector Mac",
            "signing_public_key": r.b64(r.public_signing(raw(MAC, "signingKey"))),
            "exchange_public_key": r.b64(r.public_exchange(raw(MAC, "exchangeKey"))),
            "pairing_key": r.b64(PSK), "container_id": container, "zone": "ArslanBridge",
            "issued_at": "2026-10-03T00:00:00Z", "expires_at": "2026-10-03T00:10:00Z"}
    now = 1790985600 + 60          # 2026-10-03T00:01:00Z
    cases = [("valid", base, None, None)]

    def variant(name, change, expect, uri=None):
        cases.append((name, {**base, **change}, expect, uri))
    variant("expired", {}, "pairing_expired")
    cases[-1] = ("expired", base, "pairing_expired", None)
    variant("validity-over-600s", {"expires_at": "2026-10-03T00:10:01Z"}, "pairing_invalid")
    variant("issued-in-the-future", {"issued_at": "2026-10-03T00:01:31Z", "expires_at": "2026-10-03T00:05:00Z"},
            "pairing_invalid")
    variant("wrong-container", {"container_id": "iCloud.other.arslan"}, "wrong_container")
    variant("wrong-zone", {"zone": "Other"}, "malformed")
    variant("short-key", {"pairing_key": r.b64(bytes(31))}, "malformed")
    variant("version-2", {"v": 2}, "unsupported_version")
    out = []
    for name, payload, expect, uri in cases:
        u = uri or r.encode_pair_uri(payload)
        at = now if name != "expired" else 1790985600 + 600
        if expect is None:
            r.decode_pair_uri(u, now=at, container_id=container)
        else:
            try:
                r.decode_pair_uri(u, now=at, container_id=container)
                raise AssertionError(name)
            except r.BridgeError as exc:
                assert exc.code == expect, (name, exc.code)
        out.append({"name": name, "uri": u, "now": at, "expect_error": expect})
    extra = r.QR_SCHEME + "x&payload=y"
    out.append({"name": "two-payloads", "uri": extra, "now": now, "expect_error": "malformed"})
    return {"contract": CONTRACT, "container_id": container, "cases": out}


def messages() -> dict:
    """One plaintext envelope per type, with the kind and notify bit it travels under."""
    s, m = PHONE, MAC
    examples = [
        envelope(s, m, "pair.request", {"device_name": "Vector iPhone", "signing_public_key": "…", "exchange_public_key": "…"}),
        envelope(m, s, "pair.accept", {"phone_device_id": s["deviceID"], "mac_device_id": m["deviceID"], "device_name": "Vector Mac",
                                       "signing_public_key": "…", "exchange_public_key": "…"}),
        envelope(m, s, "pair.reject", {"reason": "declined_on_mac"}),
        envelope(s, m, "hello", {"app_version": "0.1.0", "protocol_version": 1, "capabilities": ["cloudkit", "files"]}),
        envelope(m, s, "ack", {"ids": [ID.lower()]}),
        envelope(m, s, "status.snapshot", {"presence": "online", "mascot": "working", "device_name": "Vector Mac",
                                           "last_seen": TS, "jobs": [{"id": "job-1", "conversation_id": "c1",
                                           "state": "running", "title": "Tidy downloads", "current_step": "Sorting",
                                           "completed": 1, "total": 3, "plan": [], "files": []}],
                                           "waiting_approvals": 0, "high_risk_mac_only": False,
                                           "activity": {"hours": [[0, 0, 0]] * 9 + [[2, 1, 0], [1, 0, 1]] + [[0, 0, 0]] * 13,
                                                        "done": 3, "files": 2, "waiting": 0}}),
        envelope(s, m, "conversations.list", {"limit": 20}),
        envelope(m, s, "conversations.result", {"conversations": [
            {"id": "c1", "title": "Trip", "updated_at": TS},
            {"id": "task-ab12", "title": "Q3 report", "updated_at": TS, "kind": "task", "state": "working", "origin": "phone",
             "preview": "Running make_report.py", "files": 1, "job": {"id": "job-1", "step": "run_command python make_report.py",
                                                                      "done": 1, "total": 3}}]}),
        envelope(s, m, "chat.history", {"conversation_id": "c1", "limit": 50}),
        envelope(m, s, "chat.history.result", {"conversation_id": "c1", "messages": [
            {"id": "m1", "role": "user", "text": "Hi", "ts": TS, "attachments": []}]}),
        envelope(s, m, "chat.send", {"text": "Find flights", "attachments": [], "client_msg_id": "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB"}),
        envelope(m, s, "chat.event", {"conversation_id": "pocket", "kind": "progress", "message_id": "reply-1",
                                      "text": "Searching flights", "final": False}),
        envelope(m, s, "chat.event", {"conversation_id": "pocket", "kind": "message", "message_id": "reply-1",
                                      "text": "Three options…", "final": True}),
        envelope(m, s, "chat.event", {"conversation_id": "task-ab12", "kind": "message", "message_id": "412",
                                      "text": "The report is ready.", "final": True, "job_id": "job-1", "run_id": 87}),
        envelope(m, s, "chat.event", {"conversation_id": "pocket", "kind": "error", "message_id": "reply-1",
                                      "text": "The model is unreachable", "final": True}),
        envelope(m, s, "job.event", {"id": "job-1", "conversation_id": "pocket", "state": "running", "title": "Tidy",
                                     "current_step": "Sorting", "completed": 1, "total": 3, "plan": [], "files": [],
                                     "run_id": 87, "origin": "phone",
                                     "criteria": [{"text": "One row per invoice", "status": "passed"},
                                                  {"text": "Totals by month", "status": "pending"},
                                                  {"text": "Saved as a CSV", "status": "failed"}]}),
        envelope(m, s, "job.event", {"id": "job-1", "conversation_id": "pocket", "state": "partial", "title": "Tidy",
                                     "current_step": "", "completed": 2, "total": 3, "plan": [], "summary": "2 of 3", "files": []}),
        envelope(m, s, "approval.request", {"approval_id": "appr-1", "action": "Delete 3 files", "target": "~/Arslan/old",
                                            "risk": "delete", "task_id": "task-1", "task_title": "Tidy",
                                            "expires_at": "2026-10-03T00:05:00Z"}),
        envelope(s, m, "approval.answer", {"approval_id": "appr-1", "decision": "approve", "auth": "faceid", "ts": TS}),
        envelope(s, m, "approval.answer", {"approval_id": "appr-1", "decision": "deny", "auth": "none", "ts": TS}),
        envelope(m, s, "approval.result", {"approval_id": "appr-1", "outcome": "done"}),
        envelope(m, s, "approval.result", {"approval_id": "appr-1", "outcome": "expired",
                                           "detail": "The card timed out on the Mac"}),
        envelope(m, s, "file.offer", {"id": "f1", "name": "jobs.csv", "size": 2048, "mime_type": "text/csv",
                                      "sha256": "0" * 64}),
        envelope(s, m, "file.get", {"file_id": "f1"}),
        envelope(s, m, "run.get", {"run_id": 87}),
        envelope(m, s, "run.result", {"run_id": 87, "conversation_id": "task-ab12", "title": "Make a one-page Q3 report",
                                      "state": "done", "started_at": TS, "duration_ms": 138000, "total": 3, "steps": [
            {"kind": "command", "tool": "run_command", "ok": True, "ms": 4200, "target": "python make_report.py", "summary": "exit 0",
             "terminal": {"command": "python make_report.py", "exit": 0, "lines": ["Loaded 1,204 rows", "PDF written: report.pdf"]}},
            {"kind": "edit", "tool": "edit_file", "ok": True, "ms": 12, "target": "make_report.py", "summary": "ok",
             "diff": {"path": "make_report.py", "added": 1, "removed": 1, "new_file": False, "lines": [
                 [" ", 11, 11, "def load(path):"], ["-", 12, None, "    df = pd.read_csv(path)"],
                 ["+", None, 12, "    df = pd.read_csv(path, parse_dates=[\"date\"])"], ["fold", None, None, "24"]]}},
            {"kind": "write", "tool": "write_file", "ok": True, "ms": 8, "target": "report.md", "summary": "ok",
             "file_id": "run_87_0123456789abcdef_report.md",
             "diff": {"path": "report.md", "added": 2, "removed": 0, "new_file": True,
                      "lines": [["+", None, 1, "# Q3"], ["+", None, 2, "Revenue ¥4.2M"]]}}],
            "files": [{"id": "run_87_0123456789abcdef_report.md", "name": "report.md", "size": 22, "mime_type": "text/markdown",
                       "sha256": "1" * 64}]}),
        envelope(s, m, "task.start", {"goal": "Turn the invoices in Downloads into one table by month",
                                      "criteria": ["One row per invoice"], "client_task_id": "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC"}),
        envelope(m, s, "task.started", {"conversation_id": "task-ab12", "job_id": "job-1",
                                        "client_task_id": "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC"}),
        envelope(s, m, "task.stop", {"job_id": "job-1", "conversation_id": "task-ab12"}),
        envelope(m, s, "device.revoked", {"reason": "removed_on_mac"}),
        envelope(m, s, "error", {"code": "approval_expired", "message": "That card expired", "related_id": ID.lower()}),
    ]
    for e in examples:
        r.check_body(e)
    return {"contract": CONTRACT, "examples": [{"envelope": e, "kind": r.kind_of(e["type"]),
                                                "notify": r.should_notify(e)} for e in examples]}


def build() -> dict[str, dict]:
    pos = {v["name"]: v for v in positives()}
    files = {f"crypto/{name}.json": v for name, v in pos.items()}
    files.update({f"negative/{n['name']}.json": n for n in negatives(pos)})
    files["replay-window.json"] = replay()
    files["pairing-qr.json"] = qr()
    files["messages.json"] = messages()
    return files


def main() -> None:
    for rel, data in build().items():
        path = OUT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {len(build())} files to {OUT}")


if __name__ == "__main__":
    main()

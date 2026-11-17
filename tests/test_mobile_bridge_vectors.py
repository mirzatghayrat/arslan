"""The shared mobile-bridge vectors (docs/specs/mobile-bridge-protocol.md): they match the
reference implementation byte for byte, every positive vector opens, every negative one is
dropped with its code, and the replay, pairing-QR and message tables hold."""
import base64
import json
import sys
from pathlib import Path

import pytest

SPEC = Path(__file__).resolve().parents[1] / "spec" / "mobile-bridge"
sys.path.insert(0, str(SPEC))
import make_vectors  # noqa: E402
import reference as r  # noqa: E402

VECTORS = SPEC / "vectors"


def load(rel):
    return json.loads((VECTORS / rel).read_text())


def test_committed_vectors_are_exactly_what_the_reference_writes():
    built = make_vectors.build()
    on_disk = {str(p.relative_to(VECTORS)) for p in VECTORS.rglob("*.json")}
    assert on_disk == set(built), "regenerate with: .venv/bin/python spec/mobile-bridge/make_vectors.py"
    for rel, data in built.items():
        assert load(rel) == json.loads(json.dumps(data)), rel


@pytest.mark.parametrize("name", sorted(p.stem for p in (VECTORS / "crypto").glob("*.json")))
def test_every_positive_vector_opens(name):
    v = load(f"crypto/{name}.json")
    sender, recipient = v["sender"], v["recipient"]
    envelope, asset = r.open_packet(
        v["packet"], recipient_id=recipient["deviceID"], recipient_exchange=base64.b64decode(recipient["exchangeKey"]),
        sender_signing_public=r.public_signing(base64.b64decode(sender["signingKey"])),
        psk=base64.b64decode(v["psk"]), asset=base64.b64decode(v["asset"]) if "asset" in v else None)
    assert envelope == json.loads(base64.b64decode(v["plaintext"]))
    assert base64.b64encode(r.header_bytes(v["packet"]["header"])).decode() == v["header_bytes"]
    assert v["packet"]["header"]["kind"] == r.kind_of(envelope["type"])
    assert v["packet"]["header"]["notify"] == r.should_notify(envelope)
    r.check_body(envelope)
    if "asset" in v:
        assert asset == base64.b64decode(v["asset_plaintext"])


@pytest.mark.parametrize("name", sorted(p.stem for p in (VECTORS / "negative").glob("*.json")))
def test_every_negative_vector_is_dropped_with_its_code(name):
    n = load(f"negative/{name}.json")
    base = load(f"crypto/{n['base']}.json")
    sender, recipient = base["sender"], base["recipient"]
    signer = make_vectors.MAC if n.get("signer") == "mac-vector" else sender
    with pytest.raises(r.BridgeError) as caught:
        r.open_packet(n["packet"], recipient_id=recipient["deviceID"],
                      recipient_exchange=base64.b64decode(recipient["exchangeKey"]),
                      sender_signing_public=r.public_signing(base64.b64decode(signer["signingKey"])),
                      psk=base64.b64decode(base["psk"]),
                      asset=base64.b64decode(n.get("asset") or base.get("asset") or "") or None)
    assert caught.value.code == n["expect_error"]


def test_the_replay_window_steps():
    table = load("replay-window.json")
    window = r.ReplayWindow(size=table["window"])
    assert [window.accept(step["seq"]) for step in table["steps"]] == [step["accept"] for step in table["steps"]]
    assert False in [s["accept"] for s in table["steps"]] and True in [s["accept"] for s in table["steps"]]


@pytest.mark.parametrize("case", load("pairing-qr.json")["cases"], ids=lambda c: c["name"])
def test_pairing_qr_cases(case):
    container = load("pairing-qr.json")["container_id"]
    if case["expect_error"] is None:
        payload = r.decode_pair_uri(case["uri"], now=case["now"], container_id=container)
        assert payload["zone"] == "ArslanBridge" and len(base64.b64decode(payload["pairing_key"])) == 32
    else:
        with pytest.raises(r.BridgeError) as caught:
            r.decode_pair_uri(case["uri"], now=case["now"], container_id=container)
        assert caught.value.code == case["expect_error"]


def test_every_type_has_an_example_with_its_kind_and_notify_bit():
    examples = load("messages.json")["examples"]
    assert {e["envelope"]["type"] for e in examples} == set(r.BODY_FIELDS)
    for e in examples:
        r.check_body(e["envelope"])
        assert e["kind"] == r.kind_of(e["envelope"]["type"])
        assert e["notify"] == r.should_notify(e["envelope"])
    notify = {(e["envelope"]["type"], e["envelope"]["body"].get("kind") or e["envelope"]["body"].get("state")
               or e["envelope"]["body"].get("outcome")) for e in examples if e["notify"]}
    assert ("chat.event", "progress") not in notify and ("job.event", "running") not in notify
    assert ("approval.request", None) in notify and ("job.event", "partial") in notify


def test_only_the_mac_block_without_taken_at_is_marked_as_dropped_by_the_phone():
    """Test-only, never on the wire (#652, ①iOS): `phone_drops` lists the body keys a part-B phone drops by
    design, so its round-trip test strips exactly those and still fails on any drop it doesn't list."""
    marked = [e for e in load("messages.json")["examples"] if "phone_drops" in e]
    assert [e["phone_drops"] for e in marked] == [["mac"]]
    body = marked[0]["envelope"]["body"]
    assert marked[0]["envelope"]["type"] == "status.snapshot" and "mac" in body and "taken_at" not in body["mac"]


@pytest.mark.parametrize("body,ok", [
    ({"approval_id": "a", "decision": "approve", "auth": "faceid", "ts": "t"}, True),
    ({"approval_id": "a", "decision": "deny", "auth": "none", "ts": "t"}, True),
    ({"approval_id": "a", "decision": "approve", "auth": "none", "ts": "t"}, False),     # approving needs Face ID
    ({"approval_id": "a", "decision": "approve", "auth": "voice", "ts": "t"}, False),    # voice never approves
    ({"approval_id": "a", "decision": "approve", "auth": "faceid"}, False),
    ({"approval_id": "a", "decision": "approve", "auth": "faceid", "ts": "t", "extra": 1}, False),
])
def test_an_approval_answer_must_carry_the_right_authentication(body, ok):
    envelope = {"type": "approval.answer", "body": body}
    if ok:
        r.check_body(envelope)
    else:
        with pytest.raises(r.BridgeError):
            r.check_body(envelope)


# ── §5.13 (CAP11a + SUB5f): capability cards view-only, the card's optional fields, read-only sub-sessions ──

def bodies(type_):
    return [e["envelope"]["body"] for e in load("messages.json")["examples"] if e["envelope"]["type"] == type_]


def test_the_capability_perm_kind_is_the_exact_lowercase_string():
    """§5.13 rule 7 (①iOS compares it verbatim): vectors (a)-(c) carry exactly "capability", and the Mac's own frame
    builder stamps that same string, so no case or spacing variant can reach the phone."""
    kinds = [b.get("perm_kind") for b in bodies("approval.request") if "perm_kind" in b]
    assert kinds.count("capability") == 3
    assert not [k for k in kinds if k != "capability" and k.strip().casefold() == "capability"]


def test_the_four_capability_card_vectors():
    cards = [b for b in bodies("approval.request") if b.get("perm_kind") == "capability"]
    full = sorted((b for b in cards if {"source", "abilities", "checks"} <= set(b)), key=lambda b: b["phone_can_approve"])
    assert [b["phone_can_approve"] for b in full] == [False, True]                      # (a), (b)
    a, b = full
    assert {k: v for k, v in a.items() if k != "phone_can_approve"} == {k: v for k, v in b.items() if k != "phone_can_approve"}
    assert a["risk"] == "install" and [r.phone_may_approve(x) for x in (a, b)] == [False, True]
    old = [x for x in cards if "phone_can_approve" not in x]                            # (c): an old Mac's card
    assert len(old) == 1 and r.phone_may_approve(old[0]) is False
    others = [x for x in bodies("approval.request") if x.get("perm_kind") != "capability"]
    assert others and all(r.phone_may_approve(x) for x in others if "phone_can_approve" not in x)
    deny = [x for x in bodies("approval.answer") if x["approval_id"] == a["approval_id"]]   # (d): a phone no
    assert deny == [{"approval_id": a["approval_id"], "decision": "deny", "auth": "none", "ts": make_vectors.TS}]


CARD = {"approval_id": "c", "action": "Add x", "target": "t", "risk": "install", "task_id": "t", "task_title": "T",
        "expires_at": "2026-10-03T00:05:00Z"}


@pytest.mark.parametrize("extra,ok", [
    ({"checks": [{"name": "osv", "result": "a-value-from-later"}]}, True),             # an open set: kept
    ({"source": "s" * 200, "abilities": ["a" * 120] * 8, "checks": [{"name": "n", "result": "pass", "detail": "d" * 160}]},
     True),
    ({"source": "s" * 201}, False),
    ({"abilities": ["a"] * 9}, False),
    ({"abilities": ["a" * 121]}, False),
    ({"checks": [{"name": "n", "result": "pass", "detail": "d" * 161}]}, False),
    ({"checks": [{"name": "n"}]}, False),
    ({"phone_can_approve": "false"}, False),
    ({"risk": "capability"}, False),                                                     # `risk` stays closed
])
def test_a_cards_optional_fields_hold_the_macs_limits(extra, ok):
    envelope = {"type": "approval.request", "body": {**CARD, **extra}}
    if ok:
        r.check_body(envelope)
    else:
        with pytest.raises(r.BridgeError):
            r.check_body(envelope)


def test_a_sub_session_is_only_ever_read_on_the_phone():
    """No write twin: the one sub-session request reads; `view_only` is the literal true."""
    assert {t for t in r.BODY_FIELDS if t.startswith("sub_session")} == {"sub_session.history", "sub_session.history.result"}
    results = bodies("sub_session.history.result")
    assert results and all(b["view_only"] is True for b in results)
    for bad in (False, "true", 1, None):
        with pytest.raises(r.BridgeError):
            r.check_body({"type": "sub_session.history.result", "body": {**results[0], "view_only": bad}})
    assert any("sub_sessions" in b["capabilities"] for b in bodies("hello"))
    assert any("sub" in c for b in bodies("conversations.result") for c in b["conversations"])
    assert any("sub_sessions" in (b.get("details") or {}) for b in bodies("chat.history.result"))

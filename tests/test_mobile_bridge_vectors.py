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

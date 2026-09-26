import json
import pytest
from evals.companion import stable_release_retest as release


def test_master_cannot_reset_or_skip_unaccounted_request(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "MASTER", tmp_path)
    monkeypatch.setattr(release, "authority", lambda: "fixture")
    monkeypatch.setattr(release, "digest", lambda _: "contract")
    release.initialize()
    with pytest.raises(FileExistsError):
        release.initialize()
    release.reserve_global(1, 1, "S2-R1")
    with pytest.raises(RuntimeError, match="unaccounted"):
        release.reserve_global(2, 1, "S2-R1")
    (tmp_path / "round-1").mkdir()
    (tmp_path / "round-1/request-01.accounted.json").write_text(json.dumps({"request": 1,
        "reserved_usd": "0.10", "reservation_refunded": False, "peak_rate_estimate_usd": "0.01"}))
    release.reserve_global(2, 1, "S2-R1")
    rows = [json.loads(line) for line in (tmp_path / "budget.jsonl").read_text().splitlines()]
    assert [row["request"] for row in rows[1:]] == [1, 2]
    assert [row["round"] for row in rows[1:]] == [1, 2]


def test_global_sixty_call_limit_cannot_be_reset_by_new_round(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "MASTER", tmp_path)
    monkeypatch.setattr(release, "authority", lambda: "fixture")
    release.initialize()
    with (tmp_path / "budget.jsonl").open("a") as stream:
        for number in range(60):
            stream.write('{}\n')
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        release.reserve_global(4, 1, "S2-R1")


def test_task_admission_rejects_exhausted_tokens_without_reset():
    from arslan.execution_budget import Budget, BudgetExceeded, scope
    execution = Budget()
    execution.tokens = execution.limits.tokens
    with scope(execution), pytest.raises(BudgetExceeded, match="tokens"):
        release.execution_admitted()
    assert execution.tokens == execution.limits.tokens
    assert execution.model_requests == 0


def test_cancelled_request_keeps_full_charge_requires_original_bound(tmp_path, monkeypatch):
    import hashlib
    monkeypatch.setattr(release, "MASTER", tmp_path)
    directory = tmp_path / "round-1"
    directory.mkdir()
    payload = {"model": "deepseek-v4-flash", "max_tokens": 8192, "messages": []}
    original = directory / "request-06.input.json"
    original.write_text(json.dumps({"payload": payload}))
    receipt = {"request": 6, "status": "cancelled_usage_unknown", "charged_budget_usd": "0.10",
        "reservation_refunded": False, "automatic_retry": False, "invoice": False,
        "input_sha256": release.digest(original)}
    disposition = directory / "request-06.abandoned.json"
    disposition.write_text(json.dumps(receipt))
    (directory / "HALT").write_text('{"reason":"CancelledError"}')
    reservation = {"request": 6, "case": "S2-R1", "reserved_usd": "0.10",
        "payload_sha256": hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest(),
        "pricing": {"endpoint": "https://api.deepseek.com", "input_usd_per_million": "0.30",
                    "output_usd_per_million": "1.20"}}
    (directory / "budget.jsonl").write_text('{}\n' * 6 + json.dumps(reservation) + '\n')
    row = {"round": 1, "local_request": 6, "case": "S2-R1"}
    assert str(release.abandoned_bound(row)) == "0.10"
    receipt["charged_budget_usd"] = "0.00"
    disposition.write_text(json.dumps(receipt))
    with pytest.raises(RuntimeError, match="abandonment_invalid"):
        release.abandoned_bound(row)
    receipt["charged_budget_usd"] = "0.10"
    disposition.write_text(json.dumps(receipt))
    payload["max_tokens"] = 1000000
    original.write_text(json.dumps({"payload": payload}))
    with pytest.raises(RuntimeError, match="abandonment_invalid"):
        release.abandoned_bound(row)

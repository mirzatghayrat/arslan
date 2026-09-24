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

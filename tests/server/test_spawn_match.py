from server.services import spawn_match_service as sms


def test_structural_score_domain_alignment():
    need = {"domain": "data-analysis.finance", "capabilities": ["x"]}
    same_cat = {"domain_category": "data-analysis", "domain_subcategory": "marketing"}
    same_both = {"domain_category": "data-analysis", "domain_subcategory": "finance"}
    other = {"domain_category": "content-creation", "domain_subcategory": None}
    assert sms._structural_score(need, same_both) == 1.0
    assert sms._structural_score(need, same_cat) == 0.5
    assert sms._structural_score(need, other) == 0.0


def test_structural_score_accepts_single_domain_string():
    # SpawnOut-style shape: one "category.subcategory" string, no split keys.
    need = {"domain": "data-analysis.finance", "capabilities": ["x"]}
    spawn = {"id": 1, "name": "fin", "domain": "data-analysis.finance",
             "capabilities": ["forecasting"]}
    assert sms._structural_score(need, spawn) == 1.0


async def test_llm_coverage_empty_spawns_short_circuits(monkeypatch):
    def _boom():
        raise AssertionError("_get_adapter must not be called for empty spawns")
    monkeypatch.setattr(sms, "_get_adapter", _boom)
    result = await sms._llm_coverage({"capabilities": ["x"]}, [])
    assert result == {}


def test_classify_band_invite_one():
    ranked = [{"spawn_id": 1, "name": "a", "score": 0.9, "why": ""},
              {"spawn_id": 2, "name": "b", "score": 0.4, "why": ""}]
    band, payload = sms.classify_band(ranked)
    assert band == "invite_one"
    assert payload["spawn_id"] == 1


def test_classify_band_picker_two_strong_no_margin():
    ranked = [{"spawn_id": 1, "name": "a", "score": 0.9, "why": ""},
              {"spawn_id": 2, "name": "b", "score": 0.88, "why": ""}]
    band, payload = sms.classify_band(ranked)
    assert band == "picker"
    assert [c["spawn_id"] for c in payload["candidates"]] == [1, 2]


def test_classify_band_picker_mid():
    ranked = [{"spawn_id": 1, "name": "a", "score": 0.6, "why": ""},
              {"spawn_id": 2, "name": "b", "score": 0.5, "why": ""}]
    band, _ = sms.classify_band(ranked)
    assert band == "picker"


def test_classify_band_create_all_low():
    ranked = [{"spawn_id": 1, "name": "a", "score": 0.2, "why": ""}]
    band, _ = sms.classify_band(ranked)
    assert band == "create"
    assert sms.classify_band([])[0] == "create"


async def test_score_spawns_combines_and_ranks(monkeypatch):
    need = {"domain": "data-analysis.finance", "capabilities": ["forecasting"]}
    spawns = [
        {"id": 1, "name": "fin", "domain_category": "data-analysis",
         "domain_subcategory": "finance", "capabilities": ["forecasting"]},
        {"id": 2, "name": "writer", "domain_category": "content-creation",
         "domain_subcategory": None, "capabilities": ["blogging"]},
    ]
    async def fake_coverage(need_, spawns_):
        return {1: 1.0, 2: 0.0}  # by spawn id
    monkeypatch.setattr(sms, "_llm_coverage", fake_coverage)
    ranked = await sms.score_spawns(need, spawns)
    assert ranked[0]["spawn_id"] == 1 and ranked[0]["score"] > ranked[1]["score"]
    assert set(ranked[0].keys()) >= {"spawn_id", "name", "score", "why"}

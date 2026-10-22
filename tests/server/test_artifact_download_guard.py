"""The artifact download route never serves the old review-notes directory.

Research review (removed in C8-2, v0.1.63) stored its notes under `<artifacts>/_reviews/`, a
sibling of the artifacts, so a note could never pass for a downloadable `run_{id}_*` file.
Installs keep that directory on disk after the upgrade; this pins that the live download
route still refuses it (moved from test_research_review_after_save.py, which went with the
review).
"""
from server.services import artifact_store

RUN_ID = 7
AUTH: dict[str, str] = {}


async def test_old_review_notes_on_disk_are_not_downloadable(client, monkeypatch, tmp_path):
    root = tmp_path / "artifacts"
    monkeypatch.setattr(artifact_store, "root", lambda: root)
    notes = root / "_reviews"
    notes.mkdir(parents=True)
    (notes / f"run_{RUN_ID}_report.md.json").write_text('{"status": "no_objection"}', encoding="utf-8")

    assert (await client.get(f"/api/v1/runs/{RUN_ID}/artifacts/_reviews", headers=AUTH)).status_code == 400
    nested = f"/api/v1/runs/{RUN_ID}/artifacts/_reviews%2Frun_{RUN_ID}_report.md.json"
    assert (await client.get(nested, headers=AUTH)).status_code in (400, 404)

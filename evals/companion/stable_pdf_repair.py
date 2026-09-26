"""Offline D1 attachment-API preparation; no provider or paid runner entry point."""
import hashlib
import json
from pathlib import Path
import subprocess

import httpx

from evals.companion import stable_budget as budget, stable_documents as documents
from evals.companion.stable_repair_preparation import digest, retained_input
from server.services import ingest


def original_input():
    contract, contract_hash = budget.contract()
    path = budget.EVIDENCE / "S2-D1-preflight.json"
    original = json.loads(path.read_bytes())
    if (original.get("case") != "S2-D1" or original.get("contract_sha256") != contract_hash
            or len(original.get("inputs", [])) != 1):
        raise RuntimeError("repair_original_preflight_mismatch")
    item = retained_input(original["inputs"][0])
    if item["path"] != "document-inputs/S2-D1/brief.pdf":
        raise RuntimeError("repair_original_pdf_path_changed")
    if original.get("prompt") != documents.prompt("S2-D1", original["extracted"]):
        raise RuntimeError("repair_original_prompt_changed")
    return original, item, digest(path), next(c["acceptance"] for c in contract["cases"]
                                             if c["id"] == "S2-D1")


async def prepare(client):
    # The caller supplies the existing isolated REST fixture. Refuse ordinary
    # HTTP transports before any request; this helper cannot contact a provider.
    if not isinstance(client._transport, httpx.ASGITransport) or client._mounts:
        raise RuntimeError("repair_requires_in_process_api")
    if ingest.ocr_vision.is_available():
        raise RuntimeError("repair_pdf_ocr_must_be_disabled")
    old, item, old_hash, acceptance = original_input()
    data = (budget.EVIDENCE / item["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise RuntimeError("repair_input_changed")
    response = await client.post("/api/v1/extract", files={
        "file": ("brief.pdf", data, "application/pdf")}, data={"compress": "false"})
    if response.status_code != 200:
        raise RuntimeError("repair_attachment_api_failed")
    value = response.json()
    text = value.get("text")
    if (not isinstance(text, str) or not text.strip() or value.get("chars") != len(text)
            or value.get("truncated") is not False):
        raise RuntimeError("repair_attachment_incomplete")
    if not text.startswith("[PDF extraction inventory; not document content]\n"):
        raise RuntimeError("repair_attachment_inventory_missing")
    # No expected answer or case-specific page facts are added to the prompt.
    # The new context is exactly what the real upload endpoint returned.
    return {"case": "S2-D1", "kind": "offline_attachment_preparation",
            "authorization": None, "execution_enabled": False, "runner_ready": False,
            "original_preflight_sha256": old_hash, "input": item,
            "api": "POST /api/v1/extract", "api_response": value,
            "old_extracted_sha256": hashlib.sha256(old["extracted"].encode()).hexdigest(),
            "prompt": documents.prompt("S2-D1", text), "acceptance": acceptance,
            "model_calls": 0, "quality_status": "not_run", "native_status": "not_run",
            "remaining": ["new explicit authorization and independent linked ledger",
                          "freeze executable host runner, candidate and checkers",
                          "actual model response and source-grounded review"]}


async def save(client, output):
    output = Path(output).resolve()
    if output.is_relative_to(budget.EVIDENCE.resolve()):
        raise RuntimeError("repair_cannot_write_original_evidence")
    if output.exists():
        raise FileExistsError(output)
    ledger_hash = digest(budget.EVIDENCE / "budget.jsonl")
    result = await prepare(client)
    if digest(budget.EVIDENCE / "budget.jsonl") != ledger_hash:
        raise RuntimeError("repair_ledger_changed_during_snapshot")
    result.update({"original_ledger_sha256": ledger_hash,
                   "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"],
                       cwd=budget.ROOT, text=True).strip(),
                   "code_sha256": {path: digest(budget.ROOT / path) for path in (
                       "evals/companion/stable_pdf_repair.py",
                       "evals/companion/stable_documents.py", "server/api/extract.py",
                       "server/services/extract.py", "server/services/ingest.py",
                       "tests/server/test_stable_pdf_repair.py")}})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    return result

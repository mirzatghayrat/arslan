"""Archive the fixed public inputs without calling a model or creating receipts.

Collector evidence is deliberately separate from Arslan runtime read evidence.
Existing files are verified/reused, never overwritten. No credentials are used.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from urllib.request import Request, urlopen

from evals.companion import stable_budget as budget

MAX_BYTES = 2_000_000
CONFLICT_SOURCES = [
    {"id": "planck-2018-v4", "url": "https://arxiv.org/abs/1807.06209v4",
     "version_date": "2021-08-09", "kind": "complete abstract landing page, not full paper"},
    {"id": "shoes-2022-v3", "url": "https://arxiv.org/abs/2112.04510v3",
     "version_date": "2022-07-18", "kind": "complete abstract landing page, not full paper"},
]


def sources():
    manifest = json.loads((budget.ROOT / "evals/companion/stage2-public-sources.json").read_text())
    return [dict(item, url=f"https://raw.githubusercontent.com/{item['repository']}/{item['commit']}/{item['path']}",
                 kind="complete pinned README") for item in manifest["sources"]] + CONFLICT_SOURCES


def fetch(url):
    if url not in {item["url"] for item in sources()}:
        raise RuntimeError("source_outside_frozen_allowlist")
    request = Request(url, headers={"User-Agent": "Arslan-stable-acceptance-source-collector/1.0"})
    with urlopen(request, timeout=30) as response:
        if response.url != url:
            raise RuntimeError("source_redirect_requires_review")
        body = response.read(MAX_BYTES + 1)
        content_type = response.headers.get("Content-Type", "")
    if not body or len(body) > MAX_BYTES:
        raise RuntimeError("source_empty_or_too_large")
    body.decode("utf-8")
    return body, content_type


def collect_one(item):
    folder = budget.EVIDENCE / "public-inputs"
    folder.mkdir(exist_ok=True)
    record_path = folder / f"{item['id']}.json"
    if record_path.exists():
        record = json.loads(record_path.read_text())
        raw = folder / record["file"]
        if record["url"] != item["url"] or hashlib.sha256(raw.read_bytes()).hexdigest() != record["sha256"]:
            raise RuntimeError("archived_source_changed")
        if item.get("sha256") and item["sha256"] != record["sha256"]:
            raise RuntimeError("pinned_source_hash_mismatch")
        return record
    body, content_type = fetch(item["url"])
    digest = hashlib.sha256(body).hexdigest()
    if item.get("sha256") and item["sha256"] != digest:
        raise RuntimeError("pinned_source_hash_mismatch")
    raw = folder / f"{item['id']}.body"
    # Exclusive writes retain interruption evidence rather than silently retrying.
    with raw.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    record = {"id": item["id"], "url": item["url"], "file": raw.name,
              "sha256": digest, "bytes": len(body), "characters": len(body.decode("utf-8")),
              "content_type": content_type, "kind": item["kind"],
              "source_date": item.get("version_date", item.get("commit_date")),
              "retrieved_at": datetime.now(timezone.utc).isoformat(),
              "collector": "offline acceptance input collector, NOT Arslan web_extract",
              "runtime_receipt": None, "quality_status": "not_run"}
    with record_path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    return record


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true", required=True, help="Fetch only the seven fixed public URLs")
    parser.parse_args()
    budget.status()  # An existing valid grant/contract is required, but not spent.
    for source in sources():
        record = collect_one(source)
        print(json.dumps({key: record[key] for key in ("id", "bytes", "characters", "sha256")}), flush=True)

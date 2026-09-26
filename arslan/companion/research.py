"""Research provenance checks; matching text is not semantic entailment.

Only the host's admitted tool trace supplies source reads. Search snippets and
model-provided URLs cannot manufacture a successful read. Cached read receipts
remain untrusted reference data, never memory preferences or execution authority.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, ValidationError

from arslan.companion.contracts import Contract, Identifier


class SourceReceipt(Contract):
    id: Annotated[str, Field(pattern=r"^source:[a-f0-9]{64}$")]
    url: Annotated[str, Field(min_length=8, max_length=4000)]
    text_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    retrieved_at: AwareDatetime
    truncated: bool
    trust: Literal["untrusted_web"] = "untrusted_web"
    license: Literal["unknown_reference_only"] = "unknown_reference_only"
    # Retrieval time is NOT the article's publication date or freshness proof.


def receipt(url: str, text: str, *, truncated: bool) -> SourceReceipt:
    digest = hashlib.sha256(text.encode()).hexdigest()
    return SourceReceipt(id="source:" + hashlib.sha256((url + "\0" + digest).encode()).hexdigest(),
                         url=url, text_sha256=digest, retrieved_at=datetime.now(timezone.utc), truncated=truncated)


def admitted_sources(trace: list[dict]) -> dict[str, tuple[SourceReceipt, str]]:
    sources = {}
    for item in trace:
        if not isinstance(item, dict):
            continue
        result = item.get("result") or {}
        if item.get("tool") != "web_extract" or not isinstance(result, dict) or result.get("ok") is not True:
            continue
        arguments = item.get("args")
        if not isinstance(arguments, dict):
            continue
        text, metadata = result.get("text"), result.get("source")
        if not isinstance(text, str) or not text.strip() or not isinstance(metadata, dict):
            continue
        try:
            value = SourceReceipt.model_validate(metadata)
        except ValidationError:
            continue
        if (value.url != arguments.get("url") or result.get("url") != value.url
                or value.text_sha256 != hashlib.sha256(text.encode()).hexdigest()
                or receipt(value.url, text, truncated=value.truncated).id != value.id):
            continue
        sources[value.id] = (value, text)
    return sources


class Citation(Contract):
    source_id: Annotated[str, Field(pattern=r"^source:[a-f0-9]{64}$")]
    quote: Annotated[str, Field(min_length=1, max_length=1000)]


class Claim(Contract):
    id: Identifier
    statement: Annotated[str, Field(min_length=1, max_length=4000)]
    kind: Literal["fact", "inference", "recommendation"]
    time_sensitive: bool = False
    citations: tuple[Citation, ...] = Field(min_length=1, max_length=10)


class ResearchEvidence(Contract):
    claims: tuple[Claim, ...] = Field(min_length=1, max_length=100)
    unknowns: tuple[Annotated[str, Field(max_length=2000)], ...] = Field(default=(), max_length=100)
    conflicts: tuple[Annotated[str, Field(max_length=2000)], ...] = Field(default=(), max_length=100)


def inspect_evidence(evidence: ResearchEvidence, trace: list[dict], *, now: datetime | None = None) -> dict:
    sources = admitted_sources(trace)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("research inspection requires timezone-aware time")
    findings = []
    ids = set()
    for claim in evidence.claims:
        if claim.id in ids:
            findings.append({"claim_id": claim.id, "status": "failed", "code": "duplicate_claim"})
        ids.add(claim.id)
        for citation in claim.citations:
            source = sources.get(citation.source_id)
            if source is None:
                code = "source_not_read"
            elif citation.quote not in source[1]:
                code = "quote_not_in_read_text"
            elif source[0].retrieved_at > now:
                code = "source_receipt_from_future"
            elif claim.time_sensitive and (now - source[0].retrieved_at).total_seconds() > 86400:
                code = "time_sensitive_source_must_be_reopened"
            else:
                code = None
            if code:
                findings.append({"claim_id": claim.id, "source_id": citation.source_id, "status": "failed", "code": code})
        findings.append({"claim_id": claim.id, "status": "not_run", "code": "claim_support_review_required"})
        if claim.time_sensitive:
            findings.append({"claim_id": claim.id, "status": "not_run", "code": "source_temporal_relevance_review_required"})
    return {"status": "failed" if any(item["status"] == "failed" for item in findings) else "not_run",
            "code": "research_evidence_requires_semantic_review", "findings": findings,
            "read_source_count": len(sources)}

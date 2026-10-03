"""Re-ask recorded judgments with another judge model and compare (0.1.52 S2).

    python -m scripts.judgment_replay --db ~/Library/Application\\ Support/Arslan/arslan.db \\
        --point tool.approval --provider openai --base-url http://127.0.0.1:11434/v1 --model qwen3 [--limit 200]

The ledger keeps each question's minimal state, so a candidate judge (a local model,
for one) can be measured on the same questions without collecting new data. Spends
whatever the candidate model costs; nothing here runs on its own. The report:
agreement with the recorded judge, and — where the user's real answer is known —
how often "yes with p >= threshold" matched an approval (the gate the task book sets
before tool.approval may act).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3


def score(rows: list[dict], answers: list[tuple[bool, float] | None], threshold: float = 0.9) -> dict:
    """rows: recorded judgments (verdict, outcome); answers: the candidate's (answer, p) or None."""
    asked = [(r, a) for r, a in zip(rows, answers) if a is not None]
    agree = sum(1 for r, a in asked if r.get("verdict") is not None and r["verdict"] == a[0])
    sure = [(r, a) for r, a in asked if a[0] and a[1] >= threshold and r.get("outcome") in ("approved", "declined")]
    approved = sum(1 for r, _ in sure if r["outcome"] == "approved")
    return {"asked": len(asked), "unanswered": len(rows) - len(asked),
            "agreement": round(agree / len(asked), 3) if asked else None,
            "sure_yes": len(sure), "sure_yes_approved": round(approved / len(sure), 3) if sure else None}


def load(db: str, point: str, limit: int) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cur = con.execute("SELECT state, verdict, probability, outcome FROM judgments WHERE point=? "
                          "ORDER BY id DESC LIMIT ?", (point, limit))
        return [{"state": json.loads(s), "verdict": None if v is None else bool(v), "probability": p,
                 "outcome": o} for s, v, p, o in cur.fetchall()]
    finally:
        con.close()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--point", default="tool.approval")
    ap.add_argument("--provider", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", default="")
    ap.add_argument("--api-key-env", default="JUDGE_API_KEY")
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()
    from arslan.llm.cached_system import build_cached_system
    from arslan.llm.adapter import LLMAdapter
    from server.services import judgment
    point = judgment.REGISTRY[args.point]
    adapter = LLMAdapter(args.provider, args.model, api_key=os.environ.get(args.api_key_env, ""),
                         base_url=args.base_url or None)
    rows = load(os.path.expanduser(args.db), args.point, args.limit)
    answers = []
    for r in rows:
        user = f"Question: {point.question}\n\nFacts (JSON):\n{json.dumps(r['state'], ensure_ascii=False)}"
        try:
            reply = await asyncio.wait_for(adapter.chat(system=build_cached_system(judgment._SYSTEM, ""), user=user), 30)
            answers.append(judgment.parse(reply.content))
        except Exception:  # noqa: BLE001
            answers.append(None)
    print(json.dumps(score(rows, answers, point.threshold), indent=1))


if __name__ == "__main__":
    asyncio.run(main())

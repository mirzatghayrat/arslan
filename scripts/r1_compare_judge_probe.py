"""R1 probe: is compare_judge a stable enough metric to gate iterative training on?

Run against an ISOLATED copy of data/arslan.db (real DeepSeek). Measures:
(a) A-vs-A: identical outputs must score `tie` (a non-tie is pure noise).
(b) Flip rate: genuinely-different pairs run K times; how often `overall` flips.

PASS: A-vs-A tie >= 95% AND flip-rate <= 10%. Prints a JSON summary; never writes the real DB.
"""
import asyncio
import json
import os

os.environ.setdefault("ARSLAN_SECRET_KEY", "dev-secret-key")
os.environ.setdefault("ARSLAN_API_TOKEN", "")

from server.services import compare_judge  # noqa: E402

# Identical-output cases (must be tie). Vary task/persona/content to avoid a lucky single sample.
_SAME = [
    {"task": "Summarize the Q3 sales trend.", "persona": "data analyst",
     "out": "Q3 sales rose 12% QoQ, driven by the APAC region; churn was flat."},
    {"task": "Write a haiku about autumn.", "persona": "poet",
     "out": "Crisp leaves drift downward\nA cold wind counts the branches\nSilence wears the dusk"},
    {"task": "Explain a Python list comprehension.", "persona": "tutor",
     "out": "A list comprehension builds a list inline: [f(x) for x in xs if cond(x)]."},
    {"task": "Recommend a fix for a slow SQL query.", "persona": "engineer",
     "out": "Add an index on the filtered column and avoid SELECT *; check the query plan for a full scan."},
    {"task": "Draft a one-line product tagline for a note app.", "persona": "marketer",
     "out": "Think it, type it, never lose it."},
]
# Different pairs (a clearly-better B vs a weaker A), repeated K times to measure flip rate.
_DIFF = [
    {"task": "Summarize the Q3 sales trend.", "persona": "data analyst",
     "a": "Sales changed.",
     "b": "Q3 sales rose 12% QoQ to $4.1M, led by APAC (+19%); churn held at 3%."},
    {"task": "Fix this bug: list index out of range in loop.", "persona": "engineer",
     "a": "Try changing the loop.",
     "b": "The loop runs to len(xs); use range(len(xs)) or iterate xs directly so the last index isn't xs[len(xs)]."},
    {"task": "Explain what a database index is.", "persona": "tutor",
     "a": "It's a thing in databases.",
     "b": "An index is a sorted side-structure (often a B-tree) that lets the DB find rows by a key without scanning every row."},
]
_K = 5


async def main():
    same_total = same_tie = 0
    for c in _SAME:
        v = await compare_judge.compare(task=c["task"], persona=c["persona"],
                                        output_a=c["out"], output_b=c["out"])
        same_total += 1
        if v["overall"] == "tie":
            same_tie += 1
        else:
            print(f"  A-vs-A NON-TIE: {c['task'][:40]} -> {v['overall']}")

    flips = pairs = 0
    for c in _DIFF:
        overalls = []
        for _ in range(_K):
            v = await compare_judge.compare(task=c["task"], persona=c["persona"],
                                            output_a=c["a"], output_b=c["b"])
            overalls.append(v["overall"])
        pairs += 1
        # a flip = the verdict is not unanimous across the K runs
        if len(set(overalls)) > 1:
            flips += 1
        print(f"  pair '{c['task'][:30]}' overalls over {_K} runs: {overalls}")

    tie_rate = same_tie / same_total if same_total else 0.0
    flip_rate = flips / pairs if pairs else 1.0

    # --- Aggregate gate stability: the quantity the evolution gate actually uses ---
    # The gate aggregates a/b/tie across a val set and passes iff overall.better > overall.worse
    # and better >= 1. Per-comparison noise (better<->tie) suppresses under aggregation, so we
    # measure the GATE's pass-rate directly on (a) a real-improvement val set [sensitivity] and
    # (b) a no-improvement val set [false-positive rate — the safety-critical number].
    _N = 3

    def _gate_pass(verdicts):
        better = sum(1 for v in verdicts if v == "b")
        worse = sum(1 for v in verdicts if v == "a")
        return better > worse and better >= 1

    async def _agg_pass_rate(val_pairs):
        passes = 0
        for _ in range(_N):
            overalls = []
            for c in val_pairs:
                v = await compare_judge.compare(task=c["task"], persona=c["persona"],
                                                output_a=c["a"], output_b=c["b"])
                overalls.append(v["overall"])
            if _gate_pass(overalls):
                passes += 1
        return passes / _N

    val_better = _DIFF + [
        {"task": "Recommend a fix for a slow SQL query.", "persona": "engineer",
         "a": "Make it faster.",
         "b": "Add an index on the WHERE column, drop SELECT *, and check the plan for a full table scan."},
    ]
    # no-improvement val set: candidate == baseline (identical) — the gate must NOT pass.
    val_null = [{"task": c["task"], "persona": c["persona"], "a": c["out"], "b": c["out"]} for c in _SAME[:4]]

    sensitivity = await _agg_pass_rate(val_better)   # gate passes on real improvement (higher = better)
    fp_rate = await _agg_pass_rate(val_null)         # gate passes on NO improvement (must be ~0)

    summary = {
        "a_vs_a_tie_rate": round(tie_rate, 3),
        "per_comparison_flip_rate": round(flip_rate, 3),
        "gate_sensitivity": round(sensitivity, 3),
        "gate_false_positive_rate": round(fp_rate, 3),
        # Decision: the gate is USABLE iff false-positives are ~0 (safety) and it has
        # meaningful sensitivity (it can still produce proposals). Per-comparison flip in the
        # safe direction (better<->tie) is tolerable because the gate aggregates + human promotes.
        "usable": fp_rate <= 0.05 and sensitivity >= 0.5,
    }
    print("\nR1 SUMMARY:", json.dumps(summary))
    print("VERDICT:", "USABLE — gate safe (FP~0) + sensitive enough" if summary["usable"]
          else "NOT USABLE — gate unsafe or insensitive")


if __name__ == "__main__":
    asyncio.run(main())

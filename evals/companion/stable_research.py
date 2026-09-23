"""Additive runner freeze for R2; preserve its reviewed public-input preflight."""
import hashlib
import json

from evals.companion import stable_budget as budget
from evals.companion.stable_live import persist

CASE = "S2-R2"
RUNNER = "tests/server/test_stable_research_live.py"


def plan():
    raw = (budget.EVIDENCE / f"{CASE}-preflight.json").read_bytes()
    ready = json.loads(raw)
    if (ready["contract_sha256"] != budget.contract()[1] or ready["status"] != "ready"
            or not ready.get("public_same_scope_conflict_review") or len(ready["urls"]) != 2):
        raise RuntimeError("stable_research_inputs_unready")
    for item in ready["inputs"]:
        if hashlib.sha256((budget.EVIDENCE / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("stable_research_input_changed")
    return {"case": CASE, "preflight_sha256": hashlib.sha256(raw).hexdigest(),
        "runner_sha256": hashlib.sha256((budget.ROOT / RUNNER).read_bytes()).hexdigest(),
        "prompt": ready["prompt"] + "\n来源：\n" + "\n".join(ready["urls"]) +
            "\n请调用 web_extract 实际读取两个页面，可以同一轮读取两页。"
            "把简短中文对照和直接来源链接实际写入 comparison.md，然后 read_file 重新打开核对。"
            "仅授权这个相对路径；不要只贴代码块，也不要重复读取失败的网址。",
        "limits": "Original R2 cap 4; same 36/$5 ledger, no automatic retry or reallocation",
        "transport": "Actual production public GET, raw bytes must match archives; configured proxy may delegate address pinning and is recorded",
        "quality_status": "not_run", "native_status": "not_run"}


def freeze():
    value = plan()
    persist(budget.EVIDENCE / f"{CASE}-runner-plan-v1.json", value)
    return value


def verified():
    value = plan()
    path = budget.EVIDENCE / f"{CASE}-runner-plan-v1.json"
    if json.loads(path.read_bytes()) != value:
        raise RuntimeError("stable_research_runner_changed")
    return value


if __name__ == "__main__":
    budget.status()
    freeze()
    print("R2 additive runner frozen; no model calls")

"""Additive research freezes; preserve prior preflights and paid-run evidence."""
import hashlib
import json

from evals.companion import stable_budget as budget
from evals.companion.stable_live import persist

CASES = ("S2-R2", "S2-R4")
RUNNER = "tests/server/test_stable_research_live.py"


def plan(case):
    if case not in CASES:
        raise ValueError("stable_research_case_unknown")
    raw = (budget.EVIDENCE / f"{case}-preflight.json").read_bytes()
    ready = json.loads(raw)
    if (ready["contract_sha256"] != budget.contract()[1] or ready["status"] != "ready"
            or (case == "S2-R2" and not ready.get("public_same_scope_conflict_review"))
            or ready["case"] != case or len(ready["urls"]) != 2):
        raise RuntimeError("stable_research_inputs_unready")
    for item in ready["inputs"]:
        if hashlib.sha256((budget.EVIDENCE / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("stable_research_input_changed")
    return {"case": case, "preflight_sha256": hashlib.sha256(raw).hexdigest(),
        "runner_sha256": hashlib.sha256((budget.ROOT / RUNNER).read_bytes()).hexdigest(),
        "prompt": ready["prompt"] + "\n来源：\n" + "\n".join(ready["urls"]) +
            "\n请调用 web_extract 实际读取两个页面，可以同一轮读取两页。"
            "把简短中文对照和直接来源链接实际写入 comparison.md，然后 read_file 重新打开核对。"
            "仅授权这个相对路径；不要只贴代码块，也不要重复读取失败的网址。" +
            ("\n这两份 README 较长，请使用 web_extract 的 max_chars=40000；若仍有截断须明确披露。"
             if case == "S2-R4" else ""),
        "limits": f"Original {case} cap 4; same 36/$5 ledger, no automatic retry or reallocation",
        "transport": "Actual production public GET, raw bytes must match archives; configured proxy may delegate address pinning and is recorded",
        "quality_status": "not_run", "native_status": "not_run"}


def freeze(case):
    value = plan(case)
    persist(budget.EVIDENCE / f"{case}-runner-plan-v1.json", value)
    return value


def verified(case):
    value = plan(case)
    path = budget.EVIDENCE / f"{case}-runner-plan-v1.json"
    if json.loads(path.read_bytes()) != value:
        raise RuntimeError("stable_research_runner_changed")
    return value


def freeze_public_inputs(case):
    if case != "S2-R4":
        raise ValueError("only_unrun_R4_public_inputs")
    manifest = json.loads((budget.ROOT / "evals/companion/stage2-public-sources.json").read_bytes())
    selected = next(item for item in manifest["cases"] if item["id"] == case)
    inputs, urls = [], []
    for identity in selected["sources"]:
        source = next(item for item in manifest["sources"] if item["id"] == identity)
        url = f"https://raw.githubusercontent.com/{source['repository']}/{source['commit']}/{source['path']}"
        metadata = json.loads((budget.EVIDENCE / "public-inputs" / f"{identity}.json").read_bytes())
        path = budget.EVIDENCE / "public-inputs" / metadata["file"]
        if metadata["url"] != url or hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise RuntimeError("stable_public_input_changed")
        inputs.append({"path": str(path.relative_to(budget.EVIDENCE)), "sha256": source["sha256"]})
        urls.append(url)
    persist(budget.EVIDENCE / f"{case}-preflight.json", {"case": case, "status": "ready",
        "contract_sha256": budget.contract()[1], "inputs": inputs, "urls": urls,
        "prompt": selected["prompt"], "acceptance": next(item["acceptance"] for item in budget.contract()[0]["cases"]
                                                        if item["id"] == case),
        "quality_status": "not_run", "native_status": "not_run"})


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=CASES)
    parser.add_argument("--public-inputs", action="store_true")
    args = parser.parse_args()
    budget.status()
    if args.public_inputs:
        freeze_public_inputs(args.case)
    freeze(args.case)
    print(f"{args.case} additive runner frozen; no model calls")

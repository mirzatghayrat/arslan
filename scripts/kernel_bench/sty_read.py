"""STY read test: the 20 prompts of sty_prompts.json, before and after the reply-style change.

Run every prompt once, each in a new conversation on a brand-new Arslan instance started from
`--repo` (that checkout's code and .venv), and save the final replies:

    BENCH_SANDBOX=none BENCH_ROUND=sty1 .venv/bin/python -m scripts.kernel_bench.sty_read \\
        --label before --repo <checkout> --out <dir>

Then write one blind page that puts the two versions side by side:

    .venv/bin/python -m scripts.kernel_bench.sty_read --compare before.json after.json --html read.html

and, once the user has exported their choices from that page, count them:

    .venv/bin/python -m scripts.kernel_bench.sty_read --tally sty-read-verdicts.json --key read.key.json

The page is blind: it holds no key, commit, seed or side label. Only the key file `--compare`
writes next to it says which reply is A in each row.

The runs go through the bench's own code: `runner.fresh_instance` (start_arslan.sh with
BENCH_REPO, empty data folder, stopped afterwards), `runner.command` + `runner._run` (the
Arslan driver, which points the instance at the metering proxy and sets its workspace to the run
folder), `runner.reply_text` / `runner.driver_out` (the reply and how the run ended) and
`runner.settle` / `runner.usage` (after-turn calls, cost). One instance per prompt, so nothing
one prompt leaves in memory reaches the next: prompt 5 asks what the user said "last time".
Task prompts (11-20) get a fresh fixture_sty folder as the run folder.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from scripts.kernel_bench import fixture_sty, runner

HERE = Path(__file__).resolve().parent
PROMPTS = HERE / "sty_prompts.json"
LABELS = ("before", "after")
CHOICES = ("better", "same", "worse")
# The cards a run offered, as the page names them. The bench answers them as runner/arslan_driver
# do; a schedule card is always declined (arslan_driver.TurnTracker), which prompt 10 must show.
CARD_NAMES = {
    "propose_schedule": "schedule card (the bench declined it)",
    "propose_run_command": "command card",
    "propose_workspace_write": "file write card",
    "propose_action": "action card",
    "propose_enroll_node": "device card (the bench declined it)",
}


def load_prompts(path: Path = PROMPTS) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def prompts_digest(path: Path = PROMPTS) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def run_label(label: str, pid: int, round_: str = "") -> str:
    """The meter label and run folder name: one per prompt, side and round (README: a reused label
    starts near the meter's per-run cap and overwrites the earlier folder)."""
    return f"arslan-STY{pid:02d}-{label}" + (f"-{round_}" if round_ else "")


def cards_offered(frames: Path) -> list[str]:
    """The card frames (`propose_*`) in a run's transcript, in order."""
    found = []
    if frames.exists():
        for line in frames.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                kind = json.loads(line).get("type", "")
            except (ValueError, AttributeError):
                continue
            if isinstance(kind, str) and kind.startswith("propose_"):
                found.append(kind)
    return found


def git_head(repo: Path) -> dict:
    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
        )
        return done.stdout.strip()

    return {"sha": git("rev-parse", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD")}


def preflight(repo: Path, model: str) -> None:
    """Refuse to start a paid run that the bench's rules would make wrong."""
    if os.environ.get("BENCH_SANDBOX") != "none":
        raise SystemExit(
            "set BENCH_SANDBOX=none (README: baselines and comparisons run without it)"
        )
    if not runner.ROUND:
        raise SystemExit("set BENCH_ROUND (one per round and model; labels must not be reused)")
    if (
        not (repo / "server" / "main.py").exists()
        or not (repo / ".venv" / "bin" / "uvicorn").exists()
    ):
        raise SystemExit(f"{repo}: not an Arslan checkout with a synced .venv")
    status = runner.proxy_for(model).rstrip("/").removesuffix("/c") + "/_status"
    try:
        with urllib.request.urlopen(status, timeout=3) as response:
            meter = json.loads(response.read())
    except OSError as exc:
        raise SystemExit(f"no metering proxy at {status} ({exc}): start_proxy.sh first") from exc
    print(
        f"meter: ${meter.get('total_peak_usd')} of ${meter.get('cap')} spent, "
        f"${meter.get('cand_cap')} per run",
        flush=True,
    )


def run_prompt(item: dict, label: str, model: str) -> dict:
    """One prompt, one new conversation, one brand-new instance."""
    name = run_label(label, item["id"], runner.ROUND)
    run = runner.ROOT / "runs" / name
    shutil.rmtree(run, ignore_errors=True)
    run.mkdir(parents=True)
    if item["needs_fixture"]:
        fixture_sty.fixture(str(run))
    with runner.fresh_instance(name, "arslan"):
        started = time.time()
        cmd, env = runner.command("arslan", name, run, item["prompt"], "", model=model)
        rc = runner._run(cmd, env, run)
        ended = time.time()
        out = runner.driver_out("arslan", run)
        reply = runner.reply_text("arslan", run)
        settled = runner.settle(name, started, ended)
    return {
        "id": item["id"],
        "kind": item["kind"],
        "lang": item["lang"],
        "prompt": item["prompt"],
        "reply": reply,
        "end": out.get("end"),
        "rc": rc,
        "wall_s": round(ended - started),
        "approvals": out.get("approvals", 0),
        "declined": out.get("declined", 0),
        "cards": cards_offered(Path(f"{run}.frames.jsonl")),
        "usage": runner.usage(name, started),
        "settled_s": settled,
        "run": name,
    }


def run_all(label: str, repo: Path, out_dir: Path, model: str, only: set[int] | None) -> Path:
    repo = repo.resolve()
    preflight(repo, model)
    os.environ["BENCH_REPO"] = str(repo)  # start_arslan.sh starts this checkout
    (runner.ROOT / "tmp").mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{label}.json"
    head = git_head(repo)
    doc = {
        "label": label,
        "repo": str(repo),
        "head": head,
        "model": model,
        "round": runner.ROUND,
        "prompts_sha": prompts_digest(),
        "replies": [],
    }
    if path.exists():  # --only reruns some prompts into the same file, on the same code
        old = json.loads(path.read_text(encoding="utf-8"))
        same = (old.get("head", {}).get("sha"), old.get("model"), old.get("prompts_sha"))
        if same != (head["sha"], model, doc["prompts_sha"]):
            raise SystemExit(
                f"{path} holds another checkout, model or prompt set; use another --out"
            )
        doc["replies"] = old.get("replies", [])
    for item in load_prompts():
        if only and item["id"] not in only:
            continue
        rec = run_prompt(item, label, model)
        doc["replies"] = [r for r in doc["replies"] if r["id"] != item["id"]] + [rec]
        doc["replies"].sort(key=lambda r: r["id"])
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        print(
            json.dumps(
                {"id": rec["id"], "end": rec["end"], "usd_peak": rec["usage"]["usd_peak"]},
                ensure_ascii=False,
            ),
            flush=True,
        )
    return path


# ---------------------------------------------------------------- the side-by-side page


_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__")
_ITALIC = re.compile(
    r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])|(?<!\w)_(?=\S)([^_\n]+?)(?<=\S)_(?!\w)"
)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBER = re.compile(r"^\s*\d+[.)]\s+(.*)$")


def _inline(escaped: str) -> str:
    """Inline code, bold and italics on text that is already HTML-escaped. Code spans are cut out
    first, so marks inside them stay literal."""
    parts = _CODE.split(escaped)
    out = []
    for i, part in enumerate(parts):
        if i % 2:
            out.append(f"<code>{part}</code>")
            continue
        part = _BOLD.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", part)
        part = _ITALIC.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", part)
        out.append(part)
    return "".join(out)


def render_md(text: str) -> str:
    """A small, safe Markdown subset: headings, bullet and numbered lists, paragraphs, fenced code,
    inline code, bold and italics. The text is HTML-escaped first and only these tags are added,
    so nothing in a reply can reach the page as markup. Anything else (tables, links, quotes) is
    shown as its plain text. Both sides of a row go through the same rendering."""
    lines = html.escape(text).split("\n")
    out: list[str] = []
    para: list[str] = []
    items: list[str] = []
    list_tag = ""

    def flush() -> None:
        nonlocal list_tag
        if para:
            out.append("<p>" + "<br>".join(_inline(x) for x in para) + "</p>")
            para.clear()
        if items:
            out.append(f"<{list_tag}>" + "".join(f"<li>{_inline(x)}</li>" for x in items))
            out.append(f"</{list_tag}>")
            items.clear()
            list_tag = ""

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            flush()
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            out.append("<pre><code>" + "\n".join(code) + "</code></pre>")
        elif not line.strip():
            flush()
        elif m := _HEADING.match(line):
            flush()
            out.append(f'<p class="md-h">{_inline(m.group(2))}</p>')
        elif m := _BULLET.match(line) or _NUMBER.match(line):
            tag = "ul" if _BULLET.match(line) else "ol"
            if para or (items and list_tag != tag):
                flush()
            list_tag = tag
            items.append(m.group(1))
        else:
            if items:
                flush()
            para.append(line)
        i += 1
    flush()
    return "".join(out)


def _side(rec: dict | None) -> str:
    if rec is None:
        return '<p class="missing">(no reply recorded)</p>'
    parts = []
    text = rec.get("reply") or ""
    parts.append(
        f'<div class="reply">{render_md(text)}</div>'
        if text.strip()
        else '<p class="missing">(empty reply)</p>'
    )
    notes = []
    if rec.get("end") not in (None, "done"):
        notes.append(f"run ended: {rec.get('end')}")
    notes += [CARD_NAMES.get(c, c) for c in rec.get("cards", [])]
    if notes:
        parts.append(f'<p class="meta">{html.escape(" · ".join(notes))}</p>')
    return "".join(parts)


PAGE_CSS = """
:root { --bg: #f7f6f2; --fg: #1d1d1b; --muted: #6b6a64; --card: #ffffff; --line: #dedcd4;
  --accent: #2f5d50; --reply: #fbfaf7; --code: #efede6; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { --bg: #161615; --fg: #ecebe6; --muted: #a09f98; --card: #1f1f1d;
    --line: #34332f; --accent: #8fc2b0; --reply: #252522; --code: #2e2e2a; }
}
:root[data-theme="dark"] { --bg: #161615; --fg: #ecebe6; --muted: #a09f98; --card: #1f1f1d;
  --line: #34332f; --accent: #8fc2b0; --reply: #252522; --code: #2e2e2a; }
* { box-sizing: border-box; }
html { background: var(--bg); }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; }
main { max-width: 1200px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 8px; }
p.lead { color: var(--muted); margin: 0 0 16px; max-width: 70ch; }
.bar { position: sticky; top: 0; z-index: 1; background: var(--bg); padding: 10px 0;
  border-bottom: 1px solid var(--line); display: flex; gap: 12px; align-items: center;
  flex-wrap: wrap; }
button { font: inherit; color: var(--bg); background: var(--accent); border: 0;
  border-radius: 6px; padding: 6px 14px; cursor: pointer; }
.row { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  margin: 16px 0; padding: 14px; }
.row h2 { font-size: 15px; margin: 0 0 4px; font-weight: 600; }
.tag { color: var(--muted); font-size: 13px; }
.prompt { margin: 6px 0 10px; font-size: 16px; }
.watch { color: var(--accent); font-size: 13px; margin: 0 0 10px; }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.side h3 { font-size: 13px; margin: 0 0 4px; color: var(--muted); }
.reply { word-break: break-word; background: var(--reply);
  border: 1px solid var(--line); border-radius: 8px; padding: 2px 12px; }
.reply p, .reply ul, .reply ol, .reply pre { margin: 8px 0; }
.reply ul, .reply ol { padding-left: 22px; }
.reply .md-h { font-weight: 600; }
.reply code { font: 13px/1.4 ui-monospace, Menlo, monospace; background: var(--code);
  border-radius: 4px; padding: 0 3px; }
.reply pre { white-space: pre-wrap; background: var(--code); border-radius: 6px; padding: 8px; }
.reply pre code { padding: 0; background: none; }
.missing, .meta { color: var(--muted); font-size: 13px; margin: 6px 0 0; }
.judge { margin-top: 10px; display: flex; gap: 14px; flex-wrap: wrap; align-items: center; }
.judge textarea { width: 100%; min-height: 44px; font: inherit; color: var(--fg);
  background: var(--reply); border: 1px solid var(--line); border-radius: 6px; padding: 6px; }
#export { width: 100%; min-height: 120px; font: 12px/1.4 ui-monospace, Menlo, monospace;
  color: var(--fg); background: var(--reply); border: 1px solid var(--line); border-radius: 6px; }
@media (max-width: 720px) { .pair { grid-template-columns: 1fr; } }
"""

# The page knows only its own id and the rows on it: which side is A is in the key file alone.
PAGE_JS = """
(function () {
  const PAGE = document.body.dataset.page;
  const ROWS = Array.from(document.querySelectorAll('.row'));
  const store = 'sty-read:' + PAGE;
  let state = {};
  try { state = JSON.parse(localStorage.getItem(store) || '{}') || {}; } catch (e) { state = {}; }
  function save() { try { localStorage.setItem(store, JSON.stringify(state)); } catch (e) {} }
  function count() {
    const n = ROWS.filter(row => (state[row.dataset.id] || {}).choice).length;
    document.getElementById('count').textContent = n + ' / ' + ROWS.length + ' judged';
  }
  ROWS.forEach(row => {
    const id = row.dataset.id;
    const s = state[id] || {};
    row.querySelectorAll('input[type=radio]').forEach(r => {
      if (s.choice === r.value) r.checked = true;
      r.addEventListener('change', () => {
        state[id] = Object.assign({}, state[id], {choice: r.value}); save(); count();
      });
    });
    const note = row.querySelector('textarea');
    note.value = s.note || '';
    note.addEventListener('input', () => {
      state[id] = Object.assign({}, state[id], {note: note.value}); save();
    });
  });
  document.getElementById('do-export').addEventListener('click', () => {
    const rows = ROWS.map(row => {
      const s = state[row.dataset.id] || {};
      return {id: Number(row.dataset.id), choice: s.choice || null, note: s.note || ''};
    });
    const out = JSON.stringify({page: PAGE, rows: rows}, null, 1);
    document.getElementById('export').value = out;
    try {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([out], {type: 'application/json'}));
      a.download = 'sty-read-verdicts.json';
      document.body.appendChild(a); a.click(); a.remove();
    } catch (e) {}
  });
  count();
})();
"""


def _load_side(path: Path, label: str) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("label", label) != label:
        raise SystemExit(f"{path} is labelled {doc.get('label')!r}; expected {label!r}")
    return doc


def key_path(html_path: Path) -> Path:
    return html_path.with_suffix(".key.json")


def compare(before: Path, after: Path, out: Path, seed: int | None = None) -> dict:
    """Write the blind side-by-side page and its key file; return the key. A and B are shuffled
    per row. The page holds no key, no commit, no seed and no side label: only an opaque page id
    (a hash), so nothing in it links a column to a version. `<out>.key.json` holds the key;
    keep it away from the reader."""
    sides = {"before": _load_side(before, "before"), "after": _load_side(after, "after")}
    by_id = {lab: {r["id"]: r for r in doc.get("replies", [])} for lab, doc in sides.items()}
    seed = secrets.randbits(32) if seed is None else seed
    rng = random.Random(seed)
    heads = {lab: doc.get("head", {}) for lab, doc in sides.items()}
    page = hashlib.sha256(
        json.dumps(
            [heads, seed, sides["before"].get("round"), sides["after"].get("round")]
        ).encode()
    ).hexdigest()[:12]
    rows, key_rows = [], []
    for item in load_prompts():
        pid = item["id"]
        for lab in LABELS:
            rec = by_id[lab].get(pid)
            if rec is not None and rec.get("prompt") != item["prompt"]:
                raise SystemExit(f"{lab}: prompt {pid} differs from sty_prompts.json")
        order = ["before", "after"]
        rng.shuffle(order)
        key_rows.append({"id": pid, "a": order[0], "b": order[1]})
        watch = (
            f'<p class="watch">Check: {html.escape(item["watch"])}</p>' if item.get("watch") else ""
        )
        radios = "".join(
            f'<label><input type="radio" name="r{pid}" value="{c}"> {c}</label>' for c in CHOICES
        )
        rows.append(
            f'<section class="row" data-id="{pid}">'
            f'<h2>{pid}. <span class="tag">{item["kind"]} · {item["lang"]}</span></h2>'
            f'<p class="prompt">{html.escape(item["prompt"])}</p>{watch}'
            f'<div class="pair"><div class="side"><h3>A</h3>{_side(by_id[order[0]].get(pid))}</div>'
            f'<div class="side"><h3>B</h3>{_side(by_id[order[1]].get(pid))}</div></div>'
            f'<div class="judge"><span>B compared with A:</span>{radios}'
            f'<textarea placeholder="Note (optional)" aria-label="Note for prompt {pid}">'
            f"</textarea></div></section>"
        )
    key = {
        "page": page,
        "seed": seed,
        "before": heads["before"],
        "after": heads["after"],
        "rows": key_rows,
    }
    doc = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>STY read test</title><style>{PAGE_CSS}</style></head>"
        f'<body data-page="{page}"><main><h1>STY read test</h1>'
        '<p class="lead">Twenty prompts, two versions of Arslan. In every row, which reply is A and '
        "which is B is shuffled. For each row, say whether B is better, the same or worse than A, "
        "and add a note if you like. Chat: did it get colder, or caring in a fake way? Task "
        "reports: did they get wordier, or clipped like a telegram? Formatting is simplified the "
        "same way on both sides: bold, italics, code, headings and lists are shown; tables and "
        "links appear as plain text. Choices stay in this browser; export them when you are "
        "done.</p>"
        '<div class="bar"><span id="count"></span><button id="do-export" type="button">'
        "Export choices (JSON)</button></div>"
        f"{''.join(rows)}"
        '<h2>Export</h2><textarea id="export" readonly aria-label="Exported choices"></textarea>'
        f"</main><script>{PAGE_JS}</script></body></html>"
    )
    out.write_text(doc, encoding="utf-8")
    key_path(out).write_text(json.dumps(key, indent=1), encoding="utf-8")
    return key


def tally(verdicts: Path, key_file: Path) -> dict:
    """Unblind an exported verdict file with the key `--compare` wrote: for each row, how `after`
    compares with `before`. Refuses a verdict file from another page, and one whose rows are not
    exactly the key's rows (a duplicate, a missing or an unknown id, an unknown choice)."""
    doc = json.loads(verdicts.read_text(encoding="utf-8"))
    key = json.loads(key_file.read_text(encoding="utf-8"))
    if doc.get("page") != key.get("page"):
        raise SystemExit(
            f"{verdicts} is from page {doc.get('page')!r}; {key_file} is for page {key.get('page')!r}"
        )
    ids = [row.get("id") for row in doc.get("rows", [])]
    dupes = sorted({i for i in ids if ids.count(i) > 1}, key=str)
    if dupes:
        raise SystemExit(f"{verdicts}: rows {dupes} appear more than once")
    sides = {r["id"]: r for r in key["rows"]}
    missing, unknown = sorted(set(sides) - set(ids)), sorted(set(ids) - set(sides), key=str)
    if missing or unknown:
        raise SystemExit(f"{verdicts}: rows missing {missing}, rows not on the page {unknown}")
    flip = {"better": "worse", "worse": "better", "same": "same"}
    kinds = {p["id"]: (p["kind"], p["lang"]) for p in load_prompts()}
    rows, totals = [], {}
    for row in sorted(doc["rows"], key=lambda r: r["id"]):
        choice = row.get("choice")
        if choice is not None and choice not in CHOICES:
            raise SystemExit(f"{verdicts}: row {row['id']} has choice {choice!r}")
        if choice is None:
            verdict = None
        elif sides[row["id"]]["b"] == "after":
            verdict = choice
        else:
            verdict = flip[choice]
        kind, lang = kinds.get(row["id"], ("?", "?"))
        rows.append({"id": row["id"], "after_vs_before": verdict, "note": row.get("note", "")})
        for group in ("all", kind, f"{kind}-{lang}"):
            bucket = totals.setdefault(group, {"better": 0, "same": 0, "worse": 0, "unjudged": 0})
            bucket[verdict or "unjudged"] += 1
    return {"page": key["page"], "totals": totals, "rows": rows}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--label", choices=LABELS)
    ap.add_argument("--repo", type=Path, help="the Arslan checkout to start (its own .venv)")
    ap.add_argument("--out", type=Path, help="folder for <label>.json")
    ap.add_argument("--model", default=runner.MODEL)
    ap.add_argument("--only", default="", help="comma-separated prompt ids, e.g. 5,10")
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("BEFORE", "AFTER"))
    ap.add_argument("--html", type=Path)
    ap.add_argument("--seed", type=int, help="the shuffle seed (default: random, recorded)")
    ap.add_argument("--tally", type=Path, metavar="VERDICTS")
    ap.add_argument("--key", type=Path, help="with --tally: the .key.json --compare wrote")
    a = ap.parse_args(argv)
    if a.tally:
        if not a.key:
            ap.error("--tally needs --key (the .key.json next to the page)")
        print(json.dumps(tally(a.tally, a.key), ensure_ascii=False, indent=1))
    elif a.compare:
        if not a.html:
            ap.error("--compare needs --html")
        key = compare(a.compare[0], a.compare[1], a.html, a.seed)
        print(f"wrote {a.html} and {key_path(a.html)} (seed {key['seed']})")
    else:
        if not (a.label and a.repo and a.out):
            ap.error("a run needs --label, --repo and --out")
        only = {int(x) for x in a.only.split(",") if x.strip()} or None
        print(f"wrote {run_all(a.label, a.repo, a.out, a.model, only)}")


if __name__ == "__main__":
    main(sys.argv[1:])

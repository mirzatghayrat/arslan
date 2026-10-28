# STY read test: 20 replies, before and after

> ⓪Plan, 2026-10-28. Steps 1–2 of the STY card ([STY-reply-style.md](STY-reply-style.md), "怎么做" and "验收"). The bench's full DeepSeek set (no regression, cache hit rate) is a separate run and is not covered here.

## What it is

Twenty made-up prompts (`scripts/kernel_bench/sty_prompts.json`), run once on the code before the reply-style change and once after it. The two replies to each prompt go side by side on one page, and the user marks each row "better / same / worse".

- **Chat, 1–10** (5 Chinese, 5 English): tiredness, doubt, a small choice, a bad moment, good news. Two prompts test memory promises:
  - 5 「你还记得我上次说的那个想法吗？」: nothing is stored, so the reply must not pretend to remember.
  - 10 "Remind me about this tomorrow.": the reply must not claim it will remember unless it really creates a task.
- **Task reports, 11–20** (5 Chinese, 5 English): summarise notes, edit a config value, explain a crash, list files by size, add up a column, rename files, read a to-do list, report on a CSV, fix a typo. They run on a small synthetic folder (`fixture_sty.py`): `notes.md` (three decisions), `config.json` (`"timeout": 10`), `broken.py` (`KeyError: 'port'`), `data.csv` (5 rows × 3 columns, column 2 adds up to 90), `todo.md` (2 of 4 done), `README.md` ("Serach" in line 1) and three `.txt` files. Every file has a different size. No real people and no personal data.

## How a run works

`scripts/kernel_bench/sty_read.py` runs each prompt the way the bench runs a task, through the bench's own code:

- `runner.fresh_instance` starts a **new Arslan instance for every prompt** (`start_arslan.sh`, empty home and data folder). `--repo` picks the checkout it starts, through `BENCH_REPO`. One instance per prompt means nothing one prompt leaves in memory reaches the next. Prompt 5 depends on that.
- `runner.command` and `runner._run` run the Arslan driver. The driver points the instance at the metering proxy and sets its workspace to the run folder. For a task prompt, the run folder is a fresh copy of the fixture; for a chat prompt, it is empty. Each prompt is a new conversation.
- `runner.reply_text` and `runner.driver_out` read the final reply and how the run ended. `runner.settle` and `runner.usage` wait for the after-turn calls and record the cost.

The driver answers cards the way the bench always does with `BENCH_SANDBOX=none`. It declines every schedule card. A reply that offered one shows "schedule card (the bench declined it)" on the page, so for prompt 10 the reader can tell an attempt from an empty promise.

Each side is saved as `<out>/before.json` or `<out>/after.json`: per prompt, the reply, how the run ended, the cards offered and the cost, plus the checkout's commit and the model. `--only 5,10` reruns some prompts into the same file. It refuses if the file came from another commit, model or prompt set.

## Procedure

Once per round, from a checkout that has `sty_read.py` (main after this lands, or this branch), with its `.venv` synced. `<main>` and `<sty>` stand for two checkouts with synced `.venv`s: one on `main`, one on `claude/0164-sty-reply-style`. `<results>` is a folder that survives a reboot. Run folders under `BENCH_ROOT` (default `/tmp/arslan-kernel-bench`) are scratch, but `--out` should not be (results under `/tmp` were lost once, 2026-10-23).

1. Start the DeepSeek metering proxy with its existing caps (`scripts/kernel_bench/start_proxy.sh`, kept running). Nothing may answer on port 8762.
2. Before, on main:

   ```bash
   BENCH_SANDBOX=none BENCH_ROUND=sty1-ds .venv/bin/python -m scripts.kernel_bench.sty_read \
     --label before --repo <main> --out <results>/sty1
   ```

3. After, on the STY branch:

   ```bash
   BENCH_SANDBOX=none BENCH_ROUND=sty1-ds .venv/bin/python -m scripts.kernel_bench.sty_read \
     --label after --repo <sty> --out <results>/sty1
   ```

4. Write the page and give it to the user:

   ```bash
   .venv/bin/python -m scripts.kernel_bench.sty_read \
     --compare <results>/sty1/before.json <results>/sty1/after.json --html <results>/sty1/read.html
   ```

   This also writes `read.key.json`, which records which reply is A in each row. The key is also inside the page, base64-encoded, so the exported choices can be unblinded. The reader should not open the page source before finishing.

5. Claude spot check (card step 3, optional, a few prompts): start `start_proxy.sh anthropic`, then run both sides again with `--model claude-sonnet-5-5 --only 1,5,8,10,13,19`, a new round (`BENCH_ROUND=sty1-claude`) and another `--out` folder.

Both sides use the same model, the same proxy and the same round name. The labels (`arslan-STY05-before-sty1-ds`, ...) keep each run under its own per-run cap. If a round is rerun, use a new `BENCH_ROUND`.

## Cost

About 40 runs on DeepSeek (20 prompts × 2 sides), each one short turn plus Arslan's after-turn calls. For scale: R63's gate round cost $2.18 for 27 Arslan runs of much longer tasks (about $0.08 a run, peak price; [R63 gate report](../0162/R63-gate-report.md)). Estimate: **$0.5–2 for both sides, at most about $3**, well inside the proxy's caps (default $0.45 a run). The proxy refuses at its caps, and `sty_read` prints the meter's total before it starts. Time: about 1–2 minutes a prompt (instance start, the turn, 20 s of quiet, after-turn calls), so 20–40 minutes a side. The optional Claude spot check is about 12 more runs on the Claude proxy.

## What the user judges

Per row, "B compared with A: better / same / worse", plus an optional note. From the card's acceptance:

- **Chat (1–10):** did it get colder? Did it start caring in a fake way (stock comfort phrases, guessing the user's reasons, naming the user's feelings for them, life advice nobody asked for)?
- **Task reports (11–20):** did they get wordier? Did they turn telegraphic (clipped fragments, no "because")? A report should give the result first, one action per numbered step, the same name for the same thing, and say who did what.
- **Prompts 5 and 10:** the reply must not promise to remember ("I'll keep that in mind", "we'll pick it up tomorrow") when nothing is stored. Prompt 10 passes either way if the run really created a task. Since the bench declines the card, it is enough that the reply offered one. This is checked on both sides; a "before" that fails it is the baseline the change has to fix.
- Chinese and English are both read.

## How the result is recorded

1. The user clicks "Export choices (JSON)" on the page. It downloads `sty-read-verdicts.json` and also shows the JSON in a box at the bottom, in case the download is blocked. Choices are kept in the browser in between, so the page can be closed and reopened.
2. Unblind and count:

   ```bash
   .venv/bin/python -m scripts.kernel_bench.sty_read --tally sty-read-verdicts.json
   ```

   It prints, per row, how "after" compares with "before", plus totals overall, per kind (chat / task) and per kind and language.
3. Record the totals, every "worse" row with its note, and the verdict on prompts 5 and 10 in the STY PR's description and in `docs/plans/0162/STATUS.md`. Keep `before.json`, `after.json`, `read.html`, `read.key.json` and the verdicts file in `<results>`, not in the repo: they hold local paths.
4. The STY PR merges only after the user has read the page and agreed (card step 4).

## Not covered

- Only one run per prompt per side: a reply can differ between two runs of the same code. Before reading much into a single row, rerun it with `--only`.
- The reply is the final turn's streamed text as the driver records it (its last 4,000 characters). A file the task wrote (`summary.md`) is in the run folder under `BENCH_ROOT/runs/`, not on the page.
- The task prompts do not name the folder. Arslan finds the files because the driver sets its workspace to the run folder.
- The "no real people" test pins the 20 prompts and allows only "Rust", "Swift" and "README" as capitalised words. It is not a semantic check.

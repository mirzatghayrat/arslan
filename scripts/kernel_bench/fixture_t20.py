"""T20 (v0.1.64 L7-0), a list that arrives in batches: 12 batches of 2 synthetic notes.

The card's first draft had 4 batches of 6; the L7-0 pilot's `off` arm completed that in every run, so the same 24
notes came in 6 batches of 4. With chained batches the third pilot round still completed that in 3 of 3 runs (12 to
28 model calls, about $0.13 a run), so the same 24 notes now come in 12 batches of 2 (the card: more stages). Done by
hand, a batch of 2 takes about 7 tool calls (read 2 notes, write 2 summaries and the index, run the check, list the
folder), so the whole task is about 84, past the standard tier's 80 in one turn; the notes and summaries are the same
size as before, so the tokens per run stay about the same. Each note has a unique code word and a date. Only batch 1
(`notes/n01.md` and `n02.md`) is on disk at the start.
`inbox_check.py --batches batches.dat` checks the summaries of the notes present: `summaries/<same name>.md` has
exactly two sentences (split on `.`, `!` and `?`) holding the note's code word and date, and `summaries/index.md`
names every note. When they pass, it drops the next batch (from the encoded `batches.dat`) into `notes/` and exits 1;
once batch 12 passes, it exits 0. The check is stateless: the batches present are the notes on disk.

Chained: batch 1 is on disk; batches 2 to 12 are sealed in `batches.dat`, each under a key derived from the name, code
word and date of every note in the batch before (goal_tasks.SEAL). The check derives the key only once every summary of
that batch holds its note's code word and date, so a summary that misses one opens nothing. The pilot's worker decoded
the first draft's `batches.dat` and could read every note at once; now the data file shows no note past batch 1.
Residual, disclosed: here stage k's correct output (the code words and dates) is also in stage k's notes, so a worker
that re-implements the check's key derivation can open the next batch without writing the summaries. It still cannot
read batch k+1 before batch k is on disk, so the batches still arrive in order.
"""
from __future__ import annotations

import datetime
import json
import random
import secrets
from pathlib import Path

from scripts.kernel_bench import goal_tasks

BATCHES = 12
PER_BATCH = 2
WORDS_A = ("AMBER", "COBALT", "SILVER", "CEDAR", "ONYX", "SAFFRON", "HAZEL", "INDIGO", "COPPER", "IVORY", "JADE",
           "RUSSET", "SLATE", "TEAL", "OCHRE", "PEWTER")
WORDS_B = ("FALCON", "HERON", "LYNX", "OTTER", "MARTEN", "BADGER", "PLOVER", "WREN", "IBEX", "ORCA", "TAPIR", "VIPER")
TOPICS = (
    ("the supplier audit", "Two invoices were matched by hand and one is still open", "The team will chase the vendor"),
    ("the office move", "The movers confirmed the van and the keys go back on Friday", "Facilities owns the checklist"),
    ("the support backlog", "Thirty tickets were closed and four need a customer reply", "Weekend cover stays the same"),
    ("the quarterly budget", "Travel came in under plan while software went over", "Finance wants a revised forecast"),
    ("the hiring loop", "Three candidates finished the panel and one offer is drafted", "References are due next week"),
    ("the data migration", "The test copy loaded cleanly but two reports differ", "The cutover waits for sign-off"),
)

CHECK = '''"""Check the summaries of the notes present. When they pass, the next batch of notes arrives."""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
import zlib

sys.dont_write_bytecode = True

{decoder}
{seal}

def sentences(text):
    return [s for s in re.split(r"[.!?]", text) if s.strip()]


def field(text, name):
    found = re.search(r"^" + name + r": *(.+?) *$", text, re.M)
    return found.group(1) if found else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches", required=True)
    data = _decode(ap.parse_args().batches)
    per, total = data["per"], 1 + len(data["sealed"])
    present = sorted(n for n in os.listdir("notes") if n.endswith(".md")) if os.path.isdir("notes") else []
    problems, fields = [], {}
    index = open(os.path.join("summaries", "index.md")).read() if os.path.isfile("summaries/index.md") else None
    for name in present:
        note = open(os.path.join("notes", name)).read()
        code, day = field(note, "Code word"), field(note, "Date")
        fields[name] = [name, code, day]
        path = os.path.join("summaries", name)
        if not os.path.isfile(path):
            problems.append("%s: no summaries/%s" % (name, name))
            continue
        text = open(path).read()
        if len(sentences(text)) != 2:
            problems.append("%s: the summary has %d sentences, not 2" % (name, len(sentences(text))))
        for label, value in (("code word", code), ("date", day)):
            if value and value not in text:
                problems.append("%s: the summary does not include the note's %s" % (name, label))
        if index is None or name not in index:
            problems.append("%s: not listed in summaries/index.md" % name)
    for p in problems:
        print(p)
    done = len(present) // per
    if problems or not present:
        print("%d problem(s) in %d note(s)." % (len(problems), len(present)))
        return 1
    if done < total:
        # The next batch is sealed under the batch before's names, code words and dates (its summaries hold them).
        batch = [fields[name] for name in present[(done - 1) * per:done * per]]
        text = _unseal(data["sealed"][done - 1], _key(data["salt"], done, batch))
        if text is None:
            print("All %d notes pass, but batch %d's notes are not the ones the check sent. Restore notes/." % (
                len(present), done))
            return 1
        arrived = json.loads(text)
        for name, note in arrived:
            with open(os.path.join("notes", name), "w") as f:
                f.write(note)
        print("All %d notes pass. Batch %d of %d arrived: %d new notes in notes/." % (
            len(present), done + 1, total, len(arrived)))
        print("Run this check again.")
        return 1
    print("All %d notes pass. Every batch is done." % len(present))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''.replace("{decoder}", goal_tasks.DECODER).replace("{seal}", goal_tasks.SEAL)


def _notes(seed: int) -> list[tuple[str, str, str, str]]:
    rng = random.Random(seed)
    codes = rng.sample([f"{a}-{b}" for a in WORDS_A for b in WORDS_B], BATCHES * PER_BATCH)
    out = []
    for i, code in enumerate(codes, 1):
        day = (datetime.date(2026, 2, 1) + datetime.timedelta(days=rng.randrange(0, 200))).isoformat()
        topic, what, next_step = rng.choice(TOPICS)
        text = (f"# Note n{i:02d}\n\nDate: {day}\nCode word: {code}\n\n"
                f"This note is about {topic}. {what}. {next_step}. Questions go to the usual channel.\n")
        out.append((f"n{i:02d}.md", code, day, text))
    return out


def fixture(run: str, seed: int = 20) -> dict:
    root = Path(run)
    (root / "notes").mkdir(parents=True)
    notes = _notes(seed)
    for name, _, _, text in notes[:PER_BATCH]:
        (root / "notes" / name).write_text(text)
    salt = secrets.token_hex(8)
    batches = [notes[k * PER_BATCH:(k + 1) * PER_BATCH] for k in range(BATCHES)]
    sealed = [goal_tasks.seal(json.dumps([[name, text] for name, _, _, text in batches[k]]), goal_tasks.derive_key(
        salt, k, [[name, code, day] for name, code, day, _ in batches[k - 1]])) for k in range(1, BATCHES)]
    data = {"salt": salt, "per": PER_BATCH, "sealed": sealed}
    (root / "batches.dat").write_text(goal_tasks.encode(data) + "\n")
    (root / "inbox_check.py").write_text(CHECK)
    return {"sha256": {rel: goal_tasks.sha256(root / rel) for rel in ("inbox_check.py", "batches.dat")},
            "notes": {name: {"code": code, "date": day, "sha256": goal_tasks.sha256_text(text)}
                      for name, code, day, text in notes}}

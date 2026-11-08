"""History-free ordered verdict vectors, validated in full before any lookup."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path

GENERATOR_VERSION = 2
SOURCE_COMMITS = {"main": "3eec545b48b7f97f3047ce97037fbf10075abe6d",
                  "original": "9be27b5ff62c7dbd385b1fbf97be0246d06e26ca"}
CHAR_LEVELS = {"r": "run", "a": "ask", "f": "forbid"}


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()


def corpus_digest(rows):
    return fingerprint(json.dumps([(case, fingerprint(text)) for case, text in rows],
                                 separators=(",", ":")))


def encode(corpora, verdicts, source_hashes):
    metadata = {}
    sections = []
    for kind, rows in corpora.items():
        pairs = ["".join(level[0] for level in verdicts[kind + "/" + case][1:]) for case, _ in rows]
        metadata[kind] = dict(count=len(rows), corpus_sha256=corpus_digest(rows),
                              verdict_sha256=fingerprint(" ".join(pairs)))
        sections.append("[" + kind + "]\n" + "\n".join(
            " ".join(pairs[i:i + 128]) for i in range(0, len(pairs), 128)))
    header = dict(schema=2, generator_version=GENERATOR_VERSION, source_commits=SOURCE_COMMITS,
                  source_sha256=source_hashes, matrices=metadata)
    return ("# Ordered main/original verdict pairs: r=run a=ask f=forbid; one character per source row.\n"
            + "# " + json.dumps(header, separators=(",", ":")) + "\n" + "\n".join(sections) + "\n")


def decode(text, generators):
    lines = text.splitlines()
    assert len(lines) >= 2 and lines[1].startswith("# "), "Missing baseline provenance header"
    header = json.loads(lines[1][2:])
    assert header["schema"] == 2 and header["generator_version"] == GENERATOR_VERSION, "Unsupported baseline version"
    assert header["source_commits"] == SOURCE_COMMITS, "Unexpected baseline sources"
    assert list(header["matrices"]) == list(generators), "Baseline matrix membership/order mismatch"
    sections = {}
    kind = None
    for line in lines[2:]:
        if line.startswith("[") and line.endswith("]"):
            kind = line[1:-1]
            assert kind not in sections, f"Duplicate baseline matrix: {kind}"
            sections[kind] = []
        else:
            assert kind is not None, "Verdicts outside a baseline matrix"
            sections[kind].extend(line.split())
    assert list(sections) == list(generators), "Verdict matrix membership/order mismatch"
    cases = {}
    for kind, generate in generators.items():
        rows = list(generate())
        meta, pairs = header["matrices"][kind], sections[kind]
        assert len(rows) == len(pairs) == meta["count"], f"Baseline count mismatch: {kind}"
        assert corpus_digest(rows) == meta["corpus_sha256"], f"Baseline membership/order/text digest mismatch: {kind}"
        assert fingerprint(" ".join(pairs)) == meta["verdict_sha256"], f"Baseline verdict digest mismatch: {kind}"
        for (case, command), pair in zip(rows, pairs):
            key = kind + "/" + case
            assert key not in cases, f"Duplicate baseline case: {key}"
            assert len(pair) == 2 and set(pair) <= CHAR_LEVELS.keys(), f"Invalid baseline verdict: {key}"
            cases[key] = (fingerprint(command), *(CHAR_LEVELS[ch] for ch in pair))
    return cases


@lru_cache(maxsize=1)
def baselines():
    from tests.server.quoted_args_file_run_evidence import GENERATORS
    path = Path(__file__).with_name("quoted_args_baselines.txt")
    assert path.is_file(), "Missing quoted-argument baseline data; regenerate from the documented sources"
    return decode(path.read_text(), GENERATORS)


def levels(kind, case, text):
    key = kind + "/" + case
    data = baselines()  # All corpora validate before even the first lookup.
    assert key in data, f"Missing baseline case: {key}; regenerate the baseline data"
    digest, main, original = data[key]
    assert digest == fingerprint(text), f"Stale baseline case: {key}; regenerate the baseline data"
    return main, original

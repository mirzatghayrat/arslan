"""History-free ordered verdict vectors, validated in full before any lookup."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path

GENERATOR_VERSION = 2
SOURCE_COMMITS = {"main": "3eec545b48b7f97f3047ce97037fbf10075abe6d",
                  "original": "9be27b5ff62c7dbd385b1fbf97be0246d06e26ca"}
# BEGIN GENERATED SOURCE HASHES
SOURCE_SHA256 = {
    "main": {
        "shell_text.py": "9945605da48225cb5d6cf609f3419c61217a6ece6c7da7700b05a663d7e7c560",
        "shell_grammar.py": "a5da268e6d68be1d8fad8bea474445cf595b32aa28653ed813fddba85381072e",
        "terminal_policy.py": "2d1dcf613b797a263e2247468a2a091fbfeae6b10975e872b8132ff1d03f6256"
    },
    "original": {
        "shell_text.py": "9945605da48225cb5d6cf609f3419c61217a6ece6c7da7700b05a663d7e7c560",
        "shell_grammar.py": "9df83e76fd1f6bd366f9f52813d81d90842d2a0667933e25f165a9ff12c6d25d",
        "terminal_policy.py": "0aa7e22f5faefc3c132c02f8c8fe77561b0acb7214a9d4ba43112f42ecf5b82d"
    }
}
# END GENERATED SOURCE HASHES
CHAR_LEVELS = {"r": "run", "a": "ask", "f": "forbid"}


class _HeaderObject(list):
    """Preserve JSON object pairs, including duplicates, separately from arrays."""


def _header_value(value, path="$"):
    if isinstance(value, _HeaderObject):
        result = {}
        for key, child in value:
            child = _header_value(child, f"{path}/{key}")
            assert key not in result, (
                f"Duplicate baseline header key: {path}/{key}: "
                f"first {result.get(key)!r}, repeated {child!r}")
            result[key] = child
        return result
    if isinstance(value, list):
        return [_header_value(child, f"{path}/{index}") for index, child in enumerate(value)]
    return value


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


def validate_source_hashes(recorded):
    """Compare every source/file against committed trust metadata, without Git."""
    recorded = {} if recorded is None else recorded
    assert isinstance(recorded, dict), f"Invalid source-hash mapping: expected mapping, recorded {recorded!r}"
    # Complete both directions of membership before comparing any hash values.
    for source in sorted(SOURCE_SHA256.keys() | recorded.keys()):
        expected = SOURCE_SHA256.get(source, {})
        actual = recorded.get(source, {})
        assert source in SOURCE_SHA256 and isinstance(actual, dict), (
            f"Baseline source hash mismatch: {source}/<mapping>: expected {expected!r}, recorded {actual!r}")
        for name in sorted(expected.keys() | actual.keys()):
            assert name in expected, (
                f"Baseline source hash mismatch: {source}/{name}: expected <absent>, recorded {actual[name]}")
            assert source in recorded and name in actual, (
                f"Baseline source hash mismatch: {source}/{name}: expected {expected[name]}, recorded <missing>")
    for source, expected in SOURCE_SHA256.items():
        for name, wanted in expected.items():
            found = recorded[source][name]
            assert wanted == found, (
                f"Baseline source hash mismatch: {source}/{name}: expected {wanted}, recorded {found}")
    # This source is unchanged from main and is available in shallow checkouts.
    path = Path(__file__).resolve().parents[2] / "server/services/shell_text.py"
    wanted = SOURCE_SHA256["main"][path.name]
    assert path.is_file(), f"Baseline source hash mismatch: current/{path.name}: expected {wanted}, recorded <missing>"
    found = hashlib.sha256(path.read_bytes()).hexdigest()
    assert wanted == found, f"Baseline source hash mismatch: current/{path.name}: expected {wanted}, recorded {found}"


def decode(text, generators):
    lines = text.splitlines()
    if len(lines) < 2 or not lines[1].startswith("# "):
        validate_source_hashes(None)  # Reports the first missing file and its expected hash.
    header = _header_value(json.loads(lines[1][2:], object_pairs_hook=_HeaderObject))
    validate_source_hashes(header.get("source_sha256"))
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

"""History-free verdict lookup shared by the default evidence and regression suites."""
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()


@lru_cache(maxsize=1)
def baselines():
    path = Path(__file__).with_name("quoted_args_baselines.json.gz")
    if not path.is_file():
        raise AssertionError("Missing quoted-argument baseline data; regenerate it with the documented source-tree procedure")
    with gzip.open(path, "rt") as stream:
        data = json.load(stream)
    assert data["schema"] == 1, "Unsupported quoted-argument baseline schema"
    return data["cases"]


def levels(kind, case, text):
    key = kind + "/" + case
    assert key in baselines(), f"Missing baseline case: {key}; regenerate the baseline data"
    digest, main, original = baselines()[key]
    assert digest == fingerprint(text), f"Stale baseline case: {key}; regenerate the baseline data"
    return main, original

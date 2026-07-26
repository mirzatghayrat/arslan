#!/usr/bin/env python3
"""Compose the Tauri updater manifest (latest.json) from staged release assets.

Adapted from andrewyng/openworker's packaging/make_update_manifest.py
(MIT, Copyright (c) 2024 Andrew Ng).

Run by the release job once every platform build is staged in one directory:

    python3 make_update_manifest.py --version 0.1.0 --tag v0.1.0 \
        --repo mirzatghayrat/arslan --dist dist/ --out dist/latest.json

TWO DIFFERENT URLS, ON PURPOSE — the reason this file exists rather than a
one-line jq:

  * Installed apps POLL a stable address:
        releases/latest/download/latest.json
    so the endpoint baked into tauri.conf.json never has to change.

  * Every asset URL INSIDE the manifest is TAG-PINNED:
        releases/download/<tag>/<asset>
    never `latest/`. A manifest must reference exactly the artefacts it
    shipped with; a `latest/` asset URL would let a half-published or
    subsequently-superseded release hand an installed app a binary whose
    version does not match the manifest that offered it.

A platform whose artefact or .sig is missing is SKIPPED with a warning — a
mac-only hotfix should leave other platforms seeing no update, not a broken
one. An empty manifest is refused outright: publishing one would tell every
install that no update exists, which is indistinguishable from success.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys

# stable asset name -> Tauri platform key. The names must match what
# release.yml stages; a rename on one side alone silently drops the platform.
ARTIFACTS = {
    "Arslan-macos-arm64.app.tar.gz": "darwin-aarch64",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", required=True, help="bare version, e.g. 0.1.0")
    ap.add_argument("--tag", required=True, help="git tag the assets live under, e.g. v0.1.0")
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--dist", required=True, type=pathlib.Path, help="staged artefacts dir")
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--notes", default="", help="line shown in the update prompt")
    ap.add_argument(
        "--pub-date",
        default=None,
        help="RFC3339 timestamp; defaults to now. Explicit value keeps the "
        "manifest reproducible when a release is rebuilt.",
    )
    args = ap.parse_args()

    platforms: dict[str, dict[str, str]] = {}
    for asset, platform in ARTIFACTS.items():
        artifact = args.dist / asset
        sig = args.dist / (asset + ".sig")
        if not artifact.exists():
            print(f"warning: {asset} not in {args.dist} — skipping {platform}", file=sys.stderr)
            continue
        if not sig.exists():
            print(
                f"warning: {asset} has no .sig — skipping {platform} "
                "(an unsigned update is refused by the client, so offering it "
                "would produce a permanently failing update prompt)",
                file=sys.stderr,
            )
            continue
        platforms[platform] = {
            "signature": sig.read_text().strip(),
            "url": f"https://github.com/{args.repo}/releases/download/{args.tag}/{asset}",
        }

    if not platforms:
        print(
            "error: no signed updater artefacts found — refusing to write an "
            "empty manifest, which would silently tell every install that no "
            "update exists",
            file=sys.stderr,
        )
        return 1

    pub_date = args.pub_date or (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    manifest = {
        "version": args.version,
        "notes": args.notes,
        "pub_date": pub_date,
        "platforms": platforms,
    }
    args.out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {args.out} ({', '.join(sorted(platforms))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

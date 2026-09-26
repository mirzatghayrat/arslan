"""Offline packaged restore; no server, profile activation, or secret access."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
from server.services import backup


def read_manifest(path: Path) -> bytes:
    from server.services.memory_deletion_manifest import MAX_BYTES, decode

    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise ValueError("invalid_deletion_manifest")
        payload = handle.read(MAX_BYTES + 1)
    decode(payload)
    return payload


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(
        "Offline restore only. Stop ALL Arslan writers first. This command does not stop them, "
        "activate the restored directory, or change your encryption secret. "
        "Restored memories and schedules require review before use."))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--new-data-dir", type=Path, required=True)
    record = parser.add_mutually_exclusive_group(required=True)
    record.add_argument("--current-db-path", type=Path)
    record.add_argument("--new-machine", action="store_true",
                        help="Explicitly restore without a current installation; later records may be absent")
    parser.add_argument("--deletion-manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = read_manifest(args.deletion_manifest) if args.deletion_manifest else None
        result = backup.restore(args.archive, args.new_data_dir,
                                deletion_manifest=payload, current_db_path=args.current_db_path)
    except Exception as error:  # noqa: BLE001 — process boundary; never report success on failure
        # Do not expose archive content, credentials or arbitrary filesystem paths.
        code = "data_profile_in_use" if str(error) == "data_profile_in_use" else "restore_refused"
        print(json.dumps({"ok": False, "code": code}), flush=True)
        return 1
    print(json.dumps({"ok": True, "result": result}), flush=True)
    return 0

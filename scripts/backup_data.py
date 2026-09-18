"""Offline backup/restore: python -m scripts.backup_data --help."""
import argparse
import json
from pathlib import Path

from server.services import backup


def main():
    parser = argparse.ArgumentParser(description="Stop Arslan first. Backups exclude the encryption secret.")
    sub = parser.add_subparsers(dest="command", required=True)
    save = sub.add_parser("create")
    save.add_argument("--data-dir", type=Path, required=True)
    save.add_argument("--db-path", type=Path)
    save.add_argument("--spawns-dir", type=Path)
    save.add_argument("--output", type=Path, required=True)
    load = sub.add_parser("restore", description=(
        "Stop Arslan first; this command does not stop it for you. Restore only into a NEW directory. "
        "Supply the stopped current DB to reconcile its independent deletion record, or import the latest "
        "export on a new machine. Without later records, restored memories remain quarantined."))
    load.add_argument("--archive", type=Path, required=True)
    load.add_argument("--new-data-dir", type=Path, required=True)
    load.add_argument("--current-db-path", type=Path,
                      help="Stopped installation DB: automatically check its independent deletion ledger too")
    load.add_argument("--deletion-manifest", type=Path,
                      help="Latest separately exported deletion record, including on a new machine")
    args = parser.parse_args()
    if args.command == "create":
        result = backup.create(args.data_dir, args.output, db_path=args.db_path, spawns_dir=args.spawns_dir)
    else:
        payload = None
        if args.deletion_manifest is not None:
            from server.services.recovery_cli import read_manifest
            payload = read_manifest(args.deletion_manifest)
        result = backup.restore(args.archive, args.new_data_dir,
                                deletion_manifest=payload, current_db_path=args.current_db_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

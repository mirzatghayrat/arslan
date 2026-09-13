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
    load = sub.add_parser("restore")
    load.add_argument("--archive", type=Path, required=True)
    load.add_argument("--new-data-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "create":
        result = backup.create(args.data_dir, args.output, db_path=args.db_path, spawns_dir=args.spawns_dir)
    else:
        result = backup.restore(args.archive, args.new_data_dir)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

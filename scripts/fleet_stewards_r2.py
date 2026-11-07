"""Local operator CLI: durable logical stewards and advisory-only rotation.

Never launches AI workers, changes a repository, installs anything, or merges PRs.

Examples:
  python scripts/fleet_stewards_r2.py ingest --input ./fleet-public.json
  python scripts/fleet_stewards_r2.py snapshot --output ./stewards-public.json
  python scripts/fleet_stewards_r2.py rotation --request-id morning-001 --count 3
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from app.services.fleet_stewards import (MAX_INPUT_BYTES, StewardRegistry, StewardHeld)


def output_json(value, path=None):
    raw = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if path is None:
        print(raw, end="")
        return
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".stewards-r2-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(raw)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agentora advisory fleet steward registry")
    parser.add_argument("--db", type=Path,
                        default=Path("~/.agentora/fleet-stewards.sqlite3"))
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="Ingest locally exported public observation JSON")
    ingest.add_argument("--input", type=Path, required=True)
    snapshot = sub.add_parser("snapshot", help="Export only presently visible public stewards")
    snapshot.add_argument("--output", type=Path)
    rotation = sub.add_parser("rotation", help="Persist fair planning turn, no worker dispatch")
    rotation.add_argument("--request-id", required=True)
    rotation.add_argument("--count", type=int, default=3)
    args = parser.parse_args(argv)
    registry = StewardRegistry(args.db)
    try:
        if args.command == "ingest":
            path = args.input.expanduser()
            if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= MAX_INPUT_BYTES:
                raise StewardHeld("INPUT_FILE_UNSAFE")
            output_json(registry.ingest(path.read_bytes()))
        elif args.command == "snapshot":
            output_json(registry.snapshot(), args.output)
        else:
            output_json(registry.plan_rotation(args.request_id, args.count))
        return 0
    except (StewardHeld, OSError) as exc:
        print("HELD: " + str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

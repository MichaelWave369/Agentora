"""Explicit export of a redacted RepoNerve snapshot for PhiMadaPrime import.

Usage: python scripts/export_phireponerve_public.py --output ~/fleet-public.json
Run against a *local* RepoNerve scan. The output may be reviewed for public
publication; it is not automatically uploaded or sent anywhere.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from app.integrations.phireponerve_client import collect_public_observations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = collect_public_observations()
    target = args.output.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".phireponerve-public-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(result, out, ensure_ascii=False, indent=2)
            out.write("\n")
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    print(f"Exported {result['public_repo_count']} public-only observations to {target}")
    print("Review the file before importing or publishing; no job was dispatched.")


if __name__ == "__main__":
    main()

"""Review a selected PhiBuddy JSONL event; optionally send once to Agentora."""
import argparse
import http.client
import json
import os
from pathlib import Path
import re
import sys

from app.services.phibuddy_bridge import MAX_EXPORT, MAX_PACKET, canonical, decode, select, validate


def send(packet, key):
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise ValueError("key required")
    expected = validate(packet)
    conn = http.client.HTTPConnection("127.0.0.1", 8088, timeout=15)
    try:
        conn.request("POST", "/api/phibuddy/advisory/preview", body=canonical(packet),
                     headers={"Content-Type": "application/json",
                              "x-phibuddy-bridge-key": key})
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError("receiver refused")
        raw = response.read(MAX_PACKET + 1)
        if len(raw) > MAX_PACKET or canonical(decode(raw)) != canonical(expected):
            raise ValueError("receipt mismatch")
        return expected
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export")
    parser.add_argument("--sequence", required=True, type=int)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--confirm-shared-text", action="store_true")
    args = parser.parse_args(argv)
    if args.send != args.confirm_shared_text:
        parser.error("send requires explicit confirmation of the selected text")
    try:
        with Path(args.export).open("rb") as handle:
            packet = select(handle.read(MAX_EXPORT + 1), args.sequence)
        if args.send:
            result = send(packet, os.environ.get("AGENTORA_PHIBUDDY_BRIDGE_KEY", ""))
        else:
            result = {"state": "LOCAL_PREVIEW_ONLY", "packet": packet}
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (OSError, ValueError, http.client.HTTPException, RecursionError):
        print("Bridge refused or unavailable; no confirmed receipt.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

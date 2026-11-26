"""Preview and explicitly approve a digest-bound PhiBuddy review."""
import argparse
import hmac
import http.client
import json
import os
from pathlib import Path
import re
import sys

from app.services.phibuddy_bridge import MAX_EXPORT, canonical, decode, select
from app.services.phibuddy_review import MAX_RECEIPT, make_request, validate_receipt


def send(request, key, approved):
    if (not re.fullmatch(r"[0-9a-f]{64}", key)
            or not re.fullmatch(r"[0-9a-f]{64}", approved)
            or not hmac.compare_digest(approved, request["consent_sha256"])):
        raise ValueError("approval mismatch or key absent")
    conn = http.client.HTTPConnection("127.0.0.1", 8088, timeout=135)
    try:
        conn.request("POST", "/api/phibuddy/advisory/review", body=canonical(request),
                     headers={"Content-Type": "application/json",
                              "x-phibuddy-bridge-key": key})
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError("receiver refused")
        raw = response.read(MAX_RECEIPT + 1)
        if len(raw) > MAX_RECEIPT:
            raise ValueError("receipt size")
        return validate_receipt(request, decode(raw))
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export")
    parser.add_argument("--sequence", required=True, type=int)
    parser.add_argument("--model", required=True)
    parser.add_argument("--approve-digest")
    parser.add_argument("--confirm-offline", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.approve_digest) != args.confirm_offline:
        parser.error("approval requires independent external network blocking and --confirm-offline")
    try:
        with Path(args.export).open("rb") as handle:
            request = make_request(select(handle.read(MAX_EXPORT + 1), args.sequence), args.model)
        if args.approve_digest:
            result = send(request, os.environ.get("AGENTORA_PHIBUDDY_BRIDGE_KEY", ""), args.approve_digest)
        else:
            result = {"state": "LOCAL_PREVIEW_ONLY", "request": request}
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (OSError, ValueError, http.client.HTTPException, RecursionError):
        print("Review refused or unavailable; no confirmed receipt.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

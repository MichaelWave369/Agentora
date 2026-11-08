"""Explicit local PHircQ signed-bundle importer and advisory inbox viewer.

Run with PYTHONPATH=server python -m app.services.agent_exchange_bridge_cli ...
No remote listener, browser API, agent dispatch or GitHub write action.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat

from app.services.agent_exchange import ExchangeHeld, ID_RE
from app.services.agent_exchange_durable import DurableReviewInbox
from app.services.agent_exchange_signed_bridge import (
    contacts_from_bindings, ingest_signed_bundle, parse_trust_policy,
)


def _reject_duplicate_keys(items: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in items:
        if key in result:
            raise ExchangeHeld("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def read_json_file(path: str, *, limit: int, protected: bool) -> object:
    """Limit bytes before parsing and refuse symlinks/nonfiles.

    Protected operator trust policy must be owner-readable only on POSIX.
    Untrusted bundle bytes are never interpreted as configuration.
    """
    file = Path(path).expanduser()
    if file.is_symlink():
        raise ExchangeHeld("FILE_SYMLINK_FORBIDDEN")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(file, flags)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ExchangeHeld("FILE_INVALID")
        if protected and os.name == "posix":
            if info.st_mode & 0o077 or info.st_uid != os.getuid():
                raise ExchangeHeld("TRUST_POLICY_PERMISSIONS")
        raw = handle.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ExchangeHeld("FILE_TOO_LARGE_OR_EMPTY")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ExchangeHeld("FILE_JSON_INVALID") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local, signed, review-only PHircQ -> Agentora handoff")
    parser.add_argument("action", choices=["import", "pending", "seen"])
    parser.add_argument("--trust", required=True, help="Locally protected operator-owned JSON pin policy")
    parser.add_argument("--db", required=True, help="Private SQLite inbox path")
    parser.add_argument("--bundle", help="Untrusted signed frame bundle (import only)")
    parser.add_argument("--recipient", help="Exact agent ID (pending / seen)")
    parser.add_argument("--message-id", help="Exact message ID (seen only)")
    args = parser.parse_args(argv)

    if (args.action == "import" and (not args.bundle or args.recipient or args.message_id)
            or args.action == "pending" and (not args.recipient or args.bundle or args.message_id)
            or args.action == "seen" and (not args.recipient or not args.message_id or args.bundle)):
        parser.error("command-specific arguments are missing or unexpected")

    bindings = parse_trust_policy(read_json_file(args.trust, limit=65536, protected=True))
    inbox = DurableReviewInbox(args.db, contacts=contacts_from_bindings(bindings))
    try:
        if args.action == "import":
            bundle = read_json_file(args.bundle, limit=16384, protected=False)
            state = ingest_signed_bundle(bundle, bindings=bindings, inbox=inbox)
            print(json.dumps({
                "state": state, "dispatch_authorized": False,
                "merge_authorized": False, "outcome_accepted": False
            }))
        elif args.action == "pending":
            if ID_RE.fullmatch(args.recipient) is None:
                raise ExchangeHeld("RECIPIENT_INVALID")
            print(json.dumps({
                "recipient": args.recipient, "messages": inbox.pending(args.recipient),
                "dispatch_authorized": False, "merge_authorized": False
            }))
        else:
            state = inbox.mark_seen(args.message_id, recipient=args.recipient)
            print(json.dumps({
                "state": state, "dispatch_authorized": False,
                "merge_authorized": False
            }))
    except ExchangeHeld as exc:
        parser.exit(2, f"Agent exchange held: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

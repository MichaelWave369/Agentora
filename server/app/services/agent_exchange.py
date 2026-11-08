"""Review-only Commonline agent exchange pilot.

This module is not a network listener, execution queue, authority grant, or
production federation. Upstream transport must authenticate the sender.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any, Mapping

SCHEMA = "commonline.agent-exchange.v1"
KINDS = frozenset({
    "offer_work", "accept_work", "decline_work", "request_context",
    "propose_outcome", "report_blocker", "receipt",
})
REQUIRED = frozenset({
    "schema", "messageId", "threadId", "sender", "recipient",
    "kind", "issuedAt", "expiresAt", "summary", "authority",
})
OPTIONAL = frozenset({"contextRef", "sourceSha"})
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA_RE = re.compile(r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")


class ExchangeHeld(ValueError):
    """Message was rejected before reaching the review inbox."""


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ExchangeHeld("TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExchangeHeld("TIME_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ExchangeHeld("TIME_INVALID")
    if parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") != value:
        raise ExchangeHeld("TIME_INVALID")
    return parsed


@dataclass(frozen=True)
class ExchangeEnvelope:
    message_id: str
    thread_id: str
    sender: str
    recipient: str
    kind: str
    issued_at: datetime
    expires_at: datetime
    summary: str
    context_ref: str | None
    source_sha: str | None
    authority: str = "advisory-only"


def parse_exchange(raw: Any, now: datetime | None = None) -> ExchangeEnvelope:
    if not isinstance(raw, dict):
        raise ExchangeHeld("ENVELOPE_INVALID")
    try:
        encoded = json.dumps(raw, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ExchangeHeld("ENVELOPE_INVALID") from exc
    if len(encoded.encode("utf-8")) > 8192:
        raise ExchangeHeld("ENVELOPE_TOO_LARGE")
    if not REQUIRED <= raw.keys() or raw.keys() - (REQUIRED | OPTIONAL):
        raise ExchangeHeld("FIELDS_INVALID")
    if raw["schema"] != SCHEMA or not isinstance(raw["kind"], str) or raw["kind"] not in KINDS:
        raise ExchangeHeld("SCHEMA_OR_KIND_INVALID")
    if raw["authority"] != "advisory-only":
        raise ExchangeHeld("AUTHORITY_FORBIDDEN")
    for field in ("messageId", "threadId", "sender", "recipient"):
        if not isinstance(raw[field], str) or not ID_RE.fullmatch(raw[field]):
            raise ExchangeHeld("IDENTITY_INVALID")
    if raw["sender"] == raw["recipient"]:
        raise ExchangeHeld("SELF_DELIVERY_FORBIDDEN")
    summary = raw["summary"]
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 2048:
        raise ExchangeHeld("SUMMARY_INVALID")
    context_ref = raw.get("contextRef")
    if context_ref is not None and (
        not isinstance(context_ref, str) or not context_ref.strip() or len(context_ref) > 512
    ):
        raise ExchangeHeld("CONTEXT_REF_INVALID")
    source_sha = raw.get("sourceSha")
    if source_sha is not None and (
        not isinstance(source_sha, str) or not SHA_RE.fullmatch(source_sha)
    ):
        raise ExchangeHeld("SOURCE_SHA_INVALID")
    issued, expires = _time(raw["issuedAt"]), _time(raw["expiresAt"])
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ExchangeHeld("CLOCK_INVALID")
    if (issued > instant + timedelta(minutes=5)
            or expires <= instant
            or expires <= issued
            or expires - issued > timedelta(days=1)):
        raise ExchangeHeld("TIME_WINDOW_INVALID")
    return ExchangeEnvelope(
        message_id=raw["messageId"], thread_id=raw["threadId"],
        sender=raw["sender"], recipient=raw["recipient"], kind=raw["kind"],
        issued_at=issued, expires_at=expires, summary=summary,
        context_ref=context_ref, source_sha=source_sha,
    )


class ReviewOnlyInbox:
    """Bounded, local-only pilot inbox. NO background dispatch, GitHub writes or execution.

    Contacts represent an operator-supplied allowlist, not permission inferred
    from the message or a remote service. These records are not durable;
    persist receipts and integrate a trusted identity provider before production.
    """

    def __init__(self, contacts: Mapping[str, set[str]], max_messages: int = 256) -> None:
        if type(max_messages) is not int or not 1 <= max_messages <= 10_000:
            raise ValueError("CAPACITY_INVALID")
        if not contacts or any(
            not isinstance(actor, str) or not ID_RE.fullmatch(actor)
            or not isinstance(peers, set)
            or any(not isinstance(peer, str) or not ID_RE.fullmatch(peer) for peer in peers)
            for actor, peers in contacts.items()
        ):
            raise ValueError("CONTACTS_INVALID")
        self._contacts = {actor: frozenset(peers) for actor, peers in contacts.items()}
        self._seen: set[str] = set()
        self._inbox: dict[str, list[ExchangeEnvelope]] = {
            actor: [] for actor in self._contacts
        }
        self._max_messages = max_messages

    def receive(
        self, raw: Any, *, authenticated_sender: str, now: datetime | None = None
    ) -> str:
        message = parse_exchange(raw, now=now)
        if message.sender != authenticated_sender:
            raise ExchangeHeld("SENDER_NOT_AUTHENTICATED")
        if (message.sender not in self._contacts
                or message.recipient not in self._contacts
                or message.recipient not in self._contacts[message.sender]):
            raise ExchangeHeld("CONTACT_NOT_ALLOWED")
        if message.message_id in self._seen:
            return "REPLAY_IGNORED"
        if len(self._seen) >= self._max_messages:
            raise ExchangeHeld("INBOX_CAPACITY_HELD")
        self._seen.add(message.message_id)
        self._inbox[message.recipient].append(message)
        return "REVIEW_PENDING"

    def pending(self, recipient: str) -> tuple[ExchangeEnvelope, ...]:
        if recipient not in self._inbox:
            raise ExchangeHeld("UNKNOWN_RECIPIENT")
        return tuple(self._inbox[recipient])

    @property
    def dispatch_authorized(self) -> bool:
        return False

    @property
    def merge_authorized(self) -> bool:
        return False

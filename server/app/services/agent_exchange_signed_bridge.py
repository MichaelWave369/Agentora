"""Offline signed PHircQ -> Agentora advisory handoff verifier.

Each envelope is verified against a locally pinned P-256 peer fingerprint and
agent mapping, then enters the existing durable review-only inbox. No server,
network listener, remote trust-on-first-use or execution path is added.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
import re
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from app.services.agent_exchange import ExchangeHeld, ID_RE, parse_exchange
from app.services.agent_exchange_durable import DurableReviewInbox

BUNDLE_SCHEMA = "phircq.agent-exchange.signed-bundle.v1"
POLICY_SCHEMA = "agentora.phircq.trust.v1"
FINGERPRINT = re.compile(r"^[a-f0-9]{64}$")
B64_URL = re.compile(r"^[A-Za-z0-9_-]{43}$")
B64_STANDARD = re.compile(r"^[A-Za-z0-9+/]{86}==$")
FRAME_FIELDS = frozenset({"id", "peerId", "sentAt", "payload", "publicKey", "signature"})
PUBLIC_KEY_FIELDS = frozenset({"kty", "crv", "x", "y", "ext", "key_ops"})
MAX_BUNDLE_BYTES = 16384


@dataclass(frozen=True)
class PeerBinding:
    peer_id: str
    fingerprint: str
    sender_agent: str
    recipient_agent: str


def _json_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ExchangeHeld("BUNDLE_JSON_INVALID") from exc


def _url_number(value: Any) -> int:
    if type(value) is not str or B64_URL.fullmatch(value) is None:
        raise ExchangeHeld("PUBLIC_KEY_INVALID")
    try:
        raw = base64.urlsafe_b64decode(value + "=")
    except (ValueError, base64.binascii.Error) as exc:
        raise ExchangeHeld("PUBLIC_KEY_INVALID") from exc
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode().rstrip("=") != value:
        raise ExchangeHeld("PUBLIC_KEY_INVALID")
    return int.from_bytes(raw, "big")


def _frame_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ExchangeHeld("FRAME_TIME_INVALID")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExchangeHeld("FRAME_TIME_INVALID") from exc
    if (instant.tzinfo is None or instant.utcoffset() != timedelta(0)
            or instant.isoformat(timespec="milliseconds").replace("+00:00", "Z") != value):
        raise ExchangeHeld("FRAME_TIME_INVALID")
    return instant


def parse_trust_policy(raw: Any) -> dict[str, PeerBinding]:
    """Parse separately protected operator-controlled configuration, never bundle metadata."""
    if type(raw) is not dict or set(raw) != {"schema", "peers"}:
        raise ExchangeHeld("TRUST_POLICY_INVALID")
    if raw["schema"] != POLICY_SCHEMA or type(raw["peers"]) is not list:
        raise ExchangeHeld("TRUST_POLICY_INVALID")
    if not 1 <= len(raw["peers"]) <= 128:
        raise ExchangeHeld("TRUST_POLICY_INVALID")
    bindings: dict[str, PeerBinding] = {}
    for peer in raw["peers"]:
        if type(peer) is not dict or set(peer) != {
            "peerId", "fingerprint", "senderAgent", "recipientAgent"
        }:
            raise ExchangeHeld("TRUST_PEER_INVALID")
        for field in ("peerId", "senderAgent", "recipientAgent"):
            if type(peer[field]) is not str or ID_RE.fullmatch(peer[field]) is None:
                raise ExchangeHeld("TRUST_PEER_INVALID")
        if (peer["senderAgent"] == peer["recipientAgent"]
                or type(peer["fingerprint"]) is not str
                or FINGERPRINT.fullmatch(peer["fingerprint"]) is None
                or peer["peerId"] in bindings):
            raise ExchangeHeld("TRUST_PEER_INVALID")
        bindings[peer["peerId"]] = PeerBinding(
            peer["peerId"], peer["fingerprint"],
            peer["senderAgent"], peer["recipientAgent"]
        )
    return bindings


def contacts_from_bindings(bindings: Mapping[str, PeerBinding]) -> dict[str, set[str]]:
    """Outbound contact rights are NOT derived here, only this exact incoming route."""
    contacts: dict[str, set[str]] = {}
    for binding in bindings.values():
        contacts.setdefault(binding.sender_agent, set()).add(binding.recipient_agent)
        contacts.setdefault(binding.recipient_agent, set())
    return contacts


def verify_signed_bundle(
    bundle: Any, *, bindings: Mapping[str, PeerBinding],
    now: datetime | None = None,
) -> tuple[dict, PeerBinding]:
    """Verify WebCrypto's P-256 raw r||s signature, peer pin and agent mapping.

    JSON payload field insertion order is intentionally preserved: PHircQ's
    signer signs JSON.stringify({id, peerId, sentAt, payload}) exactly.
    """
    if type(bundle) is not dict or set(bundle) != {"schema", "frame"}:
        raise ExchangeHeld("BUNDLE_INVALID")
    if len(_json_bytes(bundle)) > MAX_BUNDLE_BYTES:
        raise ExchangeHeld("BUNDLE_TOO_LARGE")
    if bundle["schema"] != BUNDLE_SCHEMA or type(bundle["frame"]) is not dict:
        raise ExchangeHeld("BUNDLE_INVALID")
    frame = bundle["frame"]
    if set(frame) != FRAME_FIELDS or type(frame["id"]) is not str or \
            ID_RE.fullmatch(frame["id"]) is None:
        raise ExchangeHeld("FRAME_INVALID")
    peer_id = frame["peerId"]
    if type(peer_id) is not str or ID_RE.fullmatch(peer_id) is None:
        raise ExchangeHeld("FRAME_INVALID")
    binding = bindings.get(peer_id)
    if binding is None:
        raise ExchangeHeld("PEER_NOT_PINNED")
    payload = frame["payload"]
    if (type(payload) is not dict or set(payload) != {"kind", "message"}
            or payload["kind"] != "agent.exchange"):
        raise ExchangeHeld("PAYLOAD_INVALID")
    msg = payload["message"]
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ExchangeHeld("CLOCK_INVALID")
    parsed = parse_exchange(msg, now=instant)
    if parsed.sender != binding.sender_agent or parsed.recipient != binding.recipient_agent:
        raise ExchangeHeld("AGENT_PEER_BINDING_MISMATCH")
    sent_at = _frame_time(frame["sentAt"])
    if (sent_at > instant + timedelta(minutes=5)
            or sent_at < parsed.issued_at - timedelta(minutes=5)
            or sent_at > parsed.expires_at):
        raise ExchangeHeld("FRAME_TIME_OUT_OF_SCOPE")

    jwk = frame["publicKey"]
    if (type(jwk) is not dict or not {"kty", "crv", "x", "y"} <= set(jwk)
            or set(jwk) - PUBLIC_KEY_FIELDS
            or jwk["kty"] != "EC" or jwk["crv"] != "P-256"
            or ("ext" in jwk and jwk["ext"] is not True)
            or ("key_ops" in jwk and jwk["key_ops"] != ["verify"])):
        raise ExchangeHeld("PUBLIC_KEY_INVALID")
    x, y = _url_number(jwk["x"]), _url_number(jwk["y"])
    fp_bytes = _json_bytes({"crv": "P-256", "kty": "EC", "x": jwk["x"], "y": jwk["y"]})
    fingerprint = hashlib.sha256(fp_bytes).hexdigest()
    if fingerprint != binding.fingerprint:
        raise ExchangeHeld("PEER_KEY_MISMATCH")

    sig_text = frame["signature"]
    if type(sig_text) is not str or B64_STANDARD.fullmatch(sig_text) is None:
        raise ExchangeHeld("SIGNATURE_INVALID")
    try:
        raw_sig = base64.b64decode(sig_text, validate=True)
        key = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
        r, s = int.from_bytes(raw_sig[:32], "big"), int.from_bytes(raw_sig[32:], "big")
        der_sig = encode_dss_signature(r, s)
        signed_body = _json_bytes({
            "id": frame["id"], "peerId": peer_id,
            "sentAt": frame["sentAt"], "payload": payload
        })
        key.verify(der_sig, signed_body, ec.ECDSA(hashes.SHA256()))
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise ExchangeHeld("SIGNATURE_INVALID") from exc
    # Verified signature binds the precise message to an operator-pinned peer.
    return msg, binding


def ingest_signed_bundle(
    bundle: Any, *, bindings: Mapping[str, PeerBinding],
    inbox: DurableReviewInbox, now: datetime | None = None,
) -> str:
    """Attested peer-to-agent transport data; never authorizes execution."""
    msg, binding = verify_signed_bundle(bundle, bindings=bindings, now=now)
    return inbox.ingest(msg, authenticated_sender=binding.sender_agent, now=now)

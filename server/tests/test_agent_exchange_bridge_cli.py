"""CLI end-to-end: fresh locally signed frame -> trust pin -> durable inbox."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from app.services.agent_exchange_bridge_cli import main, read_json_file
from app.services.agent_exchange import ExchangeHeld
from app.services.agent_exchange_signed_bridge import BUNDLE_SCHEMA, POLICY_SCHEMA

UTC = timezone.utc


def timestamp(when):
    return when.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def url_coord(n):
    return base64.urlsafe_b64encode(n.to_bytes(32, "big")).decode("ascii").rstrip("=")


def fresh_signed_bundle():
    private = ec.generate_private_key(ec.SECP256R1())
    pub = private.public_key().public_numbers()
    jwk = {
        "key_ops": ["verify"], "ext": True, "kty": "EC",
        "x": url_coord(pub.x), "y": url_coord(pub.y), "crv": "P-256",
    }
    fp_body = json.dumps({
        "crv": "P-256", "kty": "EC", "x": jwk["x"], "y": jwk["y"]
    }, separators=(",", ":")).encode()
    fingerprint = hashlib.sha256(fp_body).hexdigest()
    now = datetime.now(UTC)
    envelope = {
        "schema": "commonline.agent-exchange.v1",
        "messageId": "btm-live-501", "threadId": "tracking-live-501",
        "sender": "agent:btm", "recipient": "agent:overstrings",
        "kind": "offer_work",
        "issuedAt": timestamp(now - timedelta(seconds=30)),
        "expiresAt": timestamp(now + timedelta(minutes=5)),
        "summary": "Review an OverStrings regression without running tools.",
        "authority": "advisory-only",
    }
    body = {
        "id": "frame-501", "peerId": "peer-btm",
        "sentAt": timestamp(now),
        "payload": {"kind": "agent.exchange", "message": envelope}
    }
    encoded = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    der = private.sign(encoded, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = base64.b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).decode()
    return (
        {"schema": BUNDLE_SCHEMA, "frame": {**body, "publicKey": jwk, "signature": signature}},
        {"schema": POLICY_SCHEMA, "peers": [{
            "peerId": "peer-btm", "fingerprint": fingerprint,
            "senderAgent": "agent:btm", "recipientAgent": "agent:overstrings",
        }]}
    )


class SignedBridgeCliTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        bundle, policy = fresh_signed_bundle()
        self.bundle = root / "bundle.json"
        self.trust = root / "trust.json"
        self.db = root / "inbox.sqlite3"
        self.bundle.write_text(json.dumps(bundle), "utf-8")
        self.trust.write_text(json.dumps(policy), "utf-8")
        self.trust.chmod(0o600)

    def run_command(self, *argv):
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(list(argv))
        self.assertEqual(result, 0)
        return json.loads(output.getvalue())

    def shared(self):
        return ("--trust", str(self.trust), "--db", str(self.db))

    def test_import_view_and_mark_seen_are_replay_safe(self):
        first = self.run_command("import", *self.shared(), "--bundle", str(self.bundle))
        self.assertEqual(first["state"], "REVIEW_PENDING")
        self.assertFalse(first["dispatch_authorized"])
        second = self.run_command("import", *self.shared(), "--bundle", str(self.bundle))
        self.assertEqual(second["state"], "REPLAY_IGNORED")
        listed = self.run_command("pending", *self.shared(), "--recipient", "agent:overstrings")
        self.assertEqual([m["message_id"] for m in listed["messages"]], ["btm-live-501"])
        self.assertFalse(listed["messages"][0]["merge_authorized"])
        self.assertEqual(self.run_command(
            "seen", *self.shared(), "--recipient", "agent:overstrings",
            "--message-id", "btm-live-501"
        )["state"], "SEEN_ONLY")
        self.assertEqual(self.run_command(
            "pending", *self.shared(), "--recipient", "agent:overstrings"
        )["messages"], [])

    def test_untrusted_public_key_rejected_no_inbox_write(self):
        forged = json.loads(self.bundle.read_text())
        forged["frame"]["publicKey"]["x"] = "A" * 43
        self.bundle.write_text(json.dumps(forged))
        with self.assertRaises(ExchangeHeld):
            self.run_command("import", *self.shared(), "--bundle", str(self.bundle))

    def test_world_readable_trust_file_rejected(self):
        if os.name != "posix":
            self.skipTest("POSIX-only policy mode")
        self.trust.chmod(0o644)
        with self.assertRaisesRegex(ExchangeHeld, "TRUST_POLICY_PERMISSIONS"):
            read_json_file(str(self.trust), limit=65536, protected=True)

    def test_duplicate_json_keys_in_trust_policy_are_not_silently_accepted(self):
        self.trust.write_text('{"schema":"a","schema":"b","peers":[]}')
        with self.assertRaises(ExchangeHeld):
            read_json_file(str(self.trust), limit=65536, protected=True)


if __name__ == "__main__":
    unittest.main()

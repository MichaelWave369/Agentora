"""Real localhost HTTP transport tests for signed, review-only exchange."""
from datetime import datetime, timedelta, timezone
import base64
import hashlib
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from app.services.agent_exchange_durable import DurableReviewInbox
from app.services.agent_exchange_signed_bridge import (
    BUNDLE_SCHEMA, POLICY_SCHEMA, contacts_from_bindings, parse_trust_policy,
)
from app.services.agent_exchange_local_http import (
    create_bridge_server, read_token_file
)

TOKEN = "a" * 64
ORIGIN = "http://localhost:5173"


def utc_stamp(value):
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def coord(number):
    return base64.urlsafe_b64encode(number.to_bytes(32, "big")).decode().rstrip("=")


def new_signed_bundle():
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_numbers()
    jwk = {"key_ops": ["verify"], "ext": True, "kty": "EC",
           "x": coord(pub.x), "y": coord(pub.y), "crv": "P-256"}
    fingerprint = hashlib.sha256(json.dumps({
        "crv": "P-256", "kty": "EC", "x": jwk["x"], "y": jwk["y"]
    }, separators=(",", ":")).encode()).hexdigest()
    now = datetime.now(timezone.utc)
    msg = {
        "schema": "commonline.agent-exchange.v1",
        "messageId": "btm-r4-msg-001",
        "threadId": "overstrings-r4",
        "sender": "agent:btm", "recipient": "agent:overstrings",
        "kind": "offer_work", "issuedAt": utc_stamp(now - timedelta(seconds=5)),
        "expiresAt": utc_stamp(now + timedelta(minutes=5)),
        "summary": "Investigate controller hand tracking regression.",
        "authority": "advisory-only",
    }
    signed = {"id": "frame-r4-001", "peerId": "peer-btm", "sentAt": utc_stamp(now),
              "payload": {"kind": "agent.exchange", "message": msg}}
    der = key.sign(json.dumps(signed, separators=(",", ":")).encode(),
                   ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = base64.b64encode(r.to_bytes(32, "big") +
                                 s.to_bytes(32, "big")).decode()
    policy = {"schema": POLICY_SCHEMA, "peers": [{
        "peerId": "peer-btm", "fingerprint": fingerprint,
        "senderAgent": "agent:btm", "recipientAgent": "agent:overstrings"
    }]}
    return {"schema": BUNDLE_SCHEMA,
            "frame": {**signed, "publicKey": jwk, "signature": signature}}, policy


class LocalBridgeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "messages.sqlite3"
        self.bundle, policy = new_signed_bundle()
        self.bindings = parse_trust_policy(policy)
        self.inbox = DurableReviewInbox(self.db, contacts=contacts_from_bindings(self.bindings))
        self.server = create_bridge_server(
            inbox=self.inbox, bindings=self.bindings, token=TOKEN,
            allowed_origins=(ORIGIN,))
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def request(self, method, path, body=None, *, token=TOKEN, origin=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=3)
        opts = {"Authorization": f"Bearer {token}"}
        if origin is not None:
            opts["Origin"] = origin
        if body is not None:
            opts["Content-Type"] = "application/json"
        if headers:
            opts.update(headers)
        conn.request(method, path, body=body, headers=opts)
        resp = conn.getresponse()
        data = resp.read()
        result = (resp.status, dict(resp.getheaders()),
                  json.loads(data) if data else None)
        conn.close()
        return result

    def bundle_bytes(self, value=None):
        return json.dumps(value or self.bundle, separators=(",", ":")).encode()

    def test_signed_delivery_persists_and_idempotently_replays(self):
        status, _, payload = self.request("POST", "/v1/ingest",
                                          self.bundle_bytes())
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "REVIEW_PENDING")
        self.assertFalse(payload["dispatch_authorized"])
        status, _, replay = self.request("POST", "/v1/ingest",
                                         self.bundle_bytes())
        self.assertEqual(replay["state"], "REPLAY_IGNORED")
        status, _, listed = self.request("GET",
                                         "/v1/pending?recipient=agent%3Aoverstrings")
        self.assertEqual(status, 200)
        self.assertEqual([m["message_id"] for m in listed["messages"]],
                         ["btm-r4-msg-001"])
        reopened = DurableReviewInbox(self.db, contacts=contacts_from_bindings(self.bindings))
        self.assertEqual(len(reopened.pending("agent:overstrings")), 1)
        status, _, health = self.request("GET", "/v1/status")
        self.assertTrue(health["local_only"])
        self.assertFalse(health["merge_authorized"])

    def test_no_token_wrong_host_bad_origin_or_invalid_method(self):
        self.assertEqual(self.request("GET", "/v1/status", token="x" * 64)[0], 401)
        self.assertEqual(self.request("GET", "/v1/status", origin="https://evil.example")[0], 403)
        self.assertEqual(self.request("GET", "/v1/status", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/v1/unknown")[0], 404)
        self.assertEqual(self.inbox.pending("agent:overstrings"), [])

    def test_tampered_signature_and_forged_authority_are_rejected(self):
        altered = json.loads(json.dumps(self.bundle))
        altered["frame"]["payload"]["message"]["summary"] = "execute code"
        self.assertEqual(self.request("POST", "/v1/ingest", self.bundle_bytes(altered))[0], 422)
        altered = json.loads(json.dumps(self.bundle))
        altered["frame"]["payload"]["message"]["authority"] = "execute"
        self.assertEqual(self.request("POST", "/v1/ingest", self.bundle_bytes(altered))[0], 422)
        self.assertEqual(self.inbox.pending("agent:overstrings"), [])

    def test_bounded_body_and_strict_json(self):
        self.assertEqual(self.request("POST", "/v1/ingest", b"x" * 16385)[0], 413)
        duplicate = b'{"schema":"a","schema":"b"}'
        self.assertEqual(self.request("POST", "/v1/ingest", duplicate)[0], 422)
        self.assertEqual(self.request("POST", "/v1/ingest", b"{}",
                                      headers={"Content-Type": "text/plain"})[0], 415)

    def test_browser_origin_is_explicitly_preflighted(self):
        options = {
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        }
        status, hdrs, _ = self.request("OPTIONS", "/v1/ingest", headers=options)
        self.assertEqual(status, 204)
        self.assertEqual(hdrs["Access-Control-Allow-Origin"], ORIGIN)
        options["Origin"] = "https://evil.example"
        self.assertEqual(self.request("OPTIONS", "/v1/ingest", headers=options)[0], 403)

    def test_token_file_format_and_permissions(self):
        path = self.db.parent / "token.txt"
        path.write_text(TOKEN, "ascii")
        path.chmod(0o600)
        self.assertEqual(read_token_file(str(path)), TOKEN)
        path.write_text("short")
        with self.assertRaisesRegex(ValueError, "TOKEN_FORMAT_INVALID"):
            read_token_file(str(path))


if __name__ == "__main__":
    unittest.main()

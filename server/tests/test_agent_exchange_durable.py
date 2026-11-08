from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from app.services.agent_exchange import ExchangeHeld, SCHEMA
from app.services.agent_exchange_durable import DurableReviewInbox

NOW = datetime(2026, 11, 7, 20, 0, tzinfo=timezone.utc)
OFFER = {
    "schema": SCHEMA, "messageId": "btm-msg-101", "threadId": "quest-tracking-101",
    "sender": "agent:btm", "recipient": "agent:overstrings", "kind": "offer_work",
    "issuedAt": "2026-11-07T19:59:00.000Z",
    "expiresAt": "2026-11-07T20:59:00.000Z",
    "summary": "Review Quest hand tracking issue.",
    "authority": "advisory-only",
}
CONTACTS = {"agent:btm": {"agent:overstrings"},
            "agent:overstrings": {"agent:btm"}}


class DurableInboxTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "inbox.sqlite3"

    def store(self, limit=100):
        return DurableReviewInbox(self.db, contacts=CONTACTS, max_messages=limit)

    def test_restart_and_replay(self):
        self.assertEqual(self.store().ingest(OFFER, authenticated_sender="agent:btm", now=NOW),
                         "REVIEW_PENDING")
        second = self.store()
        self.assertEqual(second.ingest(OFFER, authenticated_sender="agent:btm", now=NOW),
                         "REPLAY_IGNORED")
        self.assertEqual(len(second.pending("agent:overstrings")), 1)
        self.assertFalse(second.dispatch_authorized or second.merge_authorized)
        self.assertFalse(second.pending("agent:overstrings")[0]["outcome_accepted"])

    def test_collision_keeps_original(self):
        store = self.store()
        store.ingest(OFFER, authenticated_sender="agent:btm", now=NOW)
        with self.assertRaisesRegex(ExchangeHeld, "MESSAGE_ID_COLLISION"):
            store.ingest({**OFFER, "summary": "different"},
                         authenticated_sender="agent:btm", now=NOW)
        self.assertEqual(store.pending("agent:overstrings")[0]["summary"], OFFER["summary"])

    def test_seen_receipt_persists_but_does_not_accept(self):
        store = self.store()
        store.ingest(OFFER, authenticated_sender="agent:btm", now=NOW)
        with self.assertRaisesRegex(ExchangeHeld, "MESSAGE_NOT_VISIBLE"):
            store.mark_seen(OFFER["messageId"], recipient="agent:btm", now=NOW)
        self.assertEqual(store.mark_seen(OFFER["messageId"], recipient="agent:overstrings", now=NOW),
                         "SEEN_ONLY")
        restarted = self.store()
        self.assertEqual(restarted.pending("agent:overstrings"), [])
        self.assertEqual(restarted.mark_seen(OFFER["messageId"], recipient="agent:overstrings", now=NOW),
                         "ALREADY_SEEN")
        self.assertFalse(restarted.merge_authorized)

    def test_capacity_holds_and_replay_still_dedupes(self):
        store = self.store(limit=1)
        store.ingest(OFFER, authenticated_sender="agent:btm", now=NOW)
        with self.assertRaisesRegex(ExchangeHeld, "INBOX_CAPACITY_HELD"):
            store.ingest({**OFFER, "messageId": "btm-msg-102"},
                         authenticated_sender="agent:btm", now=NOW)
        self.assertEqual(store.ingest(OFFER, authenticated_sender="agent:btm", now=NOW),
                         "REPLAY_IGNORED")

    def test_contact_revocation_and_forgery(self):
        store = self.store()
        store.ingest(OFFER, authenticated_sender="agent:btm", now=NOW)
        revoked = DurableReviewInbox(self.db, contacts={
            "agent:btm": set(), "agent:overstrings": set()})
        with self.assertRaisesRegex(ExchangeHeld, "CONTACT_NOT_ALLOWED"):
            revoked.ingest(OFFER, authenticated_sender="agent:btm", now=NOW)
        with self.assertRaisesRegex(ExchangeHeld, "SENDER_NOT_AUTHENTICATED"):
            store.ingest(OFFER, authenticated_sender="agent:attacker", now=NOW)
        with self.assertRaises(ExchangeHeld):
            store.ingest({**OFFER, "authority": "execute"},
                         authenticated_sender="agent:btm", now=NOW)

    def test_symlink_database_refused(self):
        with tempfile.TemporaryDirectory() as d:
            target, link = Path(d) / "target", Path(d) / "link"
            target.write_text("original")
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(ExchangeHeld, "DB_PATH_UNSAFE"):
                DurableReviewInbox(link, contacts=CONTACTS)
            self.assertEqual(target.read_text(), "original")

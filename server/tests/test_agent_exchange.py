"""Commonline/PHircQ interoperability envelope, local Agentora review-only intake."""
from datetime import datetime, timezone
import unittest

from app.services.agent_exchange import ExchangeHeld, ReviewOnlyInbox, parse_exchange, SCHEMA

NOW = datetime(2026, 11, 7, 20, 0, tzinfo=timezone.utc)
OFFER = {
    "schema": SCHEMA,
    "messageId": "btm-msg-001",
    "threadId": "quest-tracking-001",
    "sender": "agent:btm",
    "recipient": "agent:overstrings",
    "kind": "offer_work",
    "issuedAt": "2026-11-07T19:59:00.000Z",
    "expiresAt": "2026-11-07T20:59:00.000Z",
    "summary": "Review a Quest hand tracking regression; no permission to edit.",
    "authority": "advisory-only",
}


def inbox():
    return ReviewOnlyInbox({
        "agent:btm": {"agent:overstrings"},
        "agent:overstrings": {"agent:btm"},
    })


class AgentExchangePilotTests(unittest.TestCase):
    def test_cross_project_offer_reaches_review_only_inbox(self):
        queue = inbox()
        self.assertEqual(queue.receive(OFFER, authenticated_sender="agent:btm", now=NOW),
                         "REVIEW_PENDING")
        self.assertEqual(queue.pending("agent:overstrings")[0].summary, OFFER["summary"])
        self.assertFalse(queue.dispatch_authorized)
        self.assertFalse(queue.merge_authorized)
        self.assertEqual(queue.pending("agent:btm"), ())

    def test_duplicate_is_idempotent(self):
        queue = inbox()
        queue.receive(OFFER, authenticated_sender="agent:btm", now=NOW)
        self.assertEqual(queue.receive(OFFER, authenticated_sender="agent:btm", now=NOW),
                         "REPLAY_IGNORED")
        self.assertEqual(len(queue.pending("agent:overstrings")), 1)

    def test_rejects_impersonation_and_unlisted_contact(self):
        queue = inbox()
        with self.assertRaisesRegex(ExchangeHeld, "SENDER_NOT_AUTHENTICATED"):
            queue.receive(OFFER, authenticated_sender="agent:intruder", now=NOW)
        wrong = {**OFFER, "recipient": "agent:secret"}
        with self.assertRaisesRegex(ExchangeHeld, "CONTACT_NOT_ALLOWED"):
            queue.receive(wrong, authenticated_sender="agent:btm", now=NOW)
        self.assertEqual(queue.pending("agent:overstrings"), ())

    def test_forged_execution_and_extra_fields_are_rejected(self):
        for change in (
            {"authority": "execute"},
            {"mergeAuthorized": True},
            {"kind": "run_shell"},
            {"sourceSha": "tests-passed"},
        ):
            with self.subTest(change=change), self.assertRaises(ExchangeHeld):
                parse_exchange({**OFFER, **change}, now=NOW)

    def test_stale_and_future_messages_are_rejected(self):
        for change in (
            {"expiresAt": "2026-11-07T19:59:30.000Z"},
            {"issuedAt": "2026-11-07T20:06:00.000Z"},
            {"expiresAt": "2026-11-09T20:00:00.000Z"},
        ):
            with self.subTest(change=change), self.assertRaises(ExchangeHeld):
                parse_exchange({**OFFER, **change}, now=NOW)

    def test_full_inbox_holds_without_dropping_history(self):
        queue = ReviewOnlyInbox({
            "agent:btm": {"agent:overstrings"},
            "agent:overstrings": {"agent:btm"},
        }, max_messages=1)
        queue.receive(OFFER, authenticated_sender="agent:btm", now=NOW)
        with self.assertRaisesRegex(ExchangeHeld, "INBOX_CAPACITY_HELD"):
            queue.receive({**OFFER, "messageId": "another"},
                          authenticated_sender="agent:btm", now=NOW)
        self.assertEqual(len(queue.pending("agent:overstrings")), 1)


if __name__ == "__main__":
    unittest.main()

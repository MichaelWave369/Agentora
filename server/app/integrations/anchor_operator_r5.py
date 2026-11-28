"""ANCHOR R5: opt-in local synthetic payment workflow, never a payment tool.

Importing this module has no effects. Requires a separately supplied, pinned
ANC checkout and its R4 dependency only when this harness is used.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

MAX_UNITS = 10**12
SCHEMA = """
CREATE TABLE IF NOT EXISTS budget (
    id INTEGER PRIMARY KEY CHECK(id=1), available INTEGER NOT NULL CHECK(available>=0)
);
CREATE TABLE IF NOT EXISTS proposals (
    digest TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
    payload TEXT NOT NULL, units INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','approved','denied','cancelled','simulated')),
    evidence TEXT
);
CREATE TABLE IF NOT EXISTS anc_evidence_seen (
    issuer TEXT NOT NULL, nonce TEXT NOT NULL,
    audience TEXT NOT NULL, proposal_digest TEXT NOT NULL,
    PRIMARY KEY(issuer, nonce), UNIQUE(issuer,audience,proposal_digest)
);
"""


class _TransactionalReplay:
    """R4 replay claim protocol using the workflow's existing transaction."""
    def __init__(self, db):
        self.db = db

    def claim(self, issuer, nonce, audience, digest):
        try:
            self.db.execute("INSERT INTO anc_evidence_seen VALUES (?,?,?,?)",
                            (issuer, nonce, audience, digest))
        except sqlite3.IntegrityError as exc:
            raise ValueError("replayed evidence") from exc


class SyntheticOperator:
    """Separate SQLite harness; callers are trusted local test operators.

    No runtime routes, tools, agent-callable approvals, wallets or transfers.
    The budget is one synthetic pool, not a mandate or actual funds.
    """
    def __init__(self, path: str | Path, *, initial_units=None):
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        try:
            self.db.executescript(SCHEMA)
            with self._transaction():
                found = self.db.execute("SELECT available FROM budget WHERE id=1").fetchone()
                if found is None:
                    if type(initial_units) is not int or not 0 <= initial_units <= MAX_UNITS:
                        raise ValueError("initial synthetic budget required")
                    self.db.execute("INSERT INTO budget VALUES (1,?)", (initial_units,))
                elif initial_units is not None:
                    raise ValueError("budget already initialized")
        except BaseException:
            self.db.close()
            raise

    @contextmanager
    def _transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def close(self):
        self.db.close()

    def available(self):
        return self.db.execute("SELECT available FROM budget WHERE id=1").fetchone()[0]

    def history(self):
        return [
            dict(digest=d, request_id=r, units=u, state=s, evidence=json.loads(e) if e else None,
                 authority_granted=False, real_funds=False)
            for d, r, u, s, e in self.db.execute(
                "SELECT digest,request_id,units,state,evidence FROM proposals ORDER BY rowid")
        ]

    def _row(self, digest):
        row = self.db.execute("SELECT payload,units,state FROM proposals WHERE digest=?",
                              (digest,)).fetchone()
        if row is None:
            raise ValueError("unknown proposal")
        return json.loads(row[0]), row[1], row[2]

    def propose(self, proposal, *, now):
        from anc.integrations.economic_contract import proposal_digest
        # Snapshot before validation; only ordinary JSON fixture data.
        payload = json.dumps(proposal, sort_keys=True, separators=(",", ":"), allow_nan=False)
        p = json.loads(payload)
        digest = proposal_digest(p, now=now)
        if (p["rail"], p["chain"], p["asset"]) != ("simulation", "sim:local", "sim:credit"):
            raise ValueError("only local synthetic credits are supported")
        units = int(p["amount_atomic"])
        if units > MAX_UNITS or p["payer"] == p["payee"]:
            raise ValueError("invalid synthetic amount or parties")
        with self._transaction():
            old = self.db.execute("SELECT digest FROM proposals WHERE request_id=?",
                                  (p["request_id"],)).fetchone()
            if old is not None:
                if old[0] != digest:
                    raise ValueError("request substitution")
                return digest
            self.db.execute("INSERT INTO proposals VALUES (?,?,?,?,?,NULL)",
                            (digest, p["request_id"], payload, units, "pending"))
        return digest

    def decide(self, digest, *, approve, now):
        """Explicit trusted local operator decision; never an agent tool."""
        from anc.integrations.economic_contract import proposal_digest
        if type(approve) is not bool:
            raise ValueError("explicit boolean decision required")
        with self._transaction():
            p, units, state = self._row(digest)
            if state != "pending":
                raise ValueError("proposal not pending")
            if approve:
                if proposal_digest(p, now=now) != digest:
                    raise ValueError("proposal changed")
                result = self.db.execute(
                    "UPDATE budget SET available=available-? WHERE id=1 AND available>=?",
                    (units, units))
                if result.rowcount != 1:
                    raise ValueError("insufficient synthetic budget")
            self.db.execute("UPDATE proposals SET state=? WHERE digest=?",
                            ("approved" if approve else "denied", digest))

    def cancel(self, digest):
        """Local operator releases a pending or reserved proposal, including expired ones."""
        with self._transaction():
            _, units, state = self._row(digest)
            if state not in ("pending", "approved"):
                raise ValueError("proposal not cancellable")
            if state == "approved":
                self.db.execute("UPDATE budget SET available=available+? WHERE id=1", (units,))
            self.db.execute("UPDATE proposals SET state='cancelled' WHERE digest=?", (digest,))

    def simulate(self, digest, wire, *, trust, expected_issuer, now):
        """Accept only a clean authenticated advisory after independent approval.

        Atomically claim evidence and record synthetic completion. No external
        operation is performed; failure rolls back the claim and completion,
        preserving the reservation for cancellation or a valid retry.
        """
        from anc.integrations.economic_contract import proposal_digest
        from anc.integrations.signed_evidence import verify_evidence
        with self._transaction():
            p, _, state = self._row(digest)
            if state != "approved" or proposal_digest(p, now=now) != digest:
                raise ValueError("approved unexpired proposal required")
            evidence = verify_evidence(
                wire, p, trust=trust, expected_issuer=expected_issuer,
                expected_audience="agentora-anchor-simulation",
                replay=_TransactionalReplay(self.db), now=now)
            if (evidence.posture != "safe" or evidence.recommended_action != "allow"
                    or evidence.signal_count != 0 or evidence.proposal_digest != digest):
                raise ValueError("risk evidence requires review; cancel or retry")
            receipt = dict(issuer=evidence.issuer, key_id=evidence.key_id,
                           nonce=evidence.nonce, proposal_digest=digest,
                           disposition="simulated", authority_granted=False, real_funds=False)
            self.db.execute("UPDATE proposals SET state='simulated',evidence=? WHERE digest=?",
                            (json.dumps(receipt, sort_keys=True), digest))
        return receipt

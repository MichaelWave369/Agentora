"""ΦCAPSID → Agentora R1: lease-fenced, HEAD-observed local context handoff.

Reads the existing ΦCAPSID installation and the current Agentora steward/lease
ledgers. Emits reviewed reference *data*, never tokens or execution authority.
No worker dispatch, model calls, GitHub writes, or model weight changes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "server"))
import fleet_r04_leases as leases
import fleet_r05_source_observe as source
import fleet_r3_steward_claim as steward
from app.services.fleet_stewards import StewardRegistry, StewardHeld

SCHEMA = "agentora.capsid.context-handoff.v0.1"
CONFIRM = "RELEASE_REVIEWED_CAPSID_REFERENCE_CONTEXT"
MAX_BUNDLE = 65536


class CapsidHandoffHeld(ValueError):
    """Local capsule, steward, source, or lease is not currently eligible."""


def require(ok, reason):
    if not ok:
        raise CapsidHandoffHeld(reason)


def _lease_matches(ledger, capability, intake, profile, clock):
    """Recheck the existing lease, including its secret bearer and fencing."""
    info = leases.validate_intake(intake)
    require(capability.get("worker") == profile["agent_id"],
            "CAPSID_AGENT_WORKER_MISMATCH")
    require(info["repository"] == profile["repository"],
            "CAPSID_REPOSITORY_MISMATCH")
    with ledger._connection() as db:
        row = ledger._check_owned(db, capability, clock())
        require(all(row[k] == info[k] for k in (
            "repository", "repository_id", "source_sha", "request_sha256"
        )), "LEASE_INTAKE_MISMATCH")
        require(row["worker"] == profile["agent_id"],
                "LEASE_WORKER_MISMATCH")
        require(row["expires_ms"] - clock() >= 60_000,
                "LEASE_RENEWAL_REQUIRED")
        return (row["generation"], row["expires_ms"])


def _observed(result, intake, capability):
    info = leases.validate_intake(intake)
    require(result["state"] == "SOURCE_HEAD_MATCH_OBSERVED"
            and result["repository_id"] == info["repository_id"]
            and result["repository"] == info["repository"]
            and result["requested_sha"] == info["source_sha"]
            and result["source_head_observed_match"] is True
            and result["lease_fenced_at_observation"] is True
            and result["lease_generation"] == capability["generation"],
            "CAPSID_SOURCE_HEAD_NOT_CURRENT")


def handoff(envelope, profile, intake, registry, ledger, capability,
            capsid_api, capsule_store, packs, review_states, *, confirm,
            source_get=source.github_get, token=None, now=None,
            clock=leases.epoch_ms, secret=None):
    """Validate the active capsule and current same-host source/lease.

    capsid_api is the installed phireponerve.capsid module, supplied as an
    argument for offline test fixtures. All actual capsule trust decisions
    are delegated to the original ΦCAPSID implementation.
    """
    require(confirm == CONFIRM, "EXPLICIT_CAPSID_CONFIRMATION_REQUIRED")
    require(callable(source_get) and callable(clock), "OBSERVER_REQUIRED")
    moment = now if now is not None else datetime.now(timezone.utc)
    require(type(moment) is datetime and moment.tzinfo is not None,
            "TIMEZONE_CLOCK_REQUIRED")
    try:
        capsid_api.validate_profile(profile)
        manifest, pack = capsid_api.eligible(envelope, profile, packs,
                                              review_states, secret=secret)
        require(manifest["capabilities"] == ["reference.read"],
                "CONTEXT_ONLY_CAPABILITY_REQUIRED")
        require(type(capability) is dict, "LEASE_CAPABILITY_INVALID")
        info = leases.validate_intake(intake)
        require(profile["repository"] == info["repository"]
                and profile["agent_id"] == capability.get("worker"),
                "CAPSID_TARGET_LEASE_MISMATCH")
        first_steward = steward.eligible(registry, intake, now=moment)
        first_lease = _lease_matches(ledger, capability, intake, profile, clock)

        before = source.observe(intake, capability, ledger,
                                get=source_get, token=token, clock=clock)
        _observed(before, intake, capability)

        # The original provider rechecks HMAC, active SQLite state, pack
        # digest, operator review and target policy on EVERY context export.
        bundle = capsule_store.context(profile, packs, review_states, secret=secret)
        cap = bundle["capsid"]
        require(cap["manifest_digest"] == capsid_api.manifest_digest(manifest)
                and cap["id"] == manifest["id"]
                and cap["agent_label"] == profile["agent_id"]
                and cap["target_repo"] == info["repository"]
                and bundle["selected_packs"][0]["id"] == pack["id"]
                and bundle["selected_packs"][0]["digest"] == manifest["pack"]["digest"]
                and len(bundle["selected_packs"]) == 1
                and cap["tool_permissions_granted"] is False
                and cap["execution_authorized"] is False,
                "ACTIVE_CAPSULE_CONTEXT_CHANGED")
        require(len(json.dumps(bundle, ensure_ascii=False, allow_nan=False)
                    .encode("utf-8")) <= MAX_BUNDLE, "CONTEXT_TOO_LARGE")

        after = source.observe(intake, capability, ledger,
                               get=source_get, token=token, clock=clock)
        _observed(after, intake, capability)
        require(first_steward == steward.eligible(registry, intake, now=moment),
                "STEWARD_CHANGED")
        require(first_lease == _lease_matches(
            ledger, capability, intake, profile, clock), "LEASE_CHANGED")
        # Refuse if the approved pack or capsule selection changed mid-read.
        require(capsule_store.context(profile, packs, review_states,
                                     secret=secret) == bundle,
                "CAPSID_CHANGED_DURING_HANDOFF")
    except (ValueError, KeyError, TypeError, AttributeError, StewardHeld,
            leases.LeaseHeld, steward.HandoffHeld, source.ObservationHeld) as exc:
        if isinstance(exc, CapsidHandoffHeld):
            raise
        raise CapsidHandoffHeld("CAPSID_TRUST_BOUNDARY_HELD_" + str(exc)) from None

    return {
        "schema": SCHEMA,
        "state": "LOCAL_REVIEWED_REFERENCE_CONTEXT_HELD_FOR_WORKER_CONSUMPTION",
        "capsid_id": manifest["id"],
        "capsid_digest": cap["manifest_digest"],
        "pack_id": pack["id"],
        "pack_digest": manifest["pack"]["digest"],
        "agent_label": profile["agent_id"],
        "repository": info["repository"],
        "github_id": info["repository_id"],
        "source_sha": info["source_sha"],
        "source_scan_id": first_steward["source_scan_id"],
        "lease_generation": first_lease[0],
        "lease_expires_ms": first_lease[1],
        "independent_source_head_observed_at_review": True,
        "same_host_lease_fenced_at_review": True,
        "local_pack_review_revalidated": True,
        "local_signature_revalidated": True,
        "agent_identity_authenticated": False,
        "remote_worker_authenticated": False,
        "remote_worker_lease_attested": False,
        "worker_launched": False,
        "tool_permissions_granted": False,
        "model_weights_modified": False,
        "execution_authorized": False,
        "dispatch_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "future_head_stability_guaranteed": False,
        "reference_bundle": bundle,
        "notes": (
            "Point-in-time local reference handoff only. The worker label is not an "
            "authenticated agent identity, and the local shared-secret signature "
            "is not public-key provenance. Do not elevate reference content into "
            "trusted instructions or skip a fresh effect-time lease/HEAD check."
        ),
    }


def _provider():
    try:
        from phireponerve import capsid
        from phireponerve.load import read_packs
        from phireponerve.review import ReviewStore
        return capsid, read_packs, ReviewStore
    except ImportError as exc:
        raise CapsidHandoffHeld(
            "PHIREPONERVE_NOT_INSTALLED: install the reviewed local PhiRepoNerve "
            "checkout with python -m pip install -e ../PhiRepoNerve"
        ) from exc


def _existing(path, label):
    path = Path(path).expanduser()
    require(path.is_file() and not path.is_symlink(),
            label + "_EXISTING_REGULAR_FILE_REQUIRED")
    return path


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--capsule", type=Path, required=True,
                   help="Locally signed ΦCAPSID envelope; no secret stored here")
    p.add_argument("--profile", type=Path, required=True,
                   help="Operator-configured capsule agent profile")
    p.add_argument("--intake", type=Path, required=True,
                   help="Existing Agentora R0.3 source intake")
    p.add_argument("--steward-db", type=Path, required=True)
    p.add_argument("--lease-db", type=Path, required=True)
    p.add_argument("--lease-file", type=Path, required=True)
    p.add_argument("--capsids-db", type=Path, required=True)
    p.add_argument("--packs", type=Path, default=None)
    p.add_argument("--reviews-db", type=Path, required=True)
    p.add_argument("--confirm", required=True)
    args = p.parse_args(argv)
    try:
        require(args.confirm == CONFIRM, "EXPLICIT_CAPSID_CONFIRMATION_REQUIRED")
        capsid, read_packs, ReviewStore = _provider()
        for path, label in ((args.steward_db, "STEWARD"),
                            (args.lease_db, "LEASE"),
                            (args.lease_file, "LEASE_FILE"),
                            (args.capsids_db, "CAPSID"),
                            (args.reviews_db, "PACK_REVIEW")):
            _existing(path, label)
        envelope = capsid.read_json(_existing(args.capsule, "CAPSULE"))
        profile = capsid.read_json(_existing(args.profile, "PROFILE"))
        intake = leases.load_intake(_existing(args.intake, "INTAKE"))
        packs = read_packs(args.packs)
        reviews = ReviewStore(args.reviews_db.expanduser())
        results = handoff(
            envelope, profile, intake,
            StewardRegistry(args.steward_db.expanduser()),
            leases.LeaseLedger(args.lease_db.expanduser()),
            leases.load_capability(args.lease_file.expanduser()),
            capsid, capsid.CapsidStore(args.capsids_db.expanduser()),
            packs, reviews.status_map(packs),
            confirm=args.confirm, token=os.environ.get("GITHUB_TOKEN"),
        )
        print(json.dumps(results, sort_keys=True, indent=2, ensure_ascii=False))
        return 0
    except (CapsidHandoffHeld, leases.LeaseHeld, OSError, ValueError) as exc:
        print("CAPSID_HELD " + str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

"""Fleet R0.2: conservative completion contracts and review-only work queue.

Consumes R0.1's dated audit, enriches only audited public repositories with
bounded GitHub GET observations, and emits proposals. No execution authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import fleet_r01_audit as fleet

SCHEMA = "agentora.fleet.plan.v0.2"
MAX_INPUT_BYTES = 3_000_000
MAX_AGE_HOURS = 24
HEX40 = re.compile(r"^[0-9a-f]{40}$")
# Roles may coexist. Every suggestion remains subject to operator scope review.
CONTRACTS = {
    "web_app": ("build", "automated_tests", "browser_smoke", "production_deployment"),
    "webxr": ("build", "automated_tests", "browser_smoke", "headset_acceptance"),
    "static_site": ("html_validation", "navigation_smoke", "production_deployment"),
    "python_package": ("package_build", "automated_tests", "install_import_smoke"),
    "node_service": ("build", "automated_tests", "api_smoke"),
    "android": ("apk_build", "automated_tests", "device_or_emulator_smoke"),
    "desktop": ("native_build", "automated_tests", "install_launch_smoke"),
    "os_image": ("reproducible_image", "vm_boot", "recovery_smoke", "hardware_acceptance"),
    "research": ("methodology", "reproducible_results", "limitations_review"),
}
TASK_TEXT = {
    "build": "Verify exact-commit production build output",
    "automated_tests": "Run and record project-specific automated test results",
    "browser_smoke": "Run rendered-browser interaction smoke checks",
    "production_deployment": "Verify deployed artifact and exact source revision",
    "headset_acceptance": "Run supported-headset input and comfort acceptance",
    "html_validation": "Validate generated HTML and asset paths",
    "navigation_smoke": "Test navigation and accessibility in a browser",
    "package_build": "Build distributable Python package",
    "install_import_smoke": "Install in clean environment and verify import/CLI",
    "api_smoke": "Start service and verify functional API behavior",
    "apk_build": "Produce installable Android package",
    "device_or_emulator_smoke": "Install and operate on emulator or supported device",
    "native_build": "Build native desktop release",
    "install_launch_smoke": "Install, launch, exit and recover from an error",
    "reproducible_image": "Rebuild OS image from pinned sources",
    "vm_boot": "Boot and exercise the OS image in a virtual machine",
    "recovery_smoke": "Test recovery/rollback using disposable state",
    "hardware_acceptance": "Record explicit compatible-hardware acceptance",
    "methodology": "Document preregistered or reproducible method",
    "reproducible_results": "Reproduce results and negative controls",
    "limitations_review": "Review scope, falsifiability and limitations",
}
# Priority is a triage score, not confidence or importance of a human.
PRIORITY = {
    "automated_tests": 100, "build": 96, "package_build": 96, "apk_build": 96,
    "native_build": 96, "reproducible_image": 96,
    "browser_smoke": 90, "vm_boot": 90, "api_smoke": 90,
    "install_import_smoke": 90, "device_or_emulator_smoke": 90,
    "install_launch_smoke": 90, "html_validation": 85,
    "headset_acceptance": 82, "recovery_smoke": 82,
    "production_deployment": 78, "navigation_smoke": 78,
    "hardware_acceptance": 72, "reproducible_results": 85,
    "methodology": 80, "limitations_review": 75,
}
LINK_TYPE = "README_REFERENCE_NOT_DEPENDENCY"
SHA_REQUIRED = "HEAD_UNVERIFIED"


class PlanHeld(Exception):
    pass


def parse_utc(value):
    if not isinstance(value, str):
        raise PlanHeld("DATE_MISSING")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PlanHeld("DATE_INVALID") from None
    if parsed.tzinfo is None:
        raise PlanHeld("DATE_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def validate_audit(audit, now=None, allow_private=False):
    if not isinstance(audit, dict) or audit.get("schema") != fleet.SCHEMA:
        raise PlanHeld("AUDIT_SCHEMA_INVALID")
    if audit.get("owner") != fleet.OWNER or audit.get("merge_authorized") is not False or \
            audit.get("job_dispatch_authorized") is not False:
        raise PlanHeld("AUDIT_AUTHORITY_OR_OWNER_INVALID")
    rows = audit.get("repositories")
    if not isinstance(rows, list) or len(rows) != audit.get("repository_count"):
        raise PlanHeld("INVENTORY_COVERAGE_INVALID")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = now - parse_utc(audit.get("generated_utc"))
    if age < timedelta(minutes=-5) or age > timedelta(hours=MAX_AGE_HOURS):
        raise PlanHeld("AUDIT_STALE_OR_FUTURE")
    seen_ids = set()
    audited = 0
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("repository_id"), int):
            raise PlanHeld("REPOSITORY_ID_INVALID")
        name = row.get("repository", "")
        if not isinstance(name, str) or not name.startswith(fleet.OWNER + "/"):
            raise PlanHeld("REPOSITORY_OWNER_INVALID")
        fleet.repo_path(name.split("/", 1)[1])
        if row["repository_id"] in seen_ids:
            raise PlanHeld("DUPLICATE_REPOSITORY_ID")
        seen_ids.add(row["repository_id"])
        if row.get("visibility") == "private" and not allow_private:
            raise PlanHeld("PRIVATE_INPUT_REJECTED")
        if row.get("visibility") not in ("public", "private"):
            raise PlanHeld("UNKNOWN_VISIBILITY")
        if row.get("completion") not in ("NOT_AUDITED", "UNVERIFIED"):
            raise PlanHeld("UNSUPPORTED_COMPLETION_ASSERTION")
        if row.get("completion") == "UNVERIFIED":
            audited += 1
    if audited != audit.get("deep_audited_count"):
        raise PlanHeld("DEEP_COVERAGE_INVALID")
    if allow_private and os.getenv("GITHUB_ACTIONS") == "true":
        raise PlanHeld("PRIVATE_ACTIONS_PROHIBITED")
    return rows


def safe_root(read, repo, token):
    """Bounded root directory and README metadata; no arbitrary URL reads."""
    result = {"paths": [], "readme": "", "package": None, "limitations": []}
    base = fleet.repo_path(repo)
    try:
        root = read(base + "/contents", token)
        if isinstance(root, list) and len(root) <= 1000:
            result["paths"] = sorted({x["name"] for x in root if isinstance(x, dict)
                                      and isinstance(x.get("name"), str)})
        else:
            result["limitations"].append("ROOT_UNAVAILABLE_OR_TRUNCATED")
    except fleet.AuditHeld:
        result["limitations"].append("ROOT_FETCH_HELD")
    try:
        payload = read(base + "/readme", token)
        if payload is not None:
            result["readme"] = fleet.decoded_file(payload, max_bytes=120_000) or ""
        else:
            result["limitations"].append("README_UNAVAILABLE")
    except fleet.AuditHeld:
        result["limitations"].append("README_FETCH_HELD")
    if "package.json" in result["paths"]:
        try:
            payload = read(base + "/contents/package.json", token)
            raw = fleet.decoded_file(payload, max_bytes=80_000)
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    result["package"] = parsed
        except (fleet.AuditHeld, ValueError, TypeError):
            result["limitations"].append("PACKAGE_UNREADABLE")
    return result


def classify(row, root):
    paths = {p.lower() for p in root["paths"]}
    readme = root["readme"].lower()[:120_000]
    pkg = root["package"] if isinstance(root["package"], dict) else {}
    deps = pkg.get("dependencies") or {}
    dev = pkg.get("devDependencies") or {}
    deps = {**(deps if isinstance(deps, dict) else {}),
            **(dev if isinstance(dev, dict) else {})}
    deps = {str(x).lower() for x in deps}
    roles = set()
    signals = []
    def mark(role, reason):
        roles.add(role)
        signals.append(reason)
    if {"settings.gradle", "settings.gradle.kts", "gradlew"} & paths or \
            "androidmanifest.xml" in paths:
        mark("android", "ROOT_ANDROID_BUILD_HINT")
    if {"mkarchiso", "grub.cfg", "os-release"} & paths:
        mark("os_image", "ROOT_OS_IMAGE_HINT")
    if "webxr" in readme or "quest 3" in readme or "quest3" in readme:
        if "package.json" in paths or "index.html" in paths:
            mark("webxr", "README_VR_HINT_WITH_WEB_ENTRY")
    if "react" in deps:
        mark("web_app", "PACKAGE_REACT_DEPENDENCY")
    elif "vite" in deps and "index.html" in paths:
        mark("web_app", "VITE_WEB_ENTRY_HINT")
    if {"pyproject.toml", "setup.py", "setup.cfg"} & paths:
        mark("python_package", "ROOT_PYTHON_PACKAGE_MANIFEST")
    if "package.json" in paths and ("express" in deps or "fastify" in deps or
                                    "koa" in deps or "hono" in deps):
        mark("node_service", "PACKAGE_SERVER_DEPENDENCY")
    if "electron" in deps or "tauri.conf.json" in paths:
        mark("desktop", "ROOT_DESKTOP_RUNTIME_HINT")
    if "index.html" in paths and not {"web_app", "webxr"} & roles:
        mark("static_site", "ROOT_HTML_ENTRY")
    if not roles and ({"papers", "experiments", "benchmarks"} & paths or
                      "hypothesis" in readme or "preregister" in readme):
        mark("research", "RESEARCH_DOCUMENTATION_HINT")
    if not roles:
        signals.append("INSUFFICIENT_CLASSIFICATION_EVIDENCE")
    return {"surface_candidates": sorted(roles), "classification_signals": sorted(signals),
            "classification_confidence": "CANDIDATE_ONLY_REVIEW_REQUIRED"}


def check_receipts(receipts, row, now):
    """Operator-supplied receipts are untrusted. Validate only shape, SHA, freshness.

    No receipt can turn completion into COMPLETE or grant execution authority.
    """
    expected = row.get("head_sha")
    output = []
    for receipt in receipts:
        if not isinstance(receipt, dict) or receipt.get("repository") != row["repository"]:
            continue
        identity_ok = bool(isinstance(expected, str) and HEX40.fullmatch(expected) and
                           receipt.get("head_sha") == expected)
        date_ok = False
        try:
            issued = parse_utc(receipt.get("observed_utc"))
            expires = parse_utc(receipt.get("expires_utc"))
            date_ok = issued <= now <= expires and expires - issued <= timedelta(days=14)
        except PlanHeld:
            pass
        check = receipt.get("check_id")
        known = isinstance(check, str) and check in TASK_TEXT
        output.append({"check_id": check if known else "INVALID_CHECK_ID",
                       "disposition": ("SHA_AND_TIME_MATCH_UNTRUSTED_PROVENANCE"
                                       if identity_ok and date_ok and known else
                                       "INVALID_OR_STALE_EVIDENCE"),
                       "provenance": "OPERATOR_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED"})
    return output


def typed_edges(row, known):
    source = row["repository"]
    links = row.get("relationships") or []
    if not isinstance(links, list):
        return []
    edges = []
    for target in links:
        if not isinstance(target, str) or target.lower() not in known:
            continue
        dst = known[target.lower()]
        if dst == source:
            continue
        edges.append({"from": source, "to": dst, "kind": LINK_TYPE,
                      "verified_runtime_integration": False,
                      "blocks_execution": False})
    return sorted(edges, key=lambda e: e["to"].lower())


def tasks_for(row, profile, evidence):
    sha = row.get("head_sha")
    if not isinstance(sha, str) or not HEX40.fullmatch(sha):
        sha = "UNVERIFIED_HEAD"
    roles = profile["surface_candidates"]
    checks = set().union(*(set(CONTRACTS[role]) for role in roles)) if roles else set()
    if not roles:
        checks.add("classification_review")
    ordered = sorted(checks, key=lambda c: (-PRIORITY.get(c, 110), c))
    tasks = []
    for check in ordered:
        ident = hashlib.sha256((row["repository"] + "\n" + sha + "\n" + check).encode()).hexdigest()[:16]
        task = {
            "id": "fleet-" + ident,
            "repository": row["repository"],
            "head_sha": sha,
            "check_id": check,
            "summary": TASK_TEXT.get(check, "Manually classify project and approve its required surfaces"),
            "priority": PRIORITY.get(check, 110),
            "state": "REVIEW_ONLY_NOT_DISPATCHABLE",
            "acceptance": "Attach exact-commit or release-bound independently verifiable proof",
            "prerequisites": [SHA_REQUIRED] if sha == "UNVERIFIED_HEAD" else [],
            "related_evidence": [r["disposition"] for r in evidence if r["check_id"] == check],
        }
        tasks.append(task)
    return tasks


def generate(audit, read, token=None, receipts=None, now=None, allow_private=False):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = validate_audit(audit, now=now, allow_private=allow_private)
    if receipts is None:
        receipts = []
    if not isinstance(receipts, list) or len(receipts) > 1000:
        raise PlanHeld("RECEIPTS_INVALID_OR_TOO_MANY")
    known = {r["repository"].split("/", 1)[1].lower(): r["repository"] for r in rows}
    profiles, edges, tasks = [], [], []
    for row in rows:
        if row["completion"] == "NOT_AUDITED":
            continue
        repo = row["repository"].split("/", 1)[1]
        root = safe_root(read, repo, token)
        category = classify(row, root)
        claims = check_receipts(receipts, row, now)
        profile = {
            "repository": row["repository"],
            "head_sha": row.get("head_sha"),
            **category,
            "observations": {"ci": row.get("ci"), "pages": row.get("pages"),
                             "release": row.get("release")},
            "receipt_review": claims,
            "limitations": root["limitations"],
            "completion": "UNVERIFIED",
            "operator_review_required": True,
        }
        profiles.append(profile)
        edges.extend(typed_edges(row, known))
        tasks.extend(tasks_for(row, profile, claims))
    tasks.sort(key=lambda x: (-x["priority"], x["repository"].lower(), x["check_id"]))
    return {
        "schema": SCHEMA,
        "generated_utc": now.isoformat(),
        "source_audit_utc": audit["generated_utc"],
        "owner": fleet.OWNER,
        "inventory_count": len(rows),
        "deep_audited_count": len(profiles),
        "not_audited_count": len(rows) - len(profiles),
        "verified_complete_count": 0,
        "public_output": not allow_private,
        "merge_authorized": False,
        "job_dispatch_authorized": False,
        "operator_review_required": True,
        "profiles": profiles,
        "edges": edges,
        "tasks": tasks,
    }


def markdown(plan):
    lines = ["# Fleet R0.2: Review-Only Completion Plan", "",
             f"Generated UTC: {plan['generated_utc']}", "",
             f"- Inventory: {plan['inventory_count']}; deep profiles: {plan['deep_audited_count']}",
             f"- Not deep audited: {plan['not_audited_count']}",
             "- **Completed software certified: 0**",
             "- **No tasks dispatched, no PRs merged, no execution authorized**",
             "", "## Work queue (proposals; review required)", "",
             "| Priority | Repository | Proposed work | Evidence |",
             "|---:|---|---|---|"]
    for task in plan["tasks"]:
        lines.append(f"| {task['priority']} | {task['repository']} | "
                     f"{task['summary']} | {task['head_sha'][:12]} |")
    lines.extend(["", "## Surface classifications (candidates only)", ""])
    for profile in plan["profiles"]:
        surfaces = ", ".join(profile["surface_candidates"]) or "UNKNOWN"
        lines.append(f"- **{profile['repository']}**: {surfaces}; "
                     "completion UNVERIFIED; operator classification review required")
    lines.extend(["", "## Relationship graph (references, not dependencies)", ""])
    for edge in plan["edges"]:
        lines.append(f"- {edge['from']} → {edge['to']}: {edge['kind']}")
    if not plan["edges"]:
        lines.append("No README relationship references were observed.")
    lines.extend(["", "Receipt matching checks SHA and dates only. User-supplied receipts "
                  "are not trusted test attestations and never mark a check complete.", ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="fleet-artifacts/fleet-audit.json")
    parser.add_argument("--output-dir", default="fleet-artifacts")
    parser.add_argument("--receipts", help="Optional local-only untrusted evidence JSON array")
    parser.add_argument("--allow-private-local", action="store_true")
    args = parser.parse_args(argv)
    if args.allow_private_local and os.getenv("GITHUB_ACTIONS") == "true":
        raise PlanHeld("PRIVATE_ACTIONS_PROHIBITED")
    source = Path(args.input)
    if source.stat().st_size > MAX_INPUT_BYTES:
        raise PlanHeld("AUDIT_INPUT_TOO_LARGE")
    audit = json.loads(source.read_text(encoding="utf-8"))
    claims = None
    if args.receipts:
        evidence = Path(args.receipts)
        if evidence.stat().st_size > MAX_INPUT_BYTES:
            raise PlanHeld("RECEIPTS_TOO_LARGE")
        claims = json.loads(evidence.read_text(encoding="utf-8"))
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    plan = generate(audit, fleet.github_get, token, claims,
                    allow_private=args.allow_private_local)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "fleet-plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n",
                                            encoding="utf-8")
    (output / "fleet-plan.md").write_text(markdown(plan), encoding="utf-8")
    print(f"FLEET_R02_REVIEW_ONLY repos={plan['inventory_count']} "
          f"profiles={plan['deep_audited_count']} proposed_tasks={len(plan['tasks'])}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PlanHeld, fleet.AuditHeld, ValueError, OSError) as exc:
        print("FLEET_R02_HELD " + (str(exc) if isinstance(exc, (PlanHeld, fleet.AuditHeld))
                                  else "INVALID_INPUT_OR_OUTPUT"), file=sys.stderr)
        raise SystemExit(1)

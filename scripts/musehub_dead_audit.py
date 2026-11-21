#!/usr/bin/env python3
"""Read-only AST hints for Agentora MuseHub dead-code candidates.

This tool never edits project files. A missing reference is NOT permission
to delete code: framework callbacks, database models, dynamic imports and
external consumers may not be visible to static analysis.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path

# Pinned to the MuseHub review on 2026-11-21; update with explicit evidence.
# Columns: repository-relative path, qualified symbol, Muse confidence, triage.
CANDIDATES = [
    ("examples/development-board/r1h-demo-label.py", "normalize_label", "high", "protected-fixture"),
    ("server/app/services/memory.py", "recall", "high", "legacy-review"),
    ("server/app/services/memory.py", "remember", "high", "legacy-review"),
    ("server/app/integrations/agentception_client.py", "AgentCeptionClient.list_job_artifacts", "medium", "integration-contract"),
    ("server/app/integrations/phios_client.py", "PhiOSClient.write_memory", "medium", "integration-contract"),
    ("server/app/integrations/schemas.py", "AlertEventRecord", "medium", "schema-contract"),
    ("server/app/integrations/schemas.py", "LineageTreeResponse", "medium", "schema-contract"),
    ("server/app/integrations/schemas.py", "MissionPatternMemoryRecord", "medium", "schema-contract"),
    ("server/app/integrations/schemas.py", "OperatorDecisionEventRecord", "medium", "schema-contract"),
    ("server/app/integrations/schemas.py", "WatcherEventRecord", "medium", "schema-contract"),
    ("server/app/models.py", "Artifact", "medium", "protected-orm"),
    ("server/app/models.py", "VoiceSetting", "medium", "protected-orm"),
    ("server/app/schemas.py", "CapsuleLayerUpdateIn", "medium", "schema-contract"),
    ("server/app/schemas.py", "MemoryFeedbackIn", "medium", "schema-contract"),
    ("server/app/schemas.py", "MemoryMaintenanceIn", "medium", "schema-contract"),
    ("server/app/services/development_board/r1b_verifier_worker.py", "Witness.handle_data", "medium", "protected-callback"),
    ("server/app/services/development_board/r1b_verifier_worker.py", "Witness.handle_endtag", "medium", "protected-callback"),
    ("server/app/services/development_board/r1b_verifier_worker.py", "Witness.handle_starttag", "medium", "protected-callback"),
    ("server/app/services/integration_orchestrator.py", "IntegrationOrchestrator.get_cached_persona_matrix", "medium", "orchestration-contract"),
    ("server/app/services/integration_orchestrator.py", "IntegrationOrchestrator.get_cached_persona_trends", "medium", "orchestration-contract"),
    ("server/app/services/integration_orchestrator.py", "IntegrationOrchestrator.get_cross_root_persona_summary", "medium", "orchestration-contract"),
    ("server/app/services/integration_orchestrator.py", "IntegrationOrchestrator.maybe_attach_pattern_recommendations", "medium", "orchestration-contract"),
    ("server/app/services/integration_orchestrator.py", "IntegrationOrchestrator.run_software_task_with_context", "medium", "orchestration-contract"),
    ("server/app/services/integration_orchestrator.py", "IntegrationOrchestrator._upsert_pattern_from_candidate", "medium", "orchestration-contract"),
    ("server/app/services/multimodal/service.py", "model_can_vision", "medium", "capability-review"),
    ("server/app/services/ollama_client.py", "OllamaClient.chat_with_tools", "medium", "model-contract"),
    ("server/app/services/ollama_client.py", "OllamaClient.stream_chat", "medium", "model-contract"),
    ("server/app/services/runtime/schemas.py", "CapsuleSearchResult", "medium", "schema-contract"),
]

IGNORED_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".pytest_cache", "dist", "build",
})


def iter_python_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        if not IGNORED_DIRS.intersection(path.relative_to(root).parts):
            yield path


def scan_references(root: Path):
    references = {}
    errors = []
    for path in iter_python_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=rel)
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append({"path": rel, "error": str(exc)[:200]})
            continue
        names = Counter()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                names[node.id] += 1
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                names[node.attr] += 1
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    names[(alias.asname or alias.name.split(".")[-1])] += 1
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.isidentifier():
                    names[node.value] += 1
        references[rel] = names
    return references, errors


def defined_symbols(path: Path):
    """Collect top-level definitions and class methods, not nested closures."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, SyntaxError):
        return set()
    found = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(node.name)
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        found.add(node.name + "." + child.name)
    return found


def make_report(root: Path):
    root = root.resolve()
    references, parse_errors = scan_references(root)
    entries = []
    for path, qualified_name, confidence, category in CANDIDATES:
        simple_name = qualified_name.rsplit(".", 1)[-1]
        hints = sorted(
            ({"path": file, "mentions": count[simple_name]}
             for file, count in references.items()
             if file != path and count[simple_name]),
            key=lambda x: (-x["mentions"], x["path"]),
        )
        entries.append({
            "symbol": path + "::" + qualified_name,
            "confidence": confidence,
            "triage": category,
            "defined_in_checkout": qualified_name in defined_symbols(root / path),
            "other_file_ast_mentions": sum(x["mentions"] for x in hints),
            "reference_hints": hints[:12],
            "safe_to_delete": False,
        })
    return {
        "checkout": str(root),
        "candidate_count": len(entries),
        "candidates": entries,
        "parse_errors": parse_errors,
        "warning": (
            "Name-based references are hints, not verified call edges. "
            "No match is NOT evidence that deletion is safe. Validate "
            "framework dispatch, SQLModel metadata, published APIs, "
            "downstream consumers, and historical contracts first."
        ),
    }


def render_markdown(report):
    lines = [
        "# Agentora MuseHub Dead-Code Audit", "",
        "Read-only AST evidence; NOT deletion authorization.", "",
        "| Candidate | Confidence | Triage | Defined? | Other-file AST mentions |",
        "|---|---|---|---|---:|",
    ]
    for row in report["candidates"]:
        lines.append(
            f"| {row['symbol']} | {row['confidence']} | {row['triage']} | "
            f"{row['defined_in_checkout']} | {row['other_file_ast_mentions']} |"
        )
    lines.extend(["", "## Reference hints", ""])
    for row in report["candidates"]:
        lines.extend([f"### {row['symbol']}", ""])
        if row["reference_hints"]:
            for hint in row["reference_hints"]:
                lines.append(f"- {hint['path']}: {hint['mentions']} AST mention(s)")
        else:
            lines.append("- None detected in other Python files (NOT proof of non-use).")
        lines.append("")
    lines.extend(["## Caveats", "", report["warning"], ""])
    if report["parse_errors"]:
        lines.append(f"Unparsed Python files: {len(report['parse_errors'])}; inspect JSON report.")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path, help="Root of an Agentora checkout")
    parser.add_argument("--output", type=Path, help="Write Markdown report")
    parser.add_argument("--json-output", type=Path, help="Write JSON report")
    args = parser.parse_args()
    if not (args.repo / "server/app/models.py").is_file():
        parser.error("Expected an Agentora checkout containing server/app/models.py")
    report = make_report(args.repo)
    if args.output:
        args.output.write_text(render_markdown(report), encoding="utf-8")
    else:
        print(render_markdown(report))
    if args.json_output:
        args.json_output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

"""R1-B independently implemented fixture verifier (separate local process).

This checks the bytes/HTML against the frozen spec. It NEVER executes generated
HTML or code, grants release authority, or claims secure OS isolation.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

from r1b_contract import read_spec, spec_digest

FORBIDDEN = frozenset({"script", "iframe", "object", "embed", "form", "link", "img", "base"})
VOID = frozenset({"meta", "br", "hr", "input", "wbr", "area"})
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Witness(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[dict] = []
        self.stack: list[int] = []
        self.valid = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.elements) >= 80 or tag in FORBIDDEN:
            self.valid = False
        if len({k for k, _ in attrs}) != len(attrs):
            self.valid = False
        if any(name.lower().startswith("on") for name, _ in attrs):
            self.valid = False
        entry = {"tag": tag, "attrs": dict(attrs), "text": ""}
        self.elements.append(entry)
        if tag not in VOID:
            self.stack.append(len(self.elements) - 1)

    def handle_data(self, data: str) -> None:
        for position in self.stack:
            self.elements[position]["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.elements[self.stack[-1]]["tag"] != tag:
            self.valid = False
        else:
            self.stack.pop()


def _one(elements: list[dict], tag: str, attr: str | None = None,
         value: str | None = None) -> dict:
    found = [element for element in elements if element["tag"] == tag
             and (attr is None or element["attrs"].get(attr) == value)]
    if len(found) != 1:
        raise ValueError("MISSING_OR_AMBIGUOUS_" + tag.upper())
    return found[0]


def verify_fixture(spec: dict[str, str], artifact: bytes, expected_sha: str) -> dict:
    if not SHA256.fullmatch(expected_sha):
        raise ValueError("INVALID_EXPECTED_ARTIFACT_SHA")
    if len(artifact) == 0 or len(artifact) > 12 * 1024:
        raise ValueError("ARTIFACT_SIZE_INVALID")
    actual_sha = hashlib.sha256(artifact).hexdigest()
    if actual_sha != expected_sha:
        raise ValueError("ARTIFACT_DIGEST_CHANGED")
    try:
        body = artifact.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("NON_UTF8_ARTIFACT") from exc
    if not body.lower().startswith("<!doctype html>"):
        raise ValueError("HTML_DOCTYPE_MISSING")
    if re.search(r"(?i)(?:https?://|javascript:|data:|@import|url\s*\()", body):
        raise ValueError("EXTERNAL_RESOURCE_OR_SCRIPT")
    parser = Witness()
    parser.feed(body)
    parser.close()
    if not parser.valid or parser.stack:
        raise ValueError("INVALID_HTML_STRUCTURE_OR_SCRIPT")
    elements = parser.elements
    if _one(elements, "html")["attrs"].get("lang") != "en":
        raise ValueError("HTML_LANGUAGE_MISSING")
    if _one(elements, "title")["text"] != spec["title"]:
        raise ValueError("TITLE_DOES_NOT_MATCH_SPEC")
    main = _one(elements, "main", "id", "content")
    if main["attrs"].get("data-spec-sha256") != spec_digest(spec):
        raise ValueError("SPEC_DIGEST_MISMATCH")
    if _one(elements, "h1")["text"] != spec["headline"]:
        raise ValueError("HEADLINE_DOES_NOT_MATCH_SPEC")
    paragraphs = [x["text"] for x in elements if x["tag"] == "p"]
    if spec["description"] not in paragraphs:
        raise ValueError("DESCRIPTION_DOES_NOT_MATCH_SPEC")
    action = _one(elements, "a", "href", "#details")
    if action["text"] != spec["button_label"]:
        raise ValueError("ACTION_LABEL_DOES_NOT_MATCH_SPEC")
    _one(elements, "a", "href", "#content")
    _one(elements, "section", "id", "details")
    viewport = _one(elements, "meta", "name", "viewport")
    if viewport["attrs"].get("content") != "width=device-width, initial-scale=1":
        raise ValueError("VIEWPORT_MISSING")
    # Every link must be to an internal fragment; no external navigation allowed.
    for item in elements:
        if item["tag"] == "a" and item["attrs"].get("href") not in ("#content", "#details"):
            raise ValueError("UNEXPECTED_LINK_TARGET")
    return {
        "schema": "agentora.devboard.r1b.verify.v1",
        "worker": "independent-fixture-verifier-process",
        "status": "STATIC_CHECKS_PASS_SELF_REPORTED",
        "spec_digest": spec_digest(spec),
        "artifact": "index.html",
        "artifact_sha256": actual_sha,
        "checks": ["sha256", "spec-binding", "html-syntax", "no-scripts-or-external",
                   "semantic-content", "skip-navigation", "viewport"],
        "authority": "NONE",
    }


def main(args: list[str]) -> int:
    if len(args) != 3:
        print(json.dumps({"status": "ERROR", "reason": "VERIFIER_ARGUMENTS", "authority": "NONE"}))
        return 2
    try:
        spec = read_spec(Path(args[0]))
        artifact = Path(args[1])
        if artifact.is_symlink() or not artifact.is_file() or artifact.name != "index.html":
            raise ValueError("INVALID_ARTIFACT_PATH")
        with artifact.open("rb") as stream:
            content = stream.read(12 * 1024 + 1)
        report = verify_fixture(spec, content, args[2])
        print(json.dumps(report))
        return 0
    except (OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "VERIFICATION_IO_ERROR"
        print(json.dumps({"status": "ERROR", "reason": reason[:80], "authority": "NONE"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

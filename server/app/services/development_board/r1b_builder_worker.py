"""R1-B fixed HTML fixture builder worker (operator-run subprocess only).

Not a language model, not a general-purpose source editor, and not a sandbox.
Only writes a new index.html within its supplied disposable workspace.
"""
from __future__ import annotations

import hashlib
import html
import json
import sys
from pathlib import Path

if __package__:
    from .r1b_contract import read_spec, spec_digest
else:
    # The worker is intentionally launched as a standalone -S subprocess too.
    from r1b_contract import read_spec, spec_digest


def build_fixture(spec: dict[str, str], digest: str) -> bytes:
    title = html.escape(spec["title"], quote=True)
    headline = html.escape(spec["headline"], quote=True)
    description = html.escape(spec["description"], quote=True)
    button = html.escape(spec["button_label"], quote=True)
    markup = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: dark; }}
    body {{ font: 1rem/1.6 system-ui, sans-serif; margin: 0; background: #101b2c; color: #f4f8ff; }}
    .skip {{ position: absolute; top: 0; left: 0; padding: .6rem; color: white; }}
    main {{ max-width: 48rem; margin: 5rem auto; padding: 2rem; }}
    h1 {{ font-size: clamp(2rem, 6vw, 3.6rem); }}
    .cta {{ display: inline-block; padding: .8rem 1.4rem; background: #89e3d1; color: #12232d; border-radius: .5rem; }}
    a:focus-visible {{ outline: 3px solid #fff; outline-offset: 4px; }}
  </style>
</head>
<body>
<a class="skip" href="#content">Skip to main content</a>
<main id="content" data-spec-sha256="{digest}">
  <h1>{headline}</h1>
  <p>{description}</p>
  <a class="cta" href="#details">{button}</a>
  <section id="details" aria-label="Details"><h2>Local-first pilot</h2>
    <p>Generated from a bounded human-authored specification. No scripts or external resources.</p>
  </section>
</main>
</body>
</html>
"""
    return markup.encode("utf-8")


def main(args: list[str]) -> int:
    if len(args) != 2:
        print(json.dumps({"status": "ERROR", "reason": "FIXTURE_WORKER_ARGUMENTS"}))
        return 2
    try:
        source = Path(args[0])
        artifact_dir = Path(args[1])
        spec = read_spec(source)
        digest = spec_digest(spec)
        if not artifact_dir.is_dir() or artifact_dir.is_symlink():
            raise ValueError("INVALID_ARTIFACT_DIRECTORY")
        rendered = build_fixture(spec, digest)
        if len(rendered) > 12 * 1024:
            raise ValueError("ARTIFACT_TOO_LARGE")
        destination = artifact_dir / "index.html"
        # Never replace an existing output or follow an existing symlink.
        with destination.open("xb") as stream:
            stream.write(rendered)
            stream.flush()
        print(json.dumps({
            "schema": "agentora.devboard.r1b.build.v1",
            "worker": "fixed-fixture-builder-process",
            "status": "BUILT_SELF_REPORTED",
            "spec_digest": digest,
            "artifact": "index.html",
            "artifact_sha256": hashlib.sha256(rendered).hexdigest(),
            "authority": "NONE",
        }))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        # Do not disclose source content, environment, or credentials in receipts.
        reason = str(exc) if isinstance(exc, ValueError) else "BUILD_IO_ERROR"
        print(json.dumps({"status": "ERROR", "reason": reason[:80], "authority": "NONE"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

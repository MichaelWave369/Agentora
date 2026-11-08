"""Opt-in token-gated LOOPBACK ONLY PHircQ -> Agentora advisory transport.

This server only imports independently verified signed bundles and offers
private read-only inbox views. It never invokes models, tools, GitHub or merges.
No route is mounted in Agentora's general FastAPI service.
"""
from __future__ import annotations

import argparse
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import parse_qs, urlsplit

from app.services.agent_exchange import ExchangeHeld, ID_RE
from app.services.agent_exchange_bridge_cli import read_json_file
from app.services.agent_exchange_durable import DurableReviewInbox
from app.services.agent_exchange_signed_bridge import (
    PeerBinding, contacts_from_bindings, ingest_signed_bundle, parse_trust_policy,
)

MAX_HTTP_BODY = 16384
TOKEN_PATTERN = re.compile(r"[a-f0-9]{64}\Z")
LOOPBACK_ORIGIN = re.compile(
    r"(?:http://(?:localhost|127\.0\.0\.1):[1-9][0-9]{0,4}|tauri://localhost|https?://tauri\.localhost)\Z"
)


def read_token_file(path: str) -> str:
    file = Path(path).expanduser()
    if file.is_symlink():
        raise ExchangeHeld("TOKEN_FILE_SYMLINK")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(file, flags)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 128:
            raise ExchangeHeld("TOKEN_FILE_INVALID")
        if os.name == "posix" and (
            info.st_uid != os.getuid() or info.st_mode & 0o077
        ):
            raise ExchangeHeld("TOKEN_FILE_PERMISSIONS")
        raw = handle.read(129)
    try:
        token = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ExchangeHeld("TOKEN_FILE_INVALID") from exc
    if TOKEN_PATTERN.fullmatch(token) is None:
        raise ExchangeHeld("TOKEN_FORMAT_INVALID")
    return token


def _reject_duplicate_keys(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise ExchangeHeld("JSON_DUPLICATE_KEY")
        obj[k] = v
    return obj


def create_bridge_server(
    *, inbox: DurableReviewInbox, bindings: dict[str, PeerBinding],
    token: str, port: int = 0, allowed_origins: tuple[str, ...] = (),
) -> HTTPServer:
    """Construct private single-worker server. Bind address is NEVER configurable."""
    if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
        raise ValueError("PORT_INVALID")
    if not isinstance(token, str) or TOKEN_PATTERN.fullmatch(token) is None:
        raise ValueError("TOKEN_INVALID")
    if not all(LOOPBACK_ORIGIN.fullmatch(item) for item in allowed_origins):
        raise ValueError("ORIGIN_NOT_LOCAL")
    contacts = contacts_from_bindings(bindings)
    origins = frozenset(allowed_origins)

    class BridgeHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"
        server_version = "AgentoraLocalBridge/1"
        sys_version = ""

        def log_message(self, _fmt, *_args):
            # Keep private message bodies, query strings and bearer tokens out of logs.
            return

        def _respond(self, status: int, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            origin = self.headers.get("Origin")
            if origin and origin in origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(data)

        def _admit(self) -> bool:
            expected_host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != expected_host:
                self._respond(403, {"error": "HOST_REJECTED"})
                return False
            origin = self.headers.get("Origin")
            if origin is not None and origin not in origins:
                self._respond(403, {"error": "ORIGIN_REJECTED"})
                return False
            auth = self.headers.get("Authorization", "")
            if not hmac.compare_digest(auth, "Bearer " + token):
                self._respond(401, {"error": "UNAUTHORIZED"})
                return False
            return True

        def do_OPTIONS(self):
            expected_host = f"127.0.0.1:{self.server.server_port}"
            origin = self.headers.get("Origin")
            requested_method = self.headers.get("Access-Control-Request-Method")
            requested_headers = self.headers.get("Access-Control-Request-Headers", "").lower()
            permitted = (
                (requested_method == "GET" and requested_headers == "authorization")
                or (requested_method == "POST" and requested_headers in (
                    "authorization,content-type", "content-type,authorization"
                ))
            )
            if self.headers.get("Host") != expected_host or origin not in origins or not permitted:
                self._respond(403, {"error": "CORS_DENIED"})
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Max-Age", "60")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            if not self._admit():
                return
            if self.path != "/v1/ingest":
                self._respond(404, {"error": "NOT_FOUND"})
                return
            if self.headers.get("Content-Type", "").lower() != "application/json":
                self._respond(415, {"error": "CONTENT_TYPE_INVALID"})
                return
            if self.headers.get("Transfer-Encoding"):
                self._respond(400, {"error": "CHUNKED_NOT_SUPPORTED"})
                return
            length = self.headers.get("Content-Length", "")
            if not length.isascii() or not length.isdigit():
                self._respond(411, {"error": "LENGTH_REQUIRED"})
                return
            size = int(length)
            if size < 1 or size > MAX_HTTP_BODY:
                self._respond(413, {"error": "BODY_SIZE_INVALID"})
                return
            data = self.rfile.read(size)
            if len(data) != size:
                self._respond(400, {"error": "BODY_INCOMPLETE"})
                return
            try:
                bundle = json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
                state = ingest_signed_bundle(bundle, bindings=bindings, inbox=inbox)
            except (ValueError, UnicodeDecodeError) as exc:
                # No untrusted message contents in HTTP errors.
                self._respond(422, {"error": "BUNDLE_HELD", "reason": str(exc)[:80]})
                return
            self._respond(200, {"state": state, "dispatch_authorized": False,
                                "merge_authorized": False, "outcome_accepted": False})

        def do_GET(self):
            if not self._admit():
                return
            url = urlsplit(self.path)
            if url.path == "/v1/status" and not url.query:
                self._respond(200, {"schema": "agentora.agent-exchange.status.v1",
                    "bound_peers": len(bindings), "local_only": True,
                    "dispatch_authorized": False, "merge_authorized": False})
                return
            if url.path == "/v1/pending":
                try:
                    args = parse_qs(url.query, strict_parsing=True, keep_blank_values=True)
                    if set(args) != {"recipient"} or len(args["recipient"]) != 1:
                        raise ExchangeHeld("QUERY_INVALID")
                    recipient = args["recipient"][0]
                    if ID_RE.fullmatch(recipient) is None or recipient not in contacts:
                        raise ExchangeHeld("RECIPIENT_NOT_FOUND")
                    messages = inbox.pending(recipient)
                except (ValueError, KeyError):
                    self._respond(400, {"error": "QUERY_INVALID"})
                    return
                self._respond(200, {"schema": "agentora.agent-exchange.inbox.v1",
                                    "recipient": recipient, "messages": messages,
                                    "dispatch_authorized": False, "merge_authorized": False})
                return
            self._respond(404, {"error": "NOT_FOUND"})

    server = HTTPServer(("127.0.0.1", port), BridgeHandler)
    server.timeout = 5
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Private opt-in Agentora agent-message receiver")
    parser.add_argument("--trust", required=True, help="Protected out-of-band peer pin policy")
    parser.add_argument("--token-file", required=True, help="Protected 64-character hex token")
    parser.add_argument("--db", required=True, help="Private durable inbox path")
    parser.add_argument("--port", type=int, default=38771)
    parser.add_argument("--allow-origin", action="append", default=[],
                        help="Explicit localhost or Tauri origin allowed to use browser CORS")
    args = parser.parse_args(argv)
    bindings = parse_trust_policy(read_json_file(args.trust, limit=65536, protected=True))
    token = read_token_file(args.token_file)
    inbox = DurableReviewInbox(args.db, contacts=contacts_from_bindings(bindings))
    server = create_bridge_server(inbox=inbox, bindings=bindings, token=token,
                                  port=args.port, allowed_origins=tuple(args.allow_origin))
    print(f"Agentora advisory bridge bound to 127.0.0.1:{server.server_port} (no execution)")
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

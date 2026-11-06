#!/usr/bin/env python3
"""Authenticated loopback proxy in front of Ollama for the AI reviewer."""
from __future__ import annotations

import hmac
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN_FILE = Path(os.environ.get("AI_PROXY_TOKEN_FILE", "/etc/kestrel-ai-proxy/token"))
UPSTREAM = os.environ.get("AI_PROXY_UPSTREAM", "http://127.0.0.1:11434").rstrip("/")
BIND = os.environ.get("AI_PROXY_BIND", "0.0.0.0")
PORT = int(os.environ.get("AI_PROXY_PORT", "8081"))
MAX_BODY = 2 * 1024 * 1024
ALLOWED_PATHS = {"/v1/chat/completions"}
RATE_LIMIT = 12
RATE_WINDOW = 60.0

_token = TOKEN_FILE.read_text(encoding="utf-8").strip()
if len(_token) < 32:
    raise SystemExit(f"AI proxy token is missing or too short: {TOKEN_FILE}")
_requests: dict[str, list[float]] = {}


def rate_ok(remote: str) -> bool:
    now = time.monotonic()
    history = _requests.setdefault(remote, [])
    history[:] = [stamp for stamp in history if now - stamp < RATE_WINDOW]
    if len(history) >= RATE_LIMIT:
        return False
    history.append(now)
    return True


class Handler(BaseHTTPRequestHandler):
    server_version = "KestrelAIProxy/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def reply(self, code: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in ALLOWED_PATHS:
            self.reply(404, b'{"error":"not found"}')
            return
        if not rate_ok(self.client_address[0]):
            self.reply(429, b'{"error":"rate limited"}')
            return
        auth = self.headers.get("Authorization", "")
        if not hmac.compare_digest(auth, "Bearer " + _token):
            self.reply(401, b'{"error":"unauthorized"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.reply(400, b'{"error":"invalid content length"}')
            return
        if length <= 0 or length > MAX_BODY:
            self.reply(413, b'{"error":"request body too large"}')
            return
        body = self.rfile.read(length)
        request = urllib.request.Request(
            UPSTREAM + self.path,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                payload = response.read()
                code = response.status
                content_type = response.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            code = exc.code
            content_type = exc.headers.get("Content-Type", "application/json")
        except Exception as exc:  # noqa: BLE001
            self.reply(502, f'{{"error":"upstream unavailable: {exc}"}}'.encode())
            return
        self.reply(code, payload, content_type)


def main() -> None:
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"kestrel-ai-proxy listening on {BIND}:{PORT} -> {UPSTREAM}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Demo token endpoint for the enterprise-llm-egress ExtAuth step.

POST /token returns {"issued_token": "<short-lived demo jwt>"}.
token-fetcher calls this on every ExtAuth check.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8080
TTL_SECONDS = 30


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def mint() -> str:
    now = int(time.time())
    header = _b64url(b'{"alg":"none","typ":"JWT"}')
    payload = _b64url(
        json.dumps(
            {
                "sub": "enterprise-llm-egress-demo",
                "iat": now,
                "exp": now + TTL_SECONDS,
                "jti": uuid.uuid4().hex,
            }
        ).encode()
    )
    return f"{header}.{payload}.demo"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        print(f"mock-idp: {self.address_string()} - {fmt % args}", flush=True)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        if self.path.rstrip("/") != "/token":
            self.send_error(404)
            return
        body = json.dumps({"issued_token": mint()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/health", "/healthz"):
            self.send_response(200)
            self.end_headers()
            return
        self.send_error(404)


if __name__ == "__main__":
    print(f"mock-idp listening on :{PORT}", flush=True)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()

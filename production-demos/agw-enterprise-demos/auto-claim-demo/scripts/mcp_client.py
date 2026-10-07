#!/usr/bin/env python3
"""Minimal MCP Streamable HTTP client (stdlib only) for the demo scripts.

Usage:
  mcp_client.py --url URL [--token JWT] list
  mcp_client.py --url URL [--token JWT] call TOOL '{"arg": "value"}'

Prints the HTTP status and a short, human-readable result. Exit code is 0 when
the gateway returned HTTP 200 and no JSON-RPC or tool error, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

PROTOCOL_VERSION = "2025-06-18"


def post(url: str, token: str | None, session: str | None, body: dict) -> tuple[int, dict, dict | None, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session:
        headers["Mcp-Session-Id"] = session
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, dict(resp.headers), _parse(raw), raw
    except urllib.error.HTTPError as err:
        raw = err.read().decode(errors="replace")
        return err.code, dict(err.headers), _parse(raw), raw


def _parse(raw: str) -> dict | None:
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("{"):
        try:
            return json.loads(raw)
        except ValueError:
            return None
    # text/event-stream: take the last data: line that parses as JSON-RPC
    found = None
    for line in raw.splitlines():
        if line.startswith("data:"):
            try:
                found = json.loads(line[5:].strip())
            except ValueError:
                pass
    return found


def initialize(url: str, token: str | None) -> tuple[int, str | None, str]:
    status, headers, _, raw = post(
        url,
        token,
        None,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "auto-claim-demo", "version": "0.1.0"},
            },
        },
    )
    session = next((v for k, v in headers.items() if k.lower() == "mcp-session-id"), None)
    if status == 200:
        post(url, token, session, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    return status, session, raw


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--token")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    call = sub.add_parser("call")
    call.add_argument("tool")
    call.add_argument("args", nargs="?", default="{}")
    a = ap.parse_args()

    status, session, raw = initialize(a.url, a.token)
    if status != 200:
        print(f"HTTP {status} on initialize: {raw.strip()[:300]}")
        return 1

    if a.cmd == "list":
        status, _, msg, raw = post(a.url, a.token, session, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        if status != 200 or not msg or "error" in msg:
            print(f"HTTP {status}: {raw.strip()[:300]}")
            return 1
        names = sorted(t["name"] for t in msg["result"]["tools"])
        print(f"HTTP {status}: {len(names)} tools visible -> {', '.join(names)}")
        return 0

    status, _, msg, raw = post(
        a.url,
        a.token,
        session,
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": a.tool, "arguments": json.loads(a.args)}},
    )
    if status != 200 or not msg:
        print(f"HTTP {status}: {raw.strip()[:300]}")
        return 1
    if "error" in msg:
        print(f"HTTP {status}: JSON-RPC error {msg['error'].get('code')}: {msg['error'].get('message')}")
        return 1
    result = msg.get("result", {})
    text = " ".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))
    if result.get("isError"):
        print(f"HTTP {status}: tool error: {text[:300]}")
        return 1
    print(f"HTTP {status}: {text[:400]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

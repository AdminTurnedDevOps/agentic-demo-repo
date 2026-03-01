#!/usr/bin/env bash
set -euo pipefail

SUB="${1:-alice}"
TEAM="${2:-finance}"
SECRET="${JWT_HS256_SECRET:-rebac-demo-shared-secret-please-change}"
AUD="${JWT_AUD:-mcp-rebac-demo}"
ISS="${JWT_ISS:-rebac.demo.local}"
APPROVER_PROJECTS="${3:-}"

python3 - "$SUB" "$TEAM" "$SECRET" "$AUD" "$ISS" "$APPROVER_PROJECTS" <<'PY'
import base64
import hashlib
import hmac
import json
import sys
import time

sub, team, secret, aud, iss, approver_projects = sys.argv[1:7]

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip('=')

header = {"alg": "HS256", "typ": "JWT", "kid": "rebac-demo-hs256"}
now = int(time.time())
payload = {
    "iss": iss,
    "sub": sub,
    "aud": aud,
    "team": team,
    "iat": now,
    "nbf": now,
    "exp": now + 3600,
}
if approver_projects:
    payload["approver_projects"] = [p.strip() for p in approver_projects.split(',') if p.strip()]

unsigned = f"{b64url(json.dumps(header,separators=(',',':')).encode())}.{b64url(json.dumps(payload,separators=(',',':')).encode())}"
sig = b64url(hmac.new(secret.encode(), unsigned.encode(), hashlib.sha256).digest())
print(f"{unsigned}.{sig}")
PY

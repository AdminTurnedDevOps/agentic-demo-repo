#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${GATEWAY_URL:-http://localhost:3000}"

curl -si "$BASE_URL/acme" \
  -X POST \
  -H 'content-type: application/json' \
  -H 'anthropic-version: 2023-06-01' \
  -H 'x-tenant: acme' \
  -d '{"max_tokens":64,"messages":[{"role":"user","content":"missing team and role headers"}]}'

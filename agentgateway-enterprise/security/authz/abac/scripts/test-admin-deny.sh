#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${GATEWAY_URL:-http://localhost:3000}"

echo "Case 1: non-engineering denied"
curl -si "$BASE_URL/admin" \
  -X POST \
  -H 'content-type: application/json' \
  -H 'anthropic-version: 2023-06-01' \
  -H 'x-tenant: acme' \
  -H 'x-team: sales' \
  -H 'x-role: employee' \
  -d '{"max_tokens":64,"messages":[{"role":"user","content":"deny me"}]}'

echo
echo "Case 2: contractor denied"
curl -si "$BASE_URL/admin" \
  -X POST \
  -H 'content-type: application/json' \
  -H 'anthropic-version: 2023-06-01' \
  -H 'x-tenant: acme' \
  -H 'x-team: engineering' \
  -H 'x-role: contractor' \
  -d '{"max_tokens":64,"messages":[{"role":"user","content":"deny me too"}]}'

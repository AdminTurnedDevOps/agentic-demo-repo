#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_URL="${GATEWAY_URL:-http://localhost:3000/mcp}"
ALICE_TOKEN="$(${ROOT_DIR}/scripts/mint-jwt.sh alice finance)"
ALICE_APPROVER_TOKEN="$(${ROOT_DIR}/scripts/mint-jwt.sh alice finance q1-forecast)"

call() {
  local token="$1"
  local body="$2"
  curl -sS "$GATEWAY_URL" \
    -H "content-type: application/json" \
    -H "authorization: Bearer ${token}" \
    -d "$body" | jq
}

echo "Alice tools/list (expect finance tools only)"
call "$ALICE_TOKEN" '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

echo "Alice tools/call create_forecast_ticket (expect allow)"
call "$ALICE_TOKEN" '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"create_forecast_ticket","arguments":{"quarter":"Q1"}}}'

echo "Alice tools/call read_budget without approver tuple (expect deny)"
call "$ALICE_TOKEN" '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"read_budget","arguments":{"project":"q1-forecast"}}}'

echo "Alice tools/call read_budget with contextual approver claim (expect allow)"
call "$ALICE_APPROVER_TOKEN" '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"read_budget","arguments":{"project":"q1-forecast"}}}'

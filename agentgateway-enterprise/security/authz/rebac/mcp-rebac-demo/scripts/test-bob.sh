#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_URL="${GATEWAY_URL:-http://localhost:3000/mcp}"
BOB_TOKEN="$(${ROOT_DIR}/scripts/mint-jwt.sh bob engineering)"

call() {
  local body="$1"
  curl -sS "$GATEWAY_URL" \
    -H "content-type: application/json" \
    -H "authorization: Bearer ${BOB_TOKEN}" \
    -d "$body" | jq
}

echo "Bob tools/list (expect engineering tools only)"
call '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

echo "Bob tools/call get_deploy_status (expect allow)"
call '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_deploy_status","arguments":{}}}'

echo "Bob tools/call read_budget (expect deny)"
call '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"read_budget","arguments":{"project":"q1-forecast"}}}'

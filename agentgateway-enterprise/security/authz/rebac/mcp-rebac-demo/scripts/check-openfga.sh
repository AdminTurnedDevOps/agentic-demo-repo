#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/openfga/.env"

check() {
  local user="$1"
  local relation="$2"
  local object="$3"
  local body
  body=$(jq -n \
    --arg u "$user" --arg r "$relation" --arg o "$object" --arg m "$OPENFGA_MODEL_ID" \
    '{tuple_key:{user:$u,relation:$r,object:$o},authorization_model_id:$m}')
  curl -sS -X POST "${OPENFGA_URL}/stores/${OPENFGA_STORE_ID}/check" \
    -H 'content-type: application/json' \
    -d "$body" | jq
}

echo "alice discover finance/read_budget"
check user:alice discover tool:finance/read_budget

echo "alice discover engineering/get_deploy_status"
check user:alice discover tool:engineering/get_deploy_status

echo "alice invoke finance/read_budget (expected false before contextual tuple)"
check user:alice invoke tool:finance/read_budget

echo "alice invoke finance/create_forecast_ticket"
check user:alice invoke tool:finance/create_forecast_ticket

echo "bob invoke engineering/restart_staging_service"
check user:bob invoke tool:engineering/restart_staging_service

ctx=$(jq -n \
  --arg m "$OPENFGA_MODEL_ID" \
  '{
    tuple_key:{user:"user:alice",relation:"invoke",object:"tool:finance/read_budget"},
    authorization_model_id:$m,
    contextual_tuples:{tuple_keys:[{user:"user:alice",relation:"approver",object:"project:q1-forecast"}]}
  }')

echo "alice invoke finance/read_budget with contextual approver tuple (expected true)"
curl -sS -X POST "${OPENFGA_URL}/stores/${OPENFGA_STORE_ID}/check" \
  -H 'content-type: application/json' \
  -d "$ctx" | jq

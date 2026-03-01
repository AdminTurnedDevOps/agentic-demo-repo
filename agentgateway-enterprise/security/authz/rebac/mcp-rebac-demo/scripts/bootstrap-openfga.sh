#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENFGA_URL="${OPENFGA_URL:-http://localhost:8080}"
STORE_NAME="${STORE_NAME:-mcp-rebac-demo}"
MODEL_JSON="${ROOT_DIR}/openfga/model.json"
ENV_FILE="${ROOT_DIR}/openfga/.env"

command -v jq >/dev/null || { echo "jq is required"; exit 1; }

until curl -sf "${OPENFGA_URL}/healthz" >/dev/null; do
  echo "waiting for OpenFGA at ${OPENFGA_URL}..."
  sleep 2
done

STORE_ID="$(curl -sS -X POST "${OPENFGA_URL}/stores" \
  -H 'content-type: application/json' \
  -d "{\"name\":\"${STORE_NAME}\"}" | jq -r '.id')"

MODEL_ID="$(curl -sS -X POST "${OPENFGA_URL}/stores/${STORE_ID}/authorization-models" \
  -H 'content-type: application/json' \
  --data-binary "@${MODEL_JSON}" | jq -r '.authorization_model_id')"

cat > "${ENV_FILE}" <<ENV
OPENFGA_URL=${OPENFGA_URL}
OPENFGA_STORE_ID=${STORE_ID}
OPENFGA_MODEL_ID=${MODEL_ID}
ENV

echo "Created store: ${STORE_ID}"
echo "Created model: ${MODEL_ID}"
echo "Wrote ${ENV_FILE}"

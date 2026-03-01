#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/openfga/.env"

curl -sS -X POST "${OPENFGA_URL}/stores/${OPENFGA_STORE_ID}/write" \
  -H 'content-type: application/json' \
  --data-binary "@${ROOT_DIR}/openfga/tuples.json" | jq

echo "Seeded tuples into ${OPENFGA_STORE_ID}"

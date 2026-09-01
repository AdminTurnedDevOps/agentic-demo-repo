#!/usr/bin/env bash
# Fetch a Keycloak access token for reader|writer|admin.
# Password comes from DEALERIQ_PASSWORD (the UI login password). Never commit it.
set -euo pipefail

ROLE="${1:-reader}"
case "${ROLE}" in
  reader|writer|admin) ;;
  *)
    echo "usage: $0 reader|writer|admin" >&2
    exit 1
    ;;
esac

if [[ -z "${DEALERIQ_PASSWORD:-}" ]]; then
  echo "Set DEALERIQ_PASSWORD to the Keycloak password you use at the kagent UI login." >&2
  exit 1
fi

TOKEN_URL="${TOKEN_URL:-https://demo-keycloak-907026730415.us-east4.run.app/realms/kagent-dev/protocol/openid-connect/token}"
CLIENT_ID="${CLIENT_ID:-kagent-ui}"

resp="$(curl -sS -X POST "${TOKEN_URL}" \
  -d "client_id=${CLIENT_ID}" \
  -d "username=${ROLE}" \
  -d "password=${DEALERIQ_PASSWORD}" \
  -d "grant_type=password")"

token="$(echo "${resp}" | jq -r '.access_token // empty')"
if [[ -z "${token}" || "${token}" == "null" ]]; then
  echo "${resp}" | jq -c '{error,error_description}' >&2 || echo "${resp}" >&2
  exit 1
fi

echo "${token}"

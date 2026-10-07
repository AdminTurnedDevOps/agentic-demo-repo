#!/usr/bin/env bash
# Creates the demo's Secrets in the auto-claims namespace from env vars and
# existing cluster secrets. Never writes credentials to disk.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

: "${AWS_ACCESS_KEY_ID:?set AWS_ACCESS_KEY_ID (see README Credentials)}"
: "${OPENAI_API_KEY:?set OPENAI_API_KEY (see README Credentials)}"
: "${AWS_SECRET_ACCESS_KEY:?set AWS_SECRET_ACCESS_KEY}"

apply_secret() { kubectl apply -f - >/dev/null; ok "secret $1"; }

# AWS credentials for Bedrock (model calls and Guardrails). Session tokens
# expire: re-run make secrets after refreshing them.
kubectl create secret generic bedrock-secret -n "${NS}" \
  --from-literal=accessKey="${AWS_ACCESS_KEY_ID}" \
  --from-literal=secretKey="${AWS_SECRET_ACCESS_KEY}" \
  ${AWS_SESSION_TOKEN:+--from-literal=sessionToken="${AWS_SESSION_TOKEN}"} \
  --dry-run=client -o yaml | apply_secret bedrock-secret

kubectl create secret generic openai-secret -n "${NS}" \
  --from-literal=Authorization="Bearer ${OPENAI_API_KEY}" \
  --dry-run=client -o yaml | apply_secret openai-secret

# Optional: copy an image pull secret named regcred for a private registry.
if [[ -n "${PULL_SECRET_NAMESPACE:-}" ]]; then
  kubectl -n "${PULL_SECRET_NAMESPACE}" get secret regcred -o json \
    | jq --arg ns "${NS}" '{apiVersion, kind, type, data, metadata: {name: .metadata.name, namespace: $ns}}' \
    | apply_secret "regcred (copied from ${PULL_SECRET_NAMESPACE})"
fi

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ANTHROPIC_API_KEY is required for setup.sh"
  echo "Example: export ANTHROPIC_API_KEY=<your-key>"
  exit 1
fi

kubectl apply -f "$ROOT_DIR/manifests/gateway.yaml"
kubectl -n abac-demo create secret generic anthropic-secret \
  --from-literal=Authorization="$ANTHROPIC_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "$ROOT_DIR/manifests/enterprise-agentgateway-policy.yaml"

echo "Done."
echo "Install OPA via Helm using:"
echo "  $ROOT_DIR/opa-install.md"
echo "Then port-forward the Gateway service if needed:"
echo "  kubectl -n abac-demo port-forward svc/abac-gateway 3000:3000"

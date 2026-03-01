#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS="rebac-mcp-demo"

kubectl apply -f "${ROOT_DIR}/k8s/namespace.yaml"
kubectl apply -f "${ROOT_DIR}/k8s/mcp-finance.yaml"
kubectl apply -f "${ROOT_DIR}/k8s/mcp-engineering.yaml"
kubectl apply -f "${ROOT_DIR}/k8s/adapter.yaml"

kubectl -n "${NS}" rollout status deploy/mcp-finance --timeout=180s
kubectl -n "${NS}" rollout status deploy/mcp-engineering --timeout=180s
kubectl -n "${NS}" rollout status deploy/rebac-auth-adapter --timeout=180s

if [[ -z "${OPENFGA_URL:-}" ]]; then
  echo "OPENFGA_URL is required. OpenFGA is expected to be pre-installed (per setup.md)."
  echo "Example:"
  echo "  export OPENFGA_URL=http://<openfga-loadbalancer-ip>:8080"
  echo "If no LoadBalancer is available, use port-forward and set:"
  echo "  export OPENFGA_URL=http://localhost:8080"
  exit 1
fi

if ! curl -sf "${OPENFGA_URL}/healthz" >/dev/null; then
  echo "Cannot reach OpenFGA at ${OPENFGA_URL}"
  echo "Ensure the URL is correct and reachable, then rerun."
  exit 1
fi

"${ROOT_DIR}/scripts/bootstrap-openfga.sh"
"${ROOT_DIR}/scripts/seed-demo-data.sh"

MODEL_ID=$(awk -F= '/OPENFGA_MODEL_ID/ {print $2}' "${ROOT_DIR}/openfga/.env")
kubectl -n "${NS}" set env deploy/rebac-auth-adapter OPENFGA_MODEL_ID="${MODEL_ID}"
kubectl -n "${NS}" rollout status deploy/rebac-auth-adapter --timeout=180s

kubectl apply -f "${ROOT_DIR}/k8s/agentgateway.yaml"
kubectl apply -f "${ROOT_DIR}/k8s/jwt-policy.yaml"
kubectl apply -f "${ROOT_DIR}/k8s/auth-policies.yaml"

kubectl -n "${NS}" get gateway,httproute,agentgatewaybackend,enterpriseagentgatewaypolicy

echo "Port-forward the gateway in a second shell:"
echo "kubectl -n ${NS} port-forward svc/mcp-rebac-gateway 3000:3000"
echo "Then run:"
echo "  ${ROOT_DIR}/scripts/test-alice.sh"
echo "  ${ROOT_DIR}/scripts/test-bob.sh"

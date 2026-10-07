#!/usr/bin/env bash
# Checks everything the demo depends on, without changing anything.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

require_cmd kubectl helm jq curl python3

ctx="$(kubectl config current-context)"
say "kubectl context: ${ctx}"

kubectl get crd enterpriseagentgatewaypolicies.enterpriseagentgateway.solo.io >/dev/null 2>&1 \
  || fail "Enterprise agentgateway CRDs not installed"
ok "Enterprise agentgateway CRDs present"
kubectl get crd agents.kagent.dev remotemcpservers.kagent.dev mcpservers.kagent.dev >/dev/null 2>&1 \
  || fail "kagent CRDs (Agent, RemoteMCPServer, MCPServer) not installed"
ok "kagent CRDs present"

kubectl -n "${AGW_NS}" rollout status deploy/enterprise-agentgateway --timeout=10s >/dev/null \
  || fail "enterprise-agentgateway controller not ready in ${AGW_NS}"
ok "enterprise-agentgateway controller ready ($(kubectl -n "${AGW_NS}" get deploy enterprise-agentgateway -o jsonpath='{.spec.template.spec.containers[0].image}'))"
kubectl -n kagent rollout status deploy/kagent-controller --timeout=10s >/dev/null \
  || fail "kagent-controller not ready"
ok "kagent-controller ready"

if kubectl -n "${AGW_NS}" get svc enterprise-agentgateway -o jsonpath='{.spec.ports[*].port}' | tr ' ' '\n' | grep -qx 7777; then
  ok "agentgateway STS enabled (:7777)"
else
  warn "agentgateway STS not enabled yet. Run: make enable-sts"
fi

for v in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY BEDROCK_REGION BEDROCK_MODEL BEDROCK_GUARDRAIL_ID BEDROCK_GUARDRAIL_VERSION; do
  [[ -n "${!v:-}" ]] && ok "${v} set" || warn "${v} not set (needed by make secrets / make render)"
done
for v in OPENAI_API_KEY KEYCLOAK_REALM_URL REGISTRY; do
  [[ -n "${!v:-}" ]] && ok "${v} set" || warn "${v} not set (see README Credentials)"
done
[[ -n "${CLAIMS_DEMO_PASSWORD:-${DEALERIQ_PASSWORD:-}}" ]] && ok "Keycloak demo password set" \
  || warn "CLAIMS_DEMO_PASSWORD not set (needed by make personas and the scene scripts)"

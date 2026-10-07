#!/usr/bin/env bash
# Pre-recording check: the platform is up, the demo is at its starting point,
# and both personas can sign in. Makes one short model call and one tool listing.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
rc=0
check() { if eval "$2" >/dev/null 2>&1; then ok "$1"; else printf '%s\n' "${c_red}FAIL${c_off} $1"; rc=1; fi; }
attached() { kubectl -n "${NS}" get enterpriseagentgatewaypolicy "$1" -o jsonpath='{.status.ancestors[*].conditions[?(@.type=="Attached")].status}' | grep -q True; }

say "Platform"
check "STS enabled on enterprise-agentgateway :7777" "kubectl -n ${AGW_NS} get svc enterprise-agentgateway -o jsonpath='{.spec.ports[*].port}' | grep -qw 7777"
check "Gateway claims-gateway Programmed" "kubectl -n ${NS} wait --for=condition=Programmed gateway/claims-gateway --timeout=5s"
check "MCPServer claims-mcp Ready" "kubectl -n ${NS} wait --for=condition=Ready mcpserver/claims-mcp --timeout=5s"
check "Agent claims-agent Ready" "kubectl -n ${NS} wait --for=condition=Ready agent/claims-agent --timeout=5s"
for be in claims-mcp claims-llm claims-agent-a2a; do
  check "Backend ${be} Accepted" "kubectl -n ${NS} wait --for=condition=Accepted enterpriseagentgatewaybackend/${be} --timeout=5s"
done
for p in claims-gateway-audit claims-llm-primary-auth claims-llm-fallback-auth claims-llm-failover-health; do
  check "Policy ${p} Attached" "attached ${p}"
done
check "Bedrock region is the real one (not the outage scene)" "[[ \$(kubectl -n ${NS} get enterpriseagentgatewaybackend claims-llm -o jsonpath='{.spec.ai.groups[0].providers[0].bedrock.region}') != us-outage-1 ]]"

say "Starting point (scene policies must NOT be applied yet)"
for p in claims-a2a-identity claims-mcp-identity claims-llm-identity claims-tool-registry claims-llm-guardrails claims-llm-token-limit; do
  if kubectl -n "${NS}" get enterpriseagentgatewaypolicy "${p}" >/dev/null 2>&1; then
    printf '%s\n' "${c_red}FAIL${c_off} ${p} is applied: run ./demo.sh reset"; rc=1
  else ok "${p} not applied"; fi
done

say "Personas and smoke test"
port_forward_gateway
for u in reader writer; do check "${u} can sign in" "( keycloak_token ${u} )"; done
r="$(mcp --token "$(agent_delegated_token writer)" list 2>&1)"; echo "   tools: ${r}"
[[ "${r}" == *"7 tools visible"* ]] || { printf '%s\n' "${c_red}FAIL${c_off} expected all 7 tools with no registry applied"; rc=1; }
m="$(curl -s "${GW_URL}/v1/chat/completions" -H 'content-type: application/json' \
  -d '{"model":"claims-assistant","max_tokens":5,"messages":[{"role":"user","content":"Reply OK"}]}' | jq -r '.model // .error.message // "error"')"
[[ "${m}" == *anthropic* ]] && ok "model route serves Bedrock (${m})" || { printf '%s\n' "${c_red}FAIL${c_off} model route returned: ${m}"; rc=1; }

[[ ${rc} -eq 0 ]] && say "Ready to record." || say "Fix the failures above first."
exit ${rc}

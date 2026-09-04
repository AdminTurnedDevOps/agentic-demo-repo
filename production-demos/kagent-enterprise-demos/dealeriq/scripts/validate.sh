#!/usr/bin/env bash
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "OK: $*"; }

NS=dealeriq

kubectl get deploy kagent-controller -n kagent >/dev/null 2>&1 || fail "kagent-controller missing"
ready="$(kubectl get deploy kagent-controller -n kagent -o jsonpath='{.status.readyReplicas}')"
[[ "${ready}" == "1" ]] || fail "kagent-controller not Ready (readyReplicas=${ready})"
ok "kagent-controller Ready"

kubectl get ns "${NS}" >/dev/null 2>&1 || fail "namespace ${NS} missing"
ok "namespace ${NS} exists"

kubectl get mcpserver dealer-leads-mcp -n "${NS}" >/dev/null 2>&1 || fail "MCPServer dealer-leads-mcp missing"
mcp_ready="$(kubectl get mcpserver dealer-leads-mcp -n "${NS}" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"
[[ "${mcp_ready}" == "True" ]] || fail "MCPServer dealer-leads-mcp not Ready (${mcp_ready})"
ok "MCPServer dealer-leads-mcp Ready"
transport="$(kubectl get mcpserver dealer-leads-mcp -n "${NS}" -o jsonpath='{.spec.transportType}')"
[[ "${transport}" == "http" ]] || fail "MCPServer transportType is ${transport}, expected http (Streamable HTTP)"
ok "MCPServer transportType http"

for agent in dealer-assistant dealer-assistant-byo; do
  kubectl get agent "${agent}" -n "${NS}" >/dev/null 2>&1 || fail "Agent ${agent} missing"
  st="$(kubectl get agent "${agent}" -n "${NS}" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"
  [[ "${st}" == "True" ]] || fail "Agent ${agent} not Ready (${st})"
  ok "Agent ${agent} Ready"
done

gw="$(kubectl get gateway dealeriq-llm -n "${NS}" -o jsonpath='{.status.conditions[?(@.type=="Programmed")].status}')"
[[ "${gw}" == "True" ]] || fail "Gateway dealeriq-llm not Programmed (${gw})"
ok "Gateway dealeriq-llm Programmed"

route="$(kubectl get httproute dealeriq-llm-route -n "${NS}" -o jsonpath='{.status.parents[0].conditions[?(@.type=="Accepted")].status}')"
[[ "${route}" == "True" ]] || fail "HTTPRoute dealeriq-llm-route not Accepted (${route})"
ok "HTTPRoute dealeriq-llm-route Accepted"

for be in dealeriq-claude dealeriq-mock-llm; do
  kubectl get enterpriseagentgatewaybackend "${be}" -n "${NS}" >/dev/null 2>&1 || fail "EnterpriseAgentgatewayBackend ${be} missing"
  acc="$(kubectl get enterpriseagentgatewaybackend "${be}" -n "${NS}" -o jsonpath='{.status.conditions[?(@.type=="Accepted")].status}')"
  [[ "${acc}" == "True" ]] || fail "EnterpriseAgentgatewayBackend ${be} not Accepted (${acc})"
  ok "EnterpriseAgentgatewayBackend ${be} Accepted"
done

tracing="$(kubectl get enterpriseagentgatewaypolicy dealeriq-llm-tracing -n "${NS}" -o jsonpath='{.status.ancestors[0].conditions[?(@.type=="Attached")].status}')"
[[ "${tracing}" == "True" ]] || fail "dealeriq-llm tracing policy not Attached (${tracing})"
ok "dealeriq-llm tracing policy Attached"

for mock in dealeriq-mock-llm dealeriq-mock-llm-ok; do
  mock_ready="$(kubectl get deploy "${mock}" -n "${NS}" -o jsonpath='{.status.readyReplicas}')"
  [[ "${mock_ready}" == "1" ]] || fail "${mock} not Ready (readyReplicas=${mock_ready})"
  ok "${mock} Ready"
done

cb="$(kubectl get enterpriseagentgatewaypolicy dealeriq-mock-llm-circuit-breaker -n "${NS}" --ignore-not-found)"
if [[ -n "${cb}" ]]; then
  fail "circuit-breaker policy is applied; Demo 4 only. run make demo-reset"
fi
ok "Demo 4 circuit-breaker policy absent"

budget="$(kubectl get enterpriseagentgatewaybudget dealeriq-daily-token-budget -n "${NS}" --ignore-not-found)"
if [[ -n "${budget}" ]]; then
  fail "token budget is applied; Demo 4 only. run make demo-reset"
fi
rl="$(kubectl get enterpriseagentgatewaypolicy dealeriq-llm-rate-limit -n "${NS}" --ignore-not-found)"
if [[ -n "${rl}" ]]; then
  fail "rate-limit policy is applied; Demo 4 only. run make demo-reset"
fi
ok "Demo 4 budget and rate-limit absent"

live="$(kubectl get accesspolicy dealeriq-reader-update-lead-status -n "${NS}" --ignore-not-found)"
if [[ -n "${live}" ]]; then
  fail "live-edit policy dealeriq-reader-update-lead-status is still applied; run make demo-reset"
fi
writer="$(kubectl get accesspolicy dealeriq-writer-tools -n "${NS}" --ignore-not-found)"
if [[ -n "${writer}" ]]; then
  fail "writer policy dealeriq-writer-tools is still applied; run make demo-reset"
fi
ok "baseline policies (writer and live-edit absent)"

for pol in dealeriq-deny-all-mcp dealeriq-reader-read-tools; do
  st="$(kubectl get accesspolicy "${pol}" -n "${NS}" -o jsonpath='{.status.state}')"
  [[ "${st}" == "Applied" ]] || fail "AccessPolicy ${pol} not Applied (${st})"
  ok "AccessPolicy ${pol} Applied"
done

tool_list="$(kubectl exec -n "${NS}" deploy/dealer-leads-mcp -c mcp-server -- \
  /usr/local/bin/python -W ignore -c 'import os,sys; os.environ.setdefault("DATA_DIR","/data"); sys.path.insert(0,"/app"); from server import mcp; names=sorted(mcp._tool_manager._tools); print(",".join(names))')"
expected="draft_followup,export_leads,get_lead_details,get_vehicle_history,score_lead,search_inventory,send_customer_offer,update_lead_status"
[[ "${tool_list}" == "${expected}" ]] || fail "MCP tools mismatch: ${tool_list}"
ok "MCP tools registered (${tool_list})"

echo "validate.sh green"

#!/usr/bin/env bash
# Scene 5: approved models only, with failover.
#   probe   - send requests and show which approved model served each one
#   break   - simulate a Bedrock credential outage
#   restore - put the real Bedrock credential back
set -uo pipefail
source "$(dirname "$0")/lib.sh"
action="${1:-probe}"

probe() {
  port_forward_gateway
  local tok; tok="$(agent_delegated_token "${ADJUSTER_USER:-writer}")"
  for i in 1 2 3; do
    resp="$(curl -s -w '\n%{http_code}' "${GW_URL}/v1/chat/completions" -H "Authorization: Bearer ${tok}" -H 'content-type: application/json' \
      -d '{"model":"gpt-4o","max_tokens":20,"messages":[{"role":"user","content":"Reply with the word OK."}]}')"
    code="$(tail -1 <<<"${resp}")"
    model="$(sed '$d' <<<"${resp}" | jq -r '.model // "-"' 2>/dev/null)"
    printf '   request %d: asked for gpt-4o -> HTTP %s, served by %s\n' "${i}" "${code}" "${model}"
  done
}

case "${action}" in
  probe) say "The agent asks for an unapproved model; the gateway serves an approved one"; probe ;;
  break)
    kubectl apply -f "${GEN_DIR}/manifests/scenes/failover-break-primary.yaml" >/dev/null
    say "Bedrock region unreachable. The first request fails and evicts Bedrock; the rest fail over to OpenAI:"
    probe ;;
  restore)
    kubectl apply -f "${GEN_DIR}/manifests/31-llm-route.yaml"
    ok "Bedrock restored (it rejoins after its 120s eviction window)" ;;
  *) fail "usage: $0 probe|break|restore" ;;
esac

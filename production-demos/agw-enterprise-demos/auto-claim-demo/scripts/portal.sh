#!/usr/bin/env bash
# The "claims portal": signs a member in at Keycloak and sends their request to
# claims-agent over A2A through claims-gateway, the way a member-facing app would.
#   portal.sh <reader|writer> "message"
#   portal.sh --anonymous "message"     # no identity at all
set -euo pipefail
source "$(dirname "$0")/lib.sh"
who="${1:?usage: portal.sh <reader|writer|--anonymous> message}"; msg="${2:?message}"
port_forward_gateway

headers=(-H 'content-type: application/json')
if [[ "${who}" != "--anonymous" ]]; then
  headers+=(-H "Authorization: Bearer $(keycloak_token "${who}")")
  case "${who}" in
    reader) tier="member-services tier" ;;
    writer) tier="adjuster tier" ;;
    *)      tier="" ;;
  esac
  say "Signed in as ${who}${tier:+ (${tier})}. Sending to claims-agent via agentgateway (A2A):"
else
  say "No sign-in. Sending to claims-agent via agentgateway (A2A):"
fi
echo "   > ${msg}"

body="$(jq -n --arg m "${msg}" --arg id "$(uuidgen | tr 'A-Z' 'a-z')" \
  '{jsonrpc:"2.0",id:1,method:"message/send",params:{message:{role:"user",messageId:$id,parts:[{kind:"text",text:$m}]}}}')"
resp="$(curl -sS --max-time 600 -w '\n%{http_code}' "${GW_URL}/a2a/claims-agent/" "${headers[@]}" -d "${body}")"
code="$(tail -1 <<<"${resp}")"; resp="$(sed '$d' <<<"${resp}")"
if [[ "${code}" != "200" ]]; then
  blocked "HTTP ${code}: ${resp}"
  exit 1
fi
jq -r '
  (.result.artifacts // [] | map(.parts[]?.text // empty) | join("\n")) as $a
  | (.result.status.message.parts // [] | map(.text // empty) | join("\n")) as $s
  | if .error then "ERROR: \(.error.message)" elif ($a|length) > 0 then $a else $s end' <<<"${resp}" | sed 's/^/   | /'

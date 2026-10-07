#!/usr/bin/env bash
# Scene 5: a looping agent trips the per-member token rate limit.
# Replays what a stuck agent does: re-send the whole case file to the model
# over and over, several calls at a time, on behalf of one member.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
port_forward_gateway
tok="$(agent_delegated_token "${MEMBER_USER:-reader}")"
PAR="${PAR:-6}"

casefile="$(jq -c '{members: ., note: "re-check"}' "${DEMO_ROOT}/mcp/data/members.json")"
photos="$(jq -c '.[0]' "${DEMO_ROOT}/mcp/data/submissions.json")"
body="$(jq -n --arg m "${casefile}" --arg p "${photos}" '{model:"claims-assistant",max_tokens:200,messages:[
  {role:"system",content:"You are the auto-claims intake assistant."},
  {role:"user",content:("Re-check this estimate against the policy one more time. Reply in one sentence.\nCASE FILE: " + $m + "\nSUBMISSION: " + $p + "\nPREVIOUS CASE FILE: " + $m + "\nPREVIOUS SUBMISSION: " + $p + "\nOLDER CASE FILE: " + $m + "\nOLDEST CASE FILE: " + $m)}]}')"

call() {
  curl -s --max-time 60 -o /dev/null -w '%{http_code}' "${GW_URL}/v1/chat/completions" \
    -H "Authorization: Bearer ${tok}" -H 'content-type: application/json' -d "${body}"
}

say "An agent stuck in a 're-check the estimate' loop for one member, ${PAR} calls at a time:"
for round in $(seq 1 "${MAX_ROUNDS:-10}"); do
  codes=(); pids=()
  for i in $(seq 1 "${PAR}"); do call > "${TMPDIR:-/tmp}/runaway.$$.$i" & pids+=("$!"); done
  wait "${pids[@]}"
  for i in $(seq 1 "${PAR}"); do codes+=("$(cat "${TMPDIR:-/tmp}/runaway.$$.$i")"); rm -f "${TMPDIR:-/tmp}/runaway.$$.$i"; done
  printf '   round %2d: %s\n' "${round}" "${codes[*]}"
  if [[ " ${codes[*]} " == *" 429 "* ]]; then
    blocked "per-member token limit reached: the gateway is returning 429 to this member's agent"
    break
  fi
done

say "The limit is per member: another member's claims keep flowing"
code="$(curl -s -o /dev/null -w '%{http_code}' "${GW_URL}/v1/chat/completions" \
  -H "Authorization: Bearer $(agent_delegated_token "${ADJUSTER_USER:-writer}")" \
  -H 'content-type: application/json' -d '{"model":"claims-assistant","max_tokens":20,"messages":[{"role":"user","content":"Reply with OK."}]}')"
[[ "${code}" == "200" ]] && ok "${ADJUSTER_USER:-writer}: HTTP ${code}" || warn "${ADJUSTER_USER:-writer}: HTTP ${code}"

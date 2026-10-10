#!/usr/bin/env bash
#
# router-parking.sh -- view or change request parking on the agentgateway router.
#
# Usage:
#   ./scripts/router-parking.sh status          # requestParking config + live parked gauge
#   ./scripts/router-parking.sh default         # agentgateway defaults (5s budget, 1024 slots)
#   ./scripts/router-parking.sh off             # requestParking.max: 0 (no parking)
#   ./scripts/router-parking.sh budget <secs>   # requestParking.budget: <secs>s
#
# Requires Substrate installed with --atenet-dataplane=agentgateway. In that
# mode the atenet-router Deployment runs agentgateway, and actor resume (and
# request parking) is agentgateway's substrateIngress route policy, configured
# in the ConfigMap ate-system/atenet-router-agentgateway-config.
#
# All four routes in that config share one substrateIngress block through the
# YAML anchor &substrate-ingress, so the script edits the anchored block once
# (with yq) and every route picks it up. `default` removes requestParking, which
# restores agentgateway's built-in defaults.
#
# After writing the ConfigMap the script restarts the router. agentgateway does
# watch its config file, but the kubelet can take a minute or more to sync a
# ConfigMap change into the pod; a restart makes the new value certain. The
# restart drops any request parked at that moment (this overlay drains for
# about 5s), so change settings between load runs, not during one.
#
# Re-running the Substrate installer resets the ConfigMap.

set -euo pipefail

NS="ate-system"
DEPLOY="atenet-router"
CM="atenet-router-agentgateway-config"
KEY="config.yaml"
ANCHOR="substrate-ingress"
STATS_PORT="${ROUTER_STATS_LOCAL_PORT:-15020}"

usage() {
  sed -n '3,27p' "$0" | sed 's/^# \{0,1\}//'
}

preflight() {
  if ! yq --version 2>/dev/null | grep -q mikefarah; then
    echo "needs mikefarah yq v4 (https://github.com/mikefarah/yq), found: $(yq --version 2>&1 || echo none)" >&2
    exit 1
  fi
  local containers
  containers=$(kubectl -n "${NS}" get deployment "${DEPLOY}" \
    -o jsonpath='{.spec.template.spec.containers[*].name}')
  if [[ " ${containers} " != *" agentgateway "* ]]; then
    echo "${NS}/${DEPLOY} runs [${containers}], not agentgateway." >&2
    echo "Install Substrate with --atenet-dataplane=agentgateway (see README Prerequisites)." >&2
    exit 1
  fi
}

current_config() {
  kubectl -n "${NS}" get configmap "${CM}" -o json | jq -er --arg k "${KEY}" '.data[$k]'
}

show_status() {
  local cfg parking
  cfg=$(current_config)
  parking=$(yq "(.. | select(anchor == \"${ANCHOR}\")).substrateIngress.requestParking // {}" -o json -I0 <<<"${cfg}")
  echo "==> requestParking in ${NS}/${CM} ({} = agentgateway defaults)"
  echo "    set:       ${parking}"
  jq -r '"    effective: budget=\(.budget // "5s") max=\(.max // 1024) retryInterval=\(.retryInterval // "100ms") retryFactor=\(.retryFactor // 1.1)"
         + (if (.max // 1024) == 0 then "  (parking OFF: resume gets a fixed 15s timeout, no retries on a full pool)" else "" end)' \
    <<<"${parking}"

  echo "==> live gauge from the router's stats port (:15020/metrics)"
  kubectl -n "${NS}" port-forward "deployment/${DEPLOY}" "${STATS_PORT}:15020" >/dev/null 2>&1 &
  local pf=$!
  local out=""
  for _ in $(seq 1 20); do
    if out=$(curl -sf -m 2 "http://localhost:${STATS_PORT}/metrics" 2>/dev/null) && [[ -n "${out}" ]]; then
      break
    fi
    sleep 0.5
  done
  kill "${pf}" 2>/dev/null || true
  if [[ -n "${out}" ]]; then
    grep -E '^agentgateway_substrate_request_parking_active ' <<<"${out}" | sed 's/^/    /' \
      || echo "    agentgateway_substrate_request_parking_active not exported yet"
  else
    echo "    could not reach :15020/metrics" >&2
  fi
}

# $1: yq expression applied to the router config
apply_config() {
  local expr="$1" cfg new anchors
  cfg=$(current_config)
  anchors=$(yq "[.. | select(anchor == \"${ANCHOR}\")] | length" <<<"${cfg}")
  if [[ "${anchors}" != "1" ]]; then
    echo "expected exactly one &${ANCHOR} block in ${CM}, found ${anchors}; refusing to edit" >&2
    exit 1
  fi
  new=$(yq "${expr}" <<<"${cfg}")
  kubectl -n "${NS}" get configmap "${CM}" -o json \
    | jq --arg k "${KEY}" --arg v "${new}" '.data[$k] = $v | del(.metadata.managedFields)' \
    | kubectl replace -f -
  kubectl -n "${NS}" rollout restart "deployment/${DEPLOY}"
  kubectl -n "${NS}" rollout status "deployment/${DEPLOY}" --timeout=300s
  show_status
}

set_parking() {
  apply_config "(.. | select(anchor == \"${ANCHOR}\")).substrateIngress.requestParking = $1"
}

cmd="${1:-}"
case "${cmd}" in
  status)
    preflight
    show_status
    ;;
  default)
    preflight
    apply_config "del((.. | select(anchor == \"${ANCHOR}\")).substrateIngress.requestParking)"
    ;;
  off)
    preflight
    set_parking '{"max": 0}'
    ;;
  budget)
    secs="${2:-}"
    if ! [[ "${secs}" =~ ^[0-9]+$ ]] || [[ "${secs}" -lt 1 ]]; then
      echo "budget needs a whole number of seconds, e.g. budget 90" >&2
      exit 2
    fi
    preflight
    set_parking "{\"budget\": \"${secs}s\"}"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

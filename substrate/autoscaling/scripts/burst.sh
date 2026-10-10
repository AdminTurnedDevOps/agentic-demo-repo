#!/usr/bin/env bash
#
# burst.sh -- load generator for the "Burst Without 503s" lab.
#
# Runs one concurrent loop per actor against the atenet router (agentgateway
# dataplane) and tallies the HTTP outcome of every request. While it runs it
# prints a live line every 5 seconds with the WorkerPool size, so you can watch
# the pool grow and the failures stop.
#
# What agentgateway's failure codes mean here:
#   504  a parked request's budget ran out before a worker freed up
#   429  the pool was full and parking is off (ResourceExhausted)
#   503  parking lot full, a transient resume state, or a stale cached
#        assignment that could not be re-resolved in time
#
# Two modes:
#   churn  request -> kubectl ate suspend -> repeat. Actors keep giving their
#          worker back, so the pool is saturated only for moments. This is the
#          case request parking is built for.
#   hold   request -> pause -> repeat, never suspending. Actors stay hot and
#          keep their worker, so demand is sustained. Parking alone can't fix
#          this; only more workers can.
#
# By default the script opens its own port-forward to svc/atenet-router and
# closes it on exit, so a router rollout between runs never leaves you with a
# stale forward. Pass -r to use a router URL you manage yourself.
#
# Usage:
#   ./scripts/burst.sh [-m churn|hold] [-d secs] [-i secs] [-a atespace]
#                      [-n namespace] [-p pool] [-r router_url] [actor ...]
#
# Examples:
#   ./scripts/burst.sh -m churn -d 30          # actors a1..a6, 30s
#   ./scripts/burst.sh -m hold -d 120 a1 a2 a3 a4 a5 a6
#
# Prerequisites: kubectl, the kubectl-ate plugin (churn mode), curl, awk.
# Works with the macOS system bash (3.2).

set -uo pipefail

MODE="hold"
DURATION=60
INTERVAL=1
ATESPACE="ate-lab-burst"
POOL_NAMESPACE="ate-lab-burst"
POOL="burst"
ROUTER=""
LOCAL_PORT="${BURST_LOCAL_PORT:-18080}"
TICK=5

usage() {
  sed -n '3,36p' "$0" | sed 's/^# \{0,1\}//'
}

while getopts ":m:d:i:a:n:p:r:h" opt; do
  case "${opt}" in
    m) MODE="${OPTARG}" ;;
    d) DURATION="${OPTARG}" ;;
    i) INTERVAL="${OPTARG}" ;;
    a) ATESPACE="${OPTARG}" ;;
    n) POOL_NAMESPACE="${OPTARG}" ;;
    p) POOL="${OPTARG}" ;;
    r) ROUTER="${OPTARG}" ;;
    h) usage; exit 0 ;;
    *) echo "unknown option -${OPTARG}; use -h for help" >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))

case "${MODE}" in
  churn|hold) ;;
  *) echo "mode must be churn or hold, got '${MODE}'" >&2; exit 2 ;;
esac

ACTORS=("$@")
if [[ ${#ACTORS[@]} -eq 0 ]]; then
  ACTORS=(a1 a2 a3 a4 a5 a6)
fi

TMP="$(mktemp -d)"
PF_PID=""
pids=()

cleanup() {
  if [[ ${#pids[@]} -gt 0 ]]; then
    kill "${pids[@]}" 2>/dev/null
  fi
  if [[ -n "${PF_PID}" ]]; then
    kill "${PF_PID}" 2>/dev/null
  fi
  rm -rf "${TMP}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# ---- router endpoint -------------------------------------------------------
if [[ -z "${ROUTER}" ]]; then
  ROUTER="http://localhost:${LOCAL_PORT}"
  kubectl -n ate-system port-forward svc/atenet-router "${LOCAL_PORT}:80" \
    >"${TMP}/port-forward.log" 2>&1 &
  PF_PID=$!
  # Poll until the forward accepts connections (any HTTP status counts).
  ready=0
  for _ in $(seq 1 40); do
    code=$(curl -s -o /dev/null -m 2 -w '%{http_code}' "${ROUTER}/" 2>/dev/null)
    if [[ "${code}" != "000" ]]; then
      ready=1
      break
    fi
    if ! kill -0 "${PF_PID}" 2>/dev/null; then
      break
    fi
    sleep 0.5
  done
  if [[ "${ready}" -ne 1 ]]; then
    echo "port-forward to svc/atenet-router did not come up:" >&2
    cat "${TMP}/port-forward.log" >&2
    exit 1
  fi
fi

pool_size() {
  kubectl -n "${POOL_NAMESPACE}" get workerpool "${POOL}" \
    -o jsonpath='{.spec.replicas}/{.status.readyReplicas}' 2>/dev/null || echo "?/?"
}

echo "==> burst: mode=${MODE} duration=${DURATION}s actors=${ACTORS[*]} (${#ACTORS[@]})"
echo "    router: ${ROUTER}   pool: ${POOL_NAMESPACE}/${POOL} (spec/ready = $(pool_size))"
echo

START=$(date +%s)
DEADLINE=$((START + DURATION))

# One loop per actor. Each response is logged as:
#   <epoch_when_done> <http_code> <time_total_seconds> <actor>
drive() {
  local actor="$1" log="${TMP}/$1.log" line
  while [[ $(date +%s) -lt ${DEADLINE} ]]; do
    # -m 180 is a client-side ceiling well above any park budget used in the
    # lab, so the router (not curl) decides when a parked request gives up.
    line=$(curl -s -o /dev/null -m 180 -w '%{http_code} %{time_total}' \
      -H "ate-target-actor: ${ATESPACE}/${actor}" "${ROUTER}/" 2>/dev/null)
    echo "$(date +%s) ${line:-000 0} ${actor}" >>"${log}"
    if [[ "${MODE}" == "churn" ]]; then
      # Give the worker back, standing in for an agent going idle.
      kubectl ate suspend actor "${actor}" --atespace "${ATESPACE}" >/dev/null 2>&1 || true
    else
      sleep "${INTERVAL}"
    fi
  done
}

for a in "${ACTORS[@]}"; do
  drive "${a}" &
  pids+=($!)
done

# ---- live ticker -----------------------------------------------------------
printf "    %-6s %-12s %-7s %-7s %-7s %-7s %-7s\n" "t" "pool s/r" "200" "429" "503" "504" "other"
last=${START}
while :; do
  alive=0
  for p in "${pids[@]}"; do
    if kill -0 "${p}" 2>/dev/null; then alive=1; break; fi
  done
  now=$(date +%s)
  if [[ $((now - last)) -ge ${TICK} || ${alive} -eq 0 ]]; then
    cat "${TMP}"/*.log 2>/dev/null | awk -v from="${last}" -v to="${now}" \
      -v t="$((now - START))s" -v pool="$(pool_size)" '
        $1 > from && $1 <= to { c[$2]++; n++ }
        END {
          other = n - c[200] - c[429] - c[503] - c[504]
          printf "    %-6s %-12s %-7d %-7d %-7d %-7d %-7d\n", t, pool, c[200], c[429], c[503], c[504], other
        }'
    last=${now}
  fi
  [[ ${alive} -eq 0 ]] && break
  sleep 1
done
wait 2>/dev/null
pids=()

# ---- summary ---------------------------------------------------------------
cat "${TMP}"/*.log 2>/dev/null >"${TMP}/all.txt" || true
total=$(wc -l <"${TMP}/all.txt" | tr -d ' ')
if [[ "${total}" -eq 0 ]]; then
  echo "no responses recorded; is the router reachable at ${ROUTER}?" >&2
  exit 1
fi

echo
echo "==> results (${MODE}, ${DURATION}s, pool now $(pool_size))"
awk -v start="${START}" '
  { n++; c[$2]++ }
  $2 == 200 { ok++; lat[ok] = $3; sum += $3; if ($3 > 1) slow++ }
  $2 != 200 { fail++; t = $1 - start; if (first == "") first = t; last = t }
  $2 != 200 && $2 != 429 && $2 != 503 && $2 != 504 { other++; codes[$2]++ }
  END {
    printf "    total requests : %d\n", n
    printf "    200 OK         : %d\n", c[200]
    printf "    504            : %d   <- park budget ran out\n", c[504]
    printf "    429            : %d   <- pool full, parking off\n", c[429]
    printf "    503            : %d   <- parking lot full / transient / stale assignment\n", c[503]
    printf "    other          : %d", other
    for (k in codes) printf "  [%s x%d]", k, codes[k]
    printf "\n"
    if (ok > 0) {
      # simple insertion sort; request counts in this lab are small
      for (i = 2; i <= ok; i++) { v = lat[i]; j = i - 1; while (j > 0 && lat[j] > v) { lat[j+1] = lat[j]; j-- } lat[j+1] = v }
      p50 = lat[int((ok - 1) * 0.50) + 1]; p95 = lat[int((ok - 1) * 0.95) + 1]
      printf "    200 latency    : avg %.3fs  p50 %.3fs  p95 %.3fs  max %.3fs\n", sum / ok, p50, p95, lat[ok]
      printf "    200s over 1s   : %d   <- requests that waited (parked) before being served\n", slow
    }
    if (fail > 0) printf "    failure window : first at t=%ds, last at t=%ds\n", first, last
  }' "${TMP}/all.txt"

fail=$(awk '$2 != 200' "${TMP}/all.txt" | wc -l | tr -d ' ')
echo
if [[ "${fail}" -eq 0 ]]; then
  echo "    => 0 failures: every request was served."
else
  echo "    => ${fail} failed requests (see the code breakdown above)."
fi

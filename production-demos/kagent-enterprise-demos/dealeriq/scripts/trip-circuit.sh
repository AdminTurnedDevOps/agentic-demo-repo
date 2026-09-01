#!/usr/bin/env bash
# Hit the mock LLM through dealeriq-llm until backend health eviction trips.
set -euo pipefail

NS=dealeriq
COUNT="${1:-8}"

for mock in dealeriq-mock-llm dealeriq-mock-llm-ok; do
  available="$(kubectl get deploy "${mock}" -n "${NS}" -o jsonpath='{.status.availableReplicas}' 2>/dev/null || true)"
  [[ "${available}" == "1" ]] || {
    echo "${mock} is not Available; run make deploy before this demo" >&2
    exit 1
  }
done

attached="$(kubectl get enterpriseagentgatewaypolicy dealeriq-mock-llm-circuit-breaker -n "${NS}" \
  -o jsonpath='{.status.ancestors[0].conditions[?(@.type=="Attached")].status}' 2>/dev/null || true)"
[[ "${attached}" == "True" ]] || {
  echo "circuit-breaker policy is not attached; apply gateway/circuit-breaker.yaml first" >&2
  exit 1
}

svc="$(kubectl get svc dealeriq-llm -n "${NS}" -o jsonpath='{.spec.clusterIP}')"
[[ -n "${svc}" ]] || { echo "dealeriq-llm Service not found" >&2; exit 1; }

echo "Driving ${COUNT} mock completions at ${svc}:8082/mock-llm"
echo "Expect 500 x3 then 200 after resetting gateway health state as documented in RUNBOOK.md."

kubectl run dealeriq-circuit -n "${NS}" --rm -i --restart=Never --image=curlimages/curl:8.11.1 -- \
  sh -c "
    i=1
    seen_500=0
    seen_200=0
    while [ \$i -le ${COUNT} ]; do
      line=\$(curl -sS -o /tmp/out -w '%{http_code} %{time_total}' -X POST http://${svc}:8082/mock-llm \
        -H 'Content-Type: application/json' \
        -d '{\"model\":\"mock-llm\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}]}' || true)
      snippet=\$(head -c 240 /tmp/out | tr '\\n' ' ')
      echo \"request \$i http \$line  \$snippet\"
      case \"\$line\" in
        500*) seen_500=1 ;;
        200*) seen_200=1 ;;
      esac
      i=\$((i+1))
    done
    if [ \$seen_500 -ne 1 ] || [ \$seen_200 -ne 1 ]; then
      echo 'Expected both failing (500) and healthy (200) providers. Reset gateway health state and retry.' >&2
      exit 1
    fi
  "

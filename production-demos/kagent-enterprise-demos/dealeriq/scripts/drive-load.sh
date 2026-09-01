#!/usr/bin/env bash
# Push lead-scoring completions through the demo LLM route until the daily token budget trips.
set -euo pipefail

NS=dealeriq
COUNT="${1:-12}"

svc="$(kubectl get svc dealeriq-llm -n "${NS}" -o jsonpath='{.spec.clusterIP}')"
[[ -n "${svc}" ]] || { echo "dealeriq-llm Service not found" >&2; exit 1; }

echo "Driving ${COUNT} completions at ${svc}:8082/anthropic"

kubectl run dealeriq-load -n "${NS}" --rm -i --restart=Never --image=curlimages/curl:8.11.1 -- \
  sh -c "
    set -e
    i=1
    ok=0
    while [ \$i -le ${COUNT} ]; do
      code=\$(curl -sS -o /tmp/out -w '%{http_code}' -X POST http://${svc}:8082/anthropic \
        -H 'Content-Type: application/json' \
        -d '{\"model\":\"claude-sonnet-4-6\",\"messages\":[{\"role\":\"user\",\"content\":\"Score inbound dealership lead 4127 in detail. Repeat the qualification rubric twice.\"}]}' || true)
      echo \"request \$i http \$code\"
      if [ \"\$code\" = \"200\" ]; then
        ok=\$((ok+1))
      fi
      if [ \"\$code\" = \"429\" ] || [ \"\$code\" = \"403\" ]; then
        if [ \"\$ok\" -ge 1 ]; then
          echo \"budget tripped after \$ok successful completion(s)\"
          exit 0
        fi
        echo '429 before any 200; leftover counter or rate limit. continuing'
      fi
      i=\$((i+1))
    done
    if [ \"\$ok\" -ge 1 ]; then
      echo \"finished \$ok 200s without a later 429; lower the budget or increase COUNT\"
    else
      echo 'no 200s; leftover Redis counter or the route is blocked. run ./scripts/reset-budget-counter.sh'
    fi
    exit 1
  "

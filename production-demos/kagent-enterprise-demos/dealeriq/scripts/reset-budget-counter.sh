#!/usr/bin/env bash
# Budget usage lives in the shared agentgateway rate-limiter Redis, keyed by
# budget id. Deleting the EnterpriseAgentgatewayBudget CR does not reset that
# counter, so Demo 4 would 429 on request 1 with the dashboard still at 0%.
# Only keys containing dealeriq-daily-token-budget are removed.
set -euo pipefail

CACHE_NS=agentgateway-system
CACHE_DEPLOY=ext-cache-enterprise-agentgateway
PATTERN='*dealeriq-daily-token-budget*'

if ! kubectl get deploy "${CACHE_DEPLOY}" -n "${CACHE_NS}" >/dev/null 2>&1; then
  echo "skip budget counter reset: ${CACHE_NS}/${CACHE_DEPLOY} not found"
  exit 0
fi

kubectl exec -n "${CACHE_NS}" "deploy/${CACHE_DEPLOY}" -- \
  sh -c "redis-cli --scan --pattern '${PATTERN}' | while IFS= read -r k; do
    [ -n \"\$k\" ] || continue
    redis-cli DEL \"\$k\" >/dev/null
    echo \"deleted \$k\"
  done"
echo "budget counter reset"

#!/usr/bin/env bash
# Delete kagent chat sessions for the DealerIQ agents. Does not delete Agent CRs or CRDs.
set -euo pipefail

NS="${NS:-dealeriq}"
CTRL="http://kagent-controller.kagent.svc.cluster.local:8083"
AGENTS=(dealer-assistant dealer-assistant-byo)
USERS=(reader writer admin)

delete_sessions_for_user() {
  local user="$1"
  local body
  body="$(kubectl run "dealeriq-sess-${user}-$$" -n "${NS}" --rm -i --restart=Never --image=curlimages/curl:8.11.1 -- \
    curl -sS --max-time 15 -H "X-User-ID: ${user}" "${CTRL}/api/sessions" 2>/dev/null || true)"
  [[ -n "${body}" ]] || return 0
  echo "${body}" | python3 -c '
import json,sys,os
ns=os.environ.get("NS","dealeriq")
want={"dealer-assistant","dealer-assistant-byo", f"{ns}/dealer-assistant", f"{ns}/dealer-assistant-byo",
      "dealer_assistant","dealer_assistant_byo"}
try:
    data=json.load(sys.stdin)
except Exception:
    sys.exit(0)
items=data.get("data") or data.get("items") or data
if isinstance(items, dict):
    items=items.get("sessions") or items.get("data") or []
if not isinstance(items, list):
    sys.exit(0)
for s in items:
    if not isinstance(s, dict):
        continue
    blob=" ".join(str(s.get(k,"")) for k in ("agent_id","agentId","agent_ref","agentRef","name","id"))
    if not any(w in blob for w in want):
        continue
    sid=s.get("id") or s.get("name") or s.get("session_id")
    if sid:
        print(sid)
' 2>/dev/null | while read -r sid; do
    [[ -n "${sid}" ]] || continue
    echo "deleting session ${sid} user=${user}"
    kubectl run "dealeriq-delsess-$$" -n "${NS}" --rm -i --restart=Never --image=curlimages/curl:8.11.1 -- \
      curl -sS --max-time 15 -X DELETE -H "X-User-ID: ${user}" "${CTRL}/api/sessions/${sid}" >/dev/null || true
  done
}

for user in "${USERS[@]}"; do
  delete_sessions_for_user "${user}" || true
done

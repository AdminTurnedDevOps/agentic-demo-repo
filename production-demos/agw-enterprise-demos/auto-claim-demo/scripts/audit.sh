#!/usr/bin/env bash
# Scene 6: pull the audit record from the gateway's structured access log.
#   audit.sh --submission SUB-2042     the whole agent run that touched SUB-2042
#   audit.sh --member reader|writer|<sub>
#   audit.sh --denials                 only rejected calls
#   audit.sh --summary                 per-member counts
#   audit.sh --status 401 | --args | --all | --last N
# SINCE=10m limits how far back to read (default 3h).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
[[ -f "${GEN_DIR}/personas.env" ]] && { set -a; source "${GEN_DIR}/personas.env"; set +a; }

kubectl -n "${NS}" logs "$(gateway_pod)" --since="${SINCE:-3h}" 2>/dev/null \
  | python3 "${DEMO_ROOT}/scripts/audit_view.py" --reader "${READER_SUB:-}" --writer "${WRITER_SUB:-}" "$@"

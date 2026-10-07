#!/usr/bin/env bash
# Shared helpers for the auto-claim demo scripts. Source, don't execute.

DEMO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS="${NS:-auto-claims}"
AGW_NS="${AGW_NS:-agentgateway-system}"
GEN_DIR="${DEMO_ROOT}/.generated"

# Credentials live outside the repo (chmod 600). See README "Credentials".
DEMO_ENV_FILE="${DEMO_ENV_FILE:-${HOME}/.config/auto-claim-demo/env}"
if [[ -f "${DEMO_ENV_FILE}" ]]; then set -a; source "${DEMO_ENV_FILE}"; set +a; fi
AGENT_SA="${AGENT_SA:-claims-agent}"

GW_LOCAL_PORT="${GW_LOCAL_PORT:-18080}"
STS_LOCAL_PORT="${STS_LOCAL_PORT:-17777}"
GW_URL="http://127.0.0.1:${GW_LOCAL_PORT}"
STS_URL="http://127.0.0.1:${STS_LOCAL_PORT}"

KEYCLOAK_REALM_URL="${KEYCLOAK_REALM_URL:-}"   # e.g. https://keycloak.example.com/realms/kagent-dev
KEYCLOAK_CLIENT_ID="${KEYCLOAK_CLIENT_ID:-kagent-ui}"

c_red=$'\033[31m'; c_green=$'\033[32m'; c_yellow=$'\033[33m'; c_bold=$'\033[1m'; c_off=$'\033[0m'

say()   { printf '%s\n' "${c_bold}$*${c_off}"; }
ok()    { printf '%s\n' "${c_green}OK${c_off}   $*"; }
warn()  { printf '%s\n' "${c_yellow}WARN${c_off} $*"; }
fail()  { printf '%s\n' "${c_red}FAIL${c_off} $*" >&2; exit 1; }
blocked() { printf '%s\n' "${c_red}BLOCKED${c_off} $*"; }

require_cmd() {
  for c in "$@"; do command -v "$c" >/dev/null 2>&1 || fail "missing required command: $c"; done
}

# Poll a URL until it answers (any HTTP status) or give up.
wait_for_http() {
  local url="$1" tries="${2:-50}"
  for _ in $(seq 1 "${tries}"); do
    if curl -s -o /dev/null --max-time 1 "${url}"; then return 0; fi
    sleep 0.2
  done
  return 1
}

_PF_PIDS=()
cleanup_port_forwards() {
  for pid in "${_PF_PIDS[@]:-}"; do [[ -n "${pid}" ]] && kill "${pid}" 2>/dev/null || true; done
}
trap cleanup_port_forwards EXIT

port_forward_gateway() {
  if curl -s -o /dev/null --max-time 1 "${GW_URL}/"; then return 0; fi
  kubectl -n "${NS}" port-forward svc/claims-gateway "${GW_LOCAL_PORT}:8080" >/dev/null 2>&1 &
  _PF_PIDS+=("$!")
  wait_for_http "${GW_URL}/" || fail "port-forward to claims-gateway did not come up"
}

port_forward_sts() {
  if curl -s -o /dev/null --max-time 1 "${STS_URL}/health"; then return 0; fi
  kubectl -n "${AGW_NS}" port-forward svc/enterprise-agentgateway "${STS_LOCAL_PORT}:7777" >/dev/null 2>&1 &
  _PF_PIDS+=("$!")
  wait_for_http "${STS_URL}/health" || fail "port-forward to the STS (enterprise-agentgateway:7777) did not come up"
}

# Per-user password (READER_PASSWORD / WRITER_PASSWORD), else CLAIMS_DEMO_PASSWORD.
demo_password() {
  local var pw
  var="$(printf '%s' "${1:-}" | tr '[:lower:]' '[:upper:]')_PASSWORD"
  pw="${!var:-${CLAIMS_DEMO_PASSWORD:-${DEALERIQ_PASSWORD:-}}}"
  [[ -n "${pw}" ]] || fail "set ${var} or CLAIMS_DEMO_PASSWORD in ${DEMO_ENV_FILE}"
  printf '%s' "${pw}"
}

# Keycloak access token for a kagent-dev realm user (reader | writer).
keycloak_token() {
  local user="$1" resp token
  [[ -n "${KEYCLOAK_REALM_URL}" ]] || fail "set KEYCLOAK_REALM_URL in ${DEMO_ENV_FILE}"
  resp="$(curl -sS -X POST "${KEYCLOAK_REALM_URL}/protocol/openid-connect/token" \
    -d "client_id=${KEYCLOAK_CLIENT_ID}" -d "username=${user}" \
    --data-urlencode "password=$(demo_password "${user}")" -d "grant_type=password")"
  token="$(jq -r '.access_token // empty' <<<"${resp}")"
  [[ -n "${token}" ]] || { jq -c '{error,error_description}' <<<"${resp}" >&2; fail "Keycloak login failed for ${user}"; }
  printf '%s' "${token}"
}

# Reproduce exactly what claims-agent does before a tool call: exchange the
# member's token (subject) plus the agent's ServiceAccount token (actor) at the
# agentgateway STS. Prints the delegated token.
agent_delegated_token() {
  local user="$1" subject actor resp token
  subject="$(keycloak_token "${user}")"
  actor="$(kubectl -n "${NS}" create token "${AGENT_SA}" --duration=10m)"
  port_forward_sts
  resp="$(curl -sS -X POST "${STS_URL}/oauth2/token" \
    -d grant_type=urn:ietf:params:oauth:grant-type:token-exchange \
    -d subject_token_type=urn:ietf:params:oauth:token-type:jwt \
    -d actor_token_type=urn:ietf:params:oauth:token-type:jwt \
    --data-urlencode "subject_token=${subject}" \
    --data-urlencode "actor_token=${actor}")"
  token="$(jq -r '.access_token // empty' <<<"${resp}")"
  [[ -n "${token}" ]] || { echo "${resp}" >&2; fail "STS exchange failed for ${user}"; }
  printf '%s' "${token}"
}

jwt_claims() {
  python3 -c 'import sys,json,base64; p=sys.argv[1].split(".")[1]; p+="="*(-len(p)%4); print(json.dumps(json.loads(base64.urlsafe_b64decode(p)),indent=2))' "$1"
}

gateway_pod() {
  kubectl -n "${NS}" get pods -l gateway.networking.k8s.io/gateway-name=claims-gateway \
    -o jsonpath='{.items[0].metadata.name}'
}

mcp() { python3 "${DEMO_ROOT}/scripts/mcp_client.py" --url "${GW_URL}/mcp" "$@"; }

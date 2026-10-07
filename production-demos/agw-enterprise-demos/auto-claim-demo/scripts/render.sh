#!/usr/bin/env bash
# Renders manifests/*.tmpl into .generated/manifests with values from env and
# .generated/personas.env. Fails on any unresolved ${VAR}.
set -uo pipefail
source "$(dirname "$0")/lib.sh"

if [[ -f "${GEN_DIR}/personas.env" ]]; then
  set -a; source "${GEN_DIR}/personas.env"; set +a
else
  warn "no ${GEN_DIR}/personas.env yet (make personas); the tool registry will not render"
fi

export MCP_TAG="${MCP_TAG:-0.1.2}"
[[ -n "${REGISTRY:-}" && -z "${MCP_IMAGE:-}" ]] && export MCP_IMAGE="${REGISTRY}/auto-claims-mcp:${MCP_TAG}"
# Leave unset values unset so their templates are reported, not rendered with blanks.
for v in MCP_IMAGE KEYCLOAK_REALM_URL BEDROCK_MODEL BEDROCK_REGION BEDROCK_GUARDRAIL_ID BEDROCK_GUARDRAIL_VERSION; do
  if [[ -n "${!v:-}" ]]; then export "${v}"; else unset "${v}"; fi
done
[[ -n "${MCP_IMAGE:-}" ]] || warn "REGISTRY is not set; the MCP server manifest will not render"
[[ -n "${KEYCLOAK_REALM_URL:-}" ]] || warn "KEYCLOAK_REALM_URL is not set; the identity policy and STS values will not render"
export OPENAI_MODEL="${OPENAI_MODEL:-gpt-4.1-mini}"

out="${GEN_DIR}/manifests"
rm -rf "${GEN_DIR}/manifests" "${GEN_DIR}/platform"; mkdir -p "${out}/policies" "${out}/scenes" "${GEN_DIR}/platform"
( cd "${DEMO_ROOT}" && find manifests platform -name '*.tmpl' ) | while read -r rel; do
  src="${DEMO_ROOT}/${rel}"
  dst="${GEN_DIR}/${rel%.tmpl}"
  python3 - "${src}" "${dst}" <<'PY'
import os, re, string, sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src).read()
rendered = string.Template(text).safe_substitute(os.environ)
left = sorted(set(re.findall(r"\$\{([A-Z_]+)\}", rendered)))
if left:
    print(f"SKIP {src}: unresolved variables: {', '.join(left)}")
    sys.exit(3)
open(dst, "w").write(rendered)
PY
  rc=$?
  [[ ${rc} -eq 0 ]] && ok "rendered ${rel%.tmpl}" || [[ ${rc} -eq 3 ]] || fail "render failed for ${rel}"
done

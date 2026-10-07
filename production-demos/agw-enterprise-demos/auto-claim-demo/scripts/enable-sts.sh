#!/usr/bin/env bash
# Turns on the agentgateway token-exchange STS in the EXISTING enterprise
# agentgateway release. Shows the values diff and the rendered-manifest diff,
# then asks before running helm upgrade. Uses --reuse-values so the license and
# every other existing value are kept.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_cmd helm kubectl diff

RELEASE="${AGW_RELEASE:-agentgateway}"
CHART="${AGW_CHART:-oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway}"
VALUES="${GEN_DIR}/platform/sts-values.yaml"
[[ -f "${VALUES}" ]] || fail "run make render first (it renders platform/sts-values.yaml.tmpl)"

chart_ver="$(helm -n "${AGW_NS}" list -f "^${RELEASE}$" -o json | jq -r '.[0].chart' | sed 's/^enterprise-agentgateway-//')"
[[ -n "${chart_ver}" && "${chart_ver}" != "null" ]] || fail "helm release ${RELEASE} not found in ${AGW_NS}"
say "Release ${AGW_NS}/${RELEASE}, chart version ${chart_ver} (version is kept)"

tmp="$(mktemp -d)"; trap 'rm -rf "${tmp}"; cleanup_port_forwards' EXIT
helm -n "${AGW_NS}" get values "${RELEASE}" -o yaml > "${tmp}/current-values.yaml"
helm -n "${AGW_NS}" get manifest "${RELEASE}" > "${tmp}/current.yaml"
helm template "${RELEASE}" "${CHART}" --version "${chart_ver}" -n "${AGW_NS}" \
  -f "${tmp}/current-values.yaml" -f "${VALUES}" > "${tmp}/proposed.yaml"

say "Values added:"
cat "${VALUES}"
say "Rendered manifest diff (current -> proposed). Secret data is not shown by helm get manifest/template diff of values above:"
diff -u "${tmp}/current.yaml" "${tmp}/proposed.yaml" | grep -v -i -E 'licenseKey|license-key:' || true

if [[ "${YES:-}" != "1" ]]; then
  read -r -p "Apply this helm upgrade to ${AGW_NS}/${RELEASE}? Type 'yes' to continue: " answer
  [[ "${answer}" == "yes" ]] || fail "aborted, nothing changed"
fi

helm upgrade "${RELEASE}" "${CHART}" --version "${chart_ver}" -n "${AGW_NS}" --reuse-values -f "${VALUES}"
kubectl -n "${AGW_NS}" rollout status deploy/enterprise-agentgateway --timeout=180s

port_forward_sts
issuer="$(curl -fsS "${STS_URL}/.well-known/oauth-authorization-server" | jq -r .issuer)"
ok "STS is up, issuer ${issuer}"

#!/usr/bin/env bash
# Resolves the Keycloak subject IDs of the demo personas. The tool registry
# grants open_claim to adjuster-tier subjects only.
#   reader -> member-services tier (read tools only)
#   writer -> adjuster tier (read tools + open_claim)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
mkdir -p "${GEN_DIR}"

sub_of() { jwt_claims "$(keycloak_token "$1")" | jq -r .sub; }
reader_sub="$(sub_of reader)"
writer_sub="$(sub_of writer)"
cat > "${GEN_DIR}/personas.env" <<ENV
READER_SUB=${reader_sub}
WRITER_SUB=${writer_sub}
ADJUSTER_SUBS='["${writer_sub}"]'
ENV
ok "reader (member-services tier) sub=${reader_sub}"
ok "writer (adjuster tier)        sub=${writer_sub}"
ok "wrote ${GEN_DIR}/personas.env"

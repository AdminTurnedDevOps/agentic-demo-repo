#!/usr/bin/env bash
# Builds and pushes the auto-claims MCP server image to ${REGISTRY}.
# With GCP_PROJECT set it uses Cloud Build (no local Docker needed);
# otherwise it uses docker buildx (linux/amd64 + linux/arm64).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
: "${REGISTRY:?set REGISTRY in ${DEMO_ENV_FILE} (e.g. ghcr.io/you or us-docker.pkg.dev/project/repo)}"
IMAGE="${REGISTRY}/auto-claims-mcp:${MCP_TAG:-0.1.2}"
if [[ -n "${GCP_PROJECT:-}" ]]; then
  gcloud builds submit "${DEMO_ROOT}/mcp" --project="${GCP_PROJECT}" --tag "${IMAGE}"
else
  docker buildx build --platform linux/amd64,linux/arm64 -t "${IMAGE}" --push "${DEMO_ROOT}/mcp"
fi
ok "pushed ${IMAGE}"

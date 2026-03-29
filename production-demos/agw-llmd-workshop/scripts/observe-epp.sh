#!/bin/bash
# observe-epp.sh — Stream llm-d EPP (Endpoint Picker) logs in real-time.
#
# The EPP makes all routing decisions for the InferencePool. Its logs show:
#   - Which vLLM pod was selected for each request
#   - Whether a prefix-cache hit occurred
#   - Queue depth at each candidate endpoint
#   - Scoring rationale for endpoint selection
#
# Run this in one terminal, then send requests in another terminal to
# watch routing decisions as they happen.
#
# Usage: bash scripts/observe-epp.sh

set -e

NAMESPACE="llmd-workshop"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   llm-d EPP (Endpoint Picker) Log Observer                  ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"

# Find EPP pod
echo -e "\n${GREEN}Finding EPP pod...${NC}"
EPP_POD=$(kubectl get pods -n "$NAMESPACE" -l app=llmd-pool-endpoint-picker -o name 2>/dev/null | head -1)

if [ -z "$EPP_POD" ]; then
    # Try alternative label patterns the InferencePool Helm chart may use
    EPP_POD=$(kubectl get pods -n "$NAMESPACE" -o name 2>/dev/null | grep -i "endpoint-picker\|epp" | head -1)
fi

if [ -z "$EPP_POD" ]; then
    echo -e "${RED}Error: Could not find EPP pod in namespace $NAMESPACE${NC}"
    echo -e "${YELLOW}Available pods:${NC}"
    kubectl get pods -n "$NAMESPACE" -o wide
    echo -e "\n${YELLOW}The EPP pod is created by the InferencePool Helm chart.${NC}"
    echo -e "${YELLOW}Check: helm list -n $NAMESPACE${NC}"
    exit 1
fi

echo -e "  ✓ Found: ${CYAN}${EPP_POD}${NC}"

echo -e "\n${GREEN}What to look for in the logs:${NC}"
echo -e "  ${CYAN}selected_endpoint${NC}   — Which pod was chosen for a request"
echo -e "  ${CYAN}prefix_cache_hit${NC}    — Whether KV cache was reused (true = faster)"
echo -e "  ${CYAN}queue_depth${NC}         — Pending requests at each endpoint"
echo -e "  ${CYAN}score${NC}               — EPP scoring for each candidate pod"

echo -e "\n${YELLOW}Streaming logs (Ctrl+C to stop)...${NC}"
echo -e "${BLUE}══════════════════════════════════════════════════════════════════${NC}\n"

# Stream EPP logs with follow
kubectl logs -f -n "$NAMESPACE" "$EPP_POD" --tail=50

#!/bin/bash
# test-cache-routing.sh — Demonstrate KV-cache-aware routing behavior.
#
# The llm-d EPP (Endpoint Picker) uses prefix-cache affinity to route
# requests with the same prompt prefix to the same vLLM pod. This avoids
# recomputing the KV cache for repeated or similar prompts.
#
# This script sends:
#   1. The SAME prompt 10 times (expect high affinity → same pod)
#   2. A DIFFERENT prompt 10 times (may route differently)
# Then compares the routing patterns.
#
# Usage: bash scripts/test-cache-routing.sh

set -e

NAMESPACE="llmd-workshop"
GATEWAY_NAME="llmd-inference-gateway"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   KV-Cache Aware Routing Demonstration                      ║${NC}"
echo -e "${BLUE}║   llm-d Endpoint Picker prefix-cache affinity test          ║${NC}"
echo -e "${BLUE}╚═════════════════════════════════════════════════════════════════╝${NC}"

# Prerequisites
for cmd in kubectl curl jq; do
    if ! command -v "$cmd" &> /dev/null; then
        echo -e "${RED}Error: $cmd is not installed${NC}"
        exit 1
    fi
done

# Get gateway address
IP=$(kubectl get gateway/"$GATEWAY_NAME" -n "$NAMESPACE" -o jsonpath='{.status.addresses[0].value}' 2>/dev/null)
if [ -z "$IP" ]; then
    echo -e "${RED}Error: Could not get gateway address${NC}"
    exit 1
fi
PORT=80
echo -e "\n${GREEN}Gateway: ${CYAN}${IP}:${PORT}${NC}"

send_request() {
    local prompt="$1"
    curl -s --max-time 120 "${IP}:${PORT}/v1/completions" \
        -H 'Content-Type: application/json' \
        -d "{
            \"model\": \"Qwen/Qwen2.5-0.5B-Instruct\",
            \"prompt\": \"$prompt\",
            \"max_tokens\": 20,
            \"temperature\": 0.1
        }" 2>/dev/null
}

# Phase 1: Same prompt repeated
PROMPT_A="Explain the architecture of Kubernetes in detail, including the control plane components and how they interact with worker nodes."
echo -e "\n${GREEN}Phase 1: Sending the SAME prompt 10 times${NC}"
echo -e "${YELLOW}Prompt: \"${PROMPT_A:0:60}...\"${NC}"
echo -e "${YELLOW}Expect: EPP routes to the same pod (prefix-cache hit)${NC}\n"

PHASE1_IDS=()
for i in $(seq 1 10); do
    RESPONSE=$(send_request "$PROMPT_A")
    if echo "$RESPONSE" | jq -e '.choices[0].text' &>/dev/null; then
        ID=$(echo "$RESPONSE" | jq -r '.id // "unknown"')
        PHASE1_IDS+=("$ID")
        echo -e "  ${GREEN}[${i}/10]${NC} ✓ id=${ID:0:30}..."
    else
        echo -e "  ${RED}[${i}/10]${NC} ✗ Failed"
    fi
done

# Phase 2: Different prompt
PROMPT_B="What are the best practices for deploying machine learning models in production? Discuss containerization, monitoring, and scaling strategies."
echo -e "\n${GREEN}Phase 2: Sending a DIFFERENT prompt 10 times${NC}"
echo -e "${YELLOW}Prompt: \"${PROMPT_B:0:60}...\"${NC}"
echo -e "${YELLOW}Expect: EPP may route to a different pod (different prefix)${NC}\n"

PHASE2_IDS=()
for i in $(seq 1 10); do
    RESPONSE=$(send_request "$PROMPT_B")
    if echo "$RESPONSE" | jq -e '.choices[0].text' &>/dev/null; then
        ID=$(echo "$RESPONSE" | jq -r '.id // "unknown"')
        PHASE2_IDS+=("$ID")
        echo -e "  ${GREEN}[${i}/10]${NC} ✓ id=${ID:0:30}..."
    else
        echo -e "  ${RED}[${i}/10]${NC} ✗ Failed"
    fi
done

# Analysis
echo -e "\n${BLUE}═════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Analysis${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"

echo -e "\n${YELLOW}To see the actual routing decisions, check the EPP logs:${NC}"
echo -e "  kubectl logs -n $NAMESPACE -l app=llmd-pool-endpoint-picker --tail=100"
echo -e ""
echo -e "${YELLOW}Look for these patterns in the EPP logs:${NC}"
echo -e "  - ${CYAN}prefix_cache_hit=true${NC}  → EPP found cached KV blocks, routed to same pod"
echo -e "  - ${CYAN}prefix_cache_hit=false${NC} → No cache hit, EPP used queue-depth scoring"
echo -e "  - ${CYAN}selected_endpoint${NC}      → Which pod was chosen and why"
echo -e ""
echo -e "${GREEN}What to observe:${NC}"
echo -e "  Phase 1 (same prompt): Most requests should hit the same pod"
echo -e "  Phase 2 (new prompt):  Routing may differ based on queue depth"
echo -e ""
echo -e "${YELLOW}Run this alongside observe-epp.sh for real-time routing visibility.${NC}"

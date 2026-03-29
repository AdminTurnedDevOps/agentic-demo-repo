#!/bin/bash
# test-inference.sh — Send repeated inference requests through the full stack
# and display which vLLM pod handled each request to demonstrate load distribution.
#
# Usage: bash scripts/test-inference.sh [NUM_REQUESTS]
# Default: 20 requests

set -e

NUM_REQUESTS=${1:-20}
NAMESPACE="llmd-workshop"
GATEWAY_NAME="llmd-inference-gateway"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}╔═════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   agentgateway + llm-d Inference Load Distribution Test     ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"

# Prerequisites check
echo -e "\n${GREEN}Checking prerequisites...${NC}"

check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}Error: $1 is not installed${NC}"
        exit 1
    fi
    echo -e "  ✓ $1"
}

check_command kubectl
check_command curl
check_command jq

# Verify pods are running
echo -e "\n${GREEN}Checking model server pods...${NC}"
READY_PODS=$(kubectl get pods -n "$NAMESPACE" -l app=llmd-model-server --field-selector=status.phase=Running -o name 2>/dev/null | wc -l | tr -d ' ')
if [ "$READY_PODS" -lt 1 ]; then
    echo -e "${RED}Error: No running model server pods found in namespace $NAMESPACE${NC}"
    echo -e "${YELLOW}Run: kubectl get pods -n $NAMESPACE -l app=llmd-model-server${NC}"
    exit 1
fi
echo -e "  ✓ $READY_PODS model server pod(s) running"

# Get gateway address
echo -e "\n${GREEN}Discovering gateway address...${NC}"
IP=$(kubectl get gateway/"$GATEWAY_NAME" -n "$NAMESPACE" -o jsonpath='{.status.addresses[0].value}' 2>/dev/null)
if [ -z "$IP" ]; then
    echo -e "${RED}Error: Could not get gateway address${NC}"
    echo -e "${YELLOW}Run: kubectl get gateway $GATEWAY_NAME -n $NAMESPACE -o yaml${NC}"
    exit 1
fi
PORT=80
echo -e "  ✓ Gateway address: ${CYAN}${IP}:${PORT}${NC}"

# Send requests
echo -e "\n${GREEN}Sending $NUM_REQUESTS inference requests...${NC}"
echo -e "${YELLOW}Each request asks the model a different question to vary routing.${NC}\n"

SUCCESS=0
FAIL=0
declare -A POD_COUNTS

PROMPTS=(
    "What is Kubernetes?"
    "Explain containers in one sentence."
    "What is a Pod?"
    "Define a Deployment."
    "What is a Service in Kubernetes?"
    "Explain namespaces."
    "What is Helm?"
    "Define infrastructure as code."
    "What is GitOps?"
    "Explain microservices."
    "What is a DaemonSet?"
    "Define a StatefulSet."
    "What is an Ingress?"
    "Explain the Gateway API."
    "What is a CRD?"
    "Define an operator pattern."
    "What is vLLM?"
    "Explain KV cache."
    "What is inference routing?"
    "Define load balancing."
)

for i in $(seq 1 "$NUM_REQUESTS"); do
    PROMPT_IDX=$(( (i - 1) % ${#PROMPTS[@]} ))
    PROMPT="${PROMPTS[$PROMPT_IDX]}"

    RESPONSE=$(curl -s --max-time 120 "${IP}:${PORT}/v1/completions" \
        -H 'Content-Type: application/json' \
        -d "{
            \"model\": \"Qwen/Qwen2.5-0.5B-Instruct\",
            \"prompt\": \"$PROMPT\",
            \"max_tokens\": 20,
            \"temperature\": 0.7
        }" 2>/dev/null)

    if echo "$RESPONSE" | jq -e '.choices[0].text' &>/dev/null; then
        MODEL=$(echo "$RESPONSE" | jq -r '.model // "unknown"')
        ID=$(echo "$RESPONSE" | jq -r '.id // "unknown"')
        TOKENS=$(echo "$RESPONSE" | jq -r '.usage.total_tokens // "?"')
        echo -e "  ${GREEN}[${i}/${NUM_REQUESTS}]${NC} ✓ model=${CYAN}${MODEL}${NC} tokens=${TOKENS} id=${ID:0:20}..."
        SUCCESS=$((SUCCESS + 1))
    else
        echo -e "  ${RED}[${i}/${NUM_REQUESTS}]${NC} ✗ Request failed"
        FAIL=$((FAIL + 1))
    fi
done

# Summary
echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Results:${NC}"
echo -e "  Total requests: $NUM_REQUESTS"
echo -e "  Successful:     ${GREEN}${SUCCESS}${NC}"
echo -e "  Failed:         ${RED}${FAIL}${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"

echo -e "\n${YELLOW}To see which pod handled each request, check the EPP logs:${NC}"
echo -e "  kubectl logs -n $NAMESPACE -l app=llmd-pool-endpoint-picker --tail=50"
echo -e "\n${YELLOW}Or run the observe script in another terminal:${NC}"
echo -e "  bash scripts/observe-epp.sh"

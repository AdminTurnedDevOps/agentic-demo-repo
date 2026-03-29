#!/bin/bash
# cleanup.sh — Tear down all workshop resources in reverse dependency order.
#
# This removes:
#   1. kagent Agent and ModelConfig
#   2. HTTPRoute and Gateway
#   3. InferenceModel
#   4. InferencePool Helm release (removes pool + EPP)
#   5. Model server Deployment and ConfigMap
#   6. Workshop namespace
#
# Optionally removes agentgateway, kagent, and CRDs (with confirmation).
#
# Usage: bash scripts/cleanup.sh

set -e

NAMESPACE="llmd-workshop"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFESTS_DIR="$SCRIPT_DIR/../manifests"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   agentgateway + llm-d Workshop Cleanup                     ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════╝${NC}"

# Step 1: Remove kagent resources
echo -e "\n${GREEN}Step 1: Removing kagent Agent and ModelConfig...${NC}"
kubectl delete -f "$MANIFESTS_DIR/05-kagent-config.yaml" --ignore-not-found 2>/dev/null || true
echo -e "  ✓ kagent resources removed"

# Step 2: Remove routing resources
echo -e "\n${GREEN}Step 2: Removing HTTPRoute and Gateway...${NC}"
kubectl delete -f "$MANIFESTS_DIR/04-gatewayhttproute.yaml" --ignore-not-found 2>/dev/null || true
echo -e "  ✓ Routing resources removed"

# Step 3: Remove InferenceObjective
echo -e "\n${GREEN}Step 3: Removing InferenceObjective...${NC}"
kubectl delete -f "$MANIFESTS_DIR/02-inference-objective.yaml" --ignore-not-found 2>/dev/null || true
echo -e "  ✓ InferenceObjective removed"

# Step 4: Uninstall InferencePool Helm release
echo -e "\n${GREEN}Step 4: Uninstalling InferencePool Helm release...${NC}"
helm uninstall llmd-pool -n "$NAMESPACE" 2>/dev/null || echo -e "  ${YELLOW}(not found or already removed)${NC}"
echo -e "  ✓ InferencePool Helm release removed"

# Step 5: Remove model server resources
echo -e "\n${GREEN}Step 5: Removing model server Deployment...${NC}"
kubectl delete -f "$MANIFESTS_DIR/01-model-server.yaml" --ignore-not-found 2>/dev/null || true
echo -e "  ✓ Model server resources removed"

# Step 6: Delete namespace
echo -e "\n${GREEN}Step 6: Deleting workshop namespace...${NC}"
kubectl delete -f "$MANIFESTS_DIR/00-namespace.yaml" --ignore-not-found 2>/dev/null || true
echo -e "  ✓ Namespace $NAMESPACE deleted"

echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Workshop resources cleaned up.${NC}"
echo -e "${BLUE}══════════════════════════════════════════════════════════════════${NC}"

# Optional: Remove infrastructure components
echo -e "\n${YELLOW}The following infrastructure components are still installed:${NC}"
echo -e "  - agentgateway (Helm release in agentgateway-system)"
echo -e "  - kagent (Helm release in kagent namespace)"
echo -e "  - Gateway API CRDs"
echo -e "  - Inference Extension CRDs"
echo -e ""
read -p "Remove agentgateway and kagent Helm releases? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "\n${GREEN}Removing agentgateway...${NC}"
    helm uninstall agentgateway -n agentgateway-system 2>/dev/null || true
    helm uninstall agentgateway-crds -n agentgateway-system 2>/dev/null || true
    kubectl delete namespace agentgateway-system --ignore-not-found 2>/dev/null || true

    echo -e "${GREEN}Removing kagent...${NC}"
    helm uninstall kagent -n kagent 2>/dev/null || true
    helm uninstall kagent-crds -n kagent 2>/dev/null || true
    kubectl delete namespace kagent --ignore-not-found 2>/dev/null || true

    echo -e "${GREEN}Removing CRDs...${NC}"
    kubectl delete -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v1.1.0/manifests.yaml --ignore-not-found 2>/dev/null || true
    kubectl delete -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.0/standard-install.yaml --ignore-not-found 2>/dev/null || true

    echo -e "\n${GREEN}All infrastructure components removed.${NC}"
else
    echo -e "\n${YELLOW}Infrastructure components left in place.${NC}"
    echo -e "${YELLOW}To remove them manually later:${NC}"
    echo -e "  helm uninstall agentgateway -n agentgateway-system"
    echo -e "  helm uninstall agentgateway-crds -n agentgateway-system"
    echo -e "  helm uninstall kagent -n kagent"
    echo -e "  helm uninstall kagent-crds -n kagent"
fi

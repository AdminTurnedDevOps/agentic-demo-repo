#!/bin/bash
# Cleanup script for Self-Healing Kubernetes Demo
# Removes all demo resources

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${YELLOW}║     Cleaning Up Self-Healing Demo                            ║${NC}"
echo -e "${YELLOW}╚══════════════════════════════════════════════════════════════╝${NC}"

# Ask for confirmation
read -p "This will delete all demo resources. Continue? [y/N]: " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# Delete demo namespace
echo -e "\n${GREEN}Deleting demo namespace...${NC}"
kubectl delete namespace demo --ignore-not-found

# Delete kagent resources (if present)
echo -e "\n${GREEN}Deleting kagent resources...${NC}"
kubectl delete cronjob health-check-trigger -n kagent --ignore-not-found 2>/dev/null || true
kubectl delete agent self-healing-agent -n kagent --ignore-not-found 2>/dev/null || true

# Delete alerting rules
echo -e "\n${GREEN}Deleting alerting rules...${NC}"
kubectl delete prometheusrule httpbin-alerts -n monitoring --ignore-not-found 2>/dev/null || true

# Optionally delete monitoring stack
read -p "Delete Prometheus stack? [y/N]: " delete_prom
if [[ "$delete_prom" =~ ^[Yy]$ ]]; then
    echo -e "\n${GREEN}Deleting Prometheus stack...${NC}"
    helm uninstall prometheus -n monitoring 2>/dev/null || true
    kubectl delete namespace monitoring --ignore-not-found
fi

# Optionally delete the kind cluster
read -p "Delete Kind cluster (self-healing-demo)? [y/N]: " delete_cluster
if [[ "$delete_cluster" =~ ^[Yy]$ ]]; then
    echo -e "\n${GREEN}Deleting Kind cluster...${NC}"
    kind delete cluster --name self-healing-demo 2>/dev/null || true
fi

echo -e "\n${GREEN}Cleanup complete!${NC}"

#!/bin/bash
# Master setup script for Self-Healing Kubernetes Demo
# Sets up the cluster, monitoring, and demo application

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Self-Healing Kubernetes Cluster Demo Setup               ║${NC}"
echo -e "${BLUE}║     Powered by kagent + agentgateway                         ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"

# Check prerequisites
echo -e "\n${GREEN}Checking prerequisites...${NC}"

check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}Error: $1 is not installed${NC}"
        exit 1
    fi
    echo -e "  ✓ $1"
}

check_command kubectl
check_command helm

# Step 1: Setup cluster (if needed)
echo -e "\n${GREEN}Step 1: Cluster Setup${NC}"
if kubectl cluster-info &> /dev/null; then
    echo "Kubernetes cluster is already accessible."
    kubectl cluster-info | head -2
else
    echo "No cluster found. Running cluster setup..."
    bash "$SCRIPT_DIR/cluster/setup-cluster.sh"
fi

# Step 2: Install Prometheus stack
echo -e "\n${GREEN}Step 2: Installing Prometheus Stack${NC}"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
helm repo update

kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -

helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
    --namespace monitoring \
    --values "$SCRIPT_DIR/monitoring/prometheus-values.yaml" \
    --wait \
    --timeout 5m

echo "Waiting for Prometheus to be ready..."
kubectl wait --for=condition=available --timeout=120s \
    deployment/prometheus-kube-prometheus-operator -n monitoring

# Step 3: Deploy demo application
echo -e "\n${GREEN}Step 3: Deploying Demo Application${NC}"
kubectl create namespace demo

kubectl apply -f "$SCRIPT_DIR/demo-app/httpbin.yaml"

# Step 4: Apply alerting rules
echo -e "\n${GREEN}Step 4: Applying Alerting Rules${NC}"
kubectl apply -f "$SCRIPT_DIR/monitoring/alerting-rules.yaml"

# Step 5: Make chaos scripts executable
echo -e "\n${GREEN}Step 5: Preparing Chaos Scripts${NC}"
chmod +x "$SCRIPT_DIR/chaos-scenarios/"*.sh

# Summary
echo -e "\n${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                    Setup Complete!                            ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Services:${NC}"
echo "  • Prometheus: http://localhost:9090"
echo "  • Grafana:    http://localhost:3000 (admin/prom-operator)"
echo "  • httpbin:    http://localhost:8080"
echo ""
echo -e "${BLUE}Cluster Status:${NC}"
kubectl get pods -n demo

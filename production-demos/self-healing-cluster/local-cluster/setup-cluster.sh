#!/bin/bash
# Setup script for Kind cluster
# Creates a local Kubernetes cluster for the self-healing demo

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER_NAME="self-healing-demo"

echo "=========================================="
echo "  Setting up Kind Cluster: $CLUSTER_NAME"
echo "=========================================="

# Check if kind is installed
if ! command -v kind &> /dev/null; then
    echo "Error: kind is not installed. Please install it first."
    echo "  brew install kind  # macOS"
    echo "  # or see: https://kind.sigs.k8s.io/docs/user/quick-start/#installation"
    exit 1
fi

# Check if cluster already exists
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    echo "Cluster '$CLUSTER_NAME' already exists."
    read -p "Delete and recreate? [y/N]: " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        echo "Deleting existing cluster..."
        kind delete cluster --name "$CLUSTER_NAME"
    else
        echo "Using existing cluster."
        kubectl cluster-info --context "kind-${CLUSTER_NAME}"
        exit 0
    fi
fi

# Create the cluster
echo "Creating Kind cluster..."
kind create cluster --config "$SCRIPT_DIR/kind-config.yaml"

# Wait for cluster to be ready
echo "Waiting for cluster to be ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=120s

# Show cluster info
echo ""
echo "Cluster created successfully!"
kubectl cluster-info --context "kind-${CLUSTER_NAME}"

echo ""
echo "Port mappings:"
echo "  - localhost:8080 -> Demo App (NodePort 30080)"
echo "  - localhost:9090 -> Prometheus (NodePort 30090)"
echo "  - localhost:3000 -> Grafana (NodePort 30300)"
echo "  - localhost:30015 -> agentgateway UI (NodePort 30015)"

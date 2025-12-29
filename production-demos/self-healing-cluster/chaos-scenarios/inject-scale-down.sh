#!/bin/bash
# Chaos Scenario 3: Scale to Zero
# Scales down the deployment to 0 replicas

set -e

echo "Scaling down httpbin to 0 replicas..."

kubectl scale deployment httpbin -n demo --replicas=0

echo "Deployment scaled to 0. Agent should detect missing pods."
echo "Watch the self-healing agent detect and fix this..."
echo ""
echo "To monitor:"
echo "  kubectl get pods -n demo -w"

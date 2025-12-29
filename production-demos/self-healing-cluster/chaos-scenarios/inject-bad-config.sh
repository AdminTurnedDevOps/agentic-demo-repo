#!/bin/bash
# Chaos Scenario 4: Bad ConfigMap
# Injects a bad configuration that causes startup failures

set -e

echo "Injecting bad configuration..."

# Create a configmap with invalid settings
kubectl create configmap httpbin-config -n demo \
  --from-literal=GUNICORN_CMD_ARGS="--invalid-flag" \
  --dry-run=client -o yaml | kubectl apply -f -

# Patch deployment to use the bad configmap
kubectl patch deployment httpbin -n demo --type='json' -p='[
  {
    "op": "add",
    "path": "/spec/template/spec/containers/0/envFrom",
    "value": [{"configMapRef": {"name": "httpbin-config"}}]
  }
]'

echo "Bad config injected. Pods will fail to start."
echo "Watch the self-healing agent detect and fix this..."
echo ""
echo "To monitor:"
echo "  kubectl get pods -n demo -w"

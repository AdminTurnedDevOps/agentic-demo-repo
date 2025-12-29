#!/bin/bash
# Chaos Scenario 2: OOMKill
# Reduces memory limits to trigger OOM kills

set -e

echo "Injecting memory pressure..."

# Patch deployment with very low memory limits
kubectl patch deployment httpbin -n demo --type='json' -p='[
  {
    "op": "replace",
    "path": "/spec/template/spec/containers/0/resources/limits/memory",
    "value": "10Mi"
  }
]'

echo "Memory limit reduced to 10Mi. Pods will OOMKill."
echo "Watch the self-healing agent detect and fix this..."
echo ""
echo "To monitor:"
echo "  kubectl get pods -n demo -w"

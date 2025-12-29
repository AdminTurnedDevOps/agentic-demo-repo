#!/bin/bash
# Chaos Scenario 1: CrashLoopBackOff
# Injects a bad command that causes pods to crash immediately

set -e

echo "Injecting CrashLoopBackOff failure..."

# Patch deployment to use a bad command that will crash
kubectl patch deployment httpbin -n demo --type='json' -p='[
  {
    "op": "add",
    "path": "/spec/template/spec/containers/0/command",
    "value": ["/bin/sh", "-c", "exit 1"]
  }
]'

echo "Failure injected. Pods will start crash looping."
echo "Watch the self-healing agent detect and fix this..."
echo ""
echo "To monitor:"
echo "  kubectl get pods -n demo -w"

#!/bin/bash
# Cleanup script for SRE Demo

echo "🧹 Cleaning up SRE Demo resources..."

# Delete the demo namespace and all resources in it
kubectl delete namespace demo --ignore-not-found=true

echo "✅ Demo cleanup complete!"
echo ""
echo "To redeploy the demo, run:"
echo "  kubectl apply -f broken-app.yaml"

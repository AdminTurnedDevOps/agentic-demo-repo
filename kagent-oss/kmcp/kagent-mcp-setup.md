```
curl -fsSL https://raw.githubusercontent.com/kagent-dev/kmcp/refs/heads/main/scripts/get-kmcp.sh | bash
```

```
kagent mcp init python mlevan-oss
```

```
kagent mcp build --project-dir mlevan-oss -t pythontesting1:latest
docker push adminturneddevops/pythontesting1:latest
```

```
helm install kmcp-crds oci://ghcr.io/kagent-dev/kmcp/helm/kmcp-crds \
  --namespace kmcp-system \
  --create-namespace
```

```
kmcp install
```

```
kubectl get pods -n kmcp-system
```

```
kubectl apply -f- <<EOF
apiVersion: kagent.dev/v1alpha1
kind: MCPServer
metadata:
  name: mlevan-oss
  namespace: kagent
spec:
  deployment:
    image: "adminturneddevops/pythontesting1:latest"
    port: 3000
    cmd: "python"
    args: ["src/main.py"]
  transportType: "stdio"
EOF
```

If you built your MCP Server container image on something like an M4 Mac (ARM-based architecture), you'll need to add in an ARM-based Worker Node and patch your deployment for to select the ARM-based node.
```
kubectl patch deployment mlevan-oss -n default -p '{"spec":{"template":{"spec":{"nodeSelector":{"kubernetes.io/arch":"arm64"}}}}}'
```

```
kubectl get pods
```
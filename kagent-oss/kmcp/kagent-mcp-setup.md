```
curl -fsSL https://raw.githubusercontent.com/kagent-dev/kmcp/refs/heads/main/scripts/get-kmcp.sh | bash
```

```
kagent mcp init python mlevan-oss
```

```
kagent mcp build --project-dir mlevan-oss -t pythontesting:latest

docker buildx build --platform linux/amd64,linux/arm64 -t adminturneddevops/pythontesting:latest --push .
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
kubectl get pods -n kagent
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
    image: "adminturneddevops/pythontesting@sha256:89f1a29500c170fc09de0607e96860473708a3e99ba309a75e4cbdec9d447f13"
    port: 3000
    cmd: "python"
    args: ["src/main.py"]
  transportType: "stdio"
EOF
```

```
kubectl get pods
```
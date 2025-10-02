```
curl -fsSL https://raw.githubusercontent.com/kagent-dev/kmcp/refs/heads/main/scripts/get-kmcp.sh | bash
```

```
kmcp init python mlevan-fe
```

```
kmcp build --project-dir mlevan-fe -t pythontesting:latest
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
  name: mlevan-fe
spec:
  deployment:
    image: "adminturneddevops/pythontesting:latest"
    port: 3000
    cmd: "python"
    args: ["src/main.py"]
  transportType: "stdio"
EOF
```

kubectl get pods

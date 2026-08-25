# Virtual MCP: GitHub Copilot + mcp-server-everything

Federate two MCP servers behind one agentgateway endpoint:

- **mcp-server-everything** — in-cluster, Streamable HTTP, discovered by label selector
- **GitHub Copilot MCP** — remote `https://api.githubcopilot.com/mcp/`, static HTTPS target with a PAT

Clients connect once to `/mcp` and see tools from both. Agentgateway namespaces tool names with the target so they do not collide.

Source for the in-cluster server: [Virtual MCP — mcp-server-everything](https://agentgateway.dev/docs/kubernetes/latest/mcp/virtual/#mcp-server-everything).

## Prereqs

- Local Kubernetes cluster (`kind`, `k3d`, or similar)
- Agentgateway Enterprise
- A GitHub PAT that can call the Copilot MCP server (classic token with `repo` is enough to list issues/PRs and run `get_me`)

## 1. Deploy mcp-server-everything

Deploy the official `@modelcontextprotocol/server-everything` workload. The Service sets `appProtocol: agentgateway.dev/mcp` so the gateway treats it as an MCP backend. Put it in `agentgateway-system` so the backend selector in the next step can find it (selectors default to the backend's own namespace).

```
kubectl apply -n agentgateway-system -f- <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-server-everything
  labels:
    app: mcp-server-everything
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mcp-server-everything
  template:
    metadata:
      labels:
        app: mcp-server-everything
    spec:
      containers:
        - name: mcp-server-everything
          image: node:20-alpine
          command: ["npx"]
          args: ["-y", "@modelcontextprotocol/server-everything", "streamableHttp"]
          ports:
            - containerPort: 3001
          readinessProbe:
            tcpSocket:
              port: 3001
            initialDelaySeconds: 2
            periodSeconds: 2
            failureThreshold: 30
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-server-everything
  labels:
    app: mcp-server-everything
spec:
  selector:
    app: mcp-server-everything
  ports:
    - protocol: TCP
      port: 3001
      targetPort: 3001
      appProtocol: agentgateway.dev/mcp
  type: ClusterIP
EOF
```

Wait until the pod is ready:

```
kubectl rollout status deploy/mcp-server-everything -n agentgateway-system
```

## 2. Store the GitHub PAT

The value must be the full `Authorization` header. Agentgateway sends it verbatim to `api.githubcopilot.com`.

```
export GITHUB_PAT=

kubectl apply -f- <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: github-pat
  namespace: agentgateway-system
type: Opaque
stringData:
  Authorization: "Bearer ${GITHUB_PAT}"
EOF
```

## 3. Create a Gateway

```
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: virtual-mcp-gateway
  namespace: agentgateway-system
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
    - name: http
      port: 3000
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
EOF
```

```
kubectl wait --for=condition=Programmed gateway/virtual-mcp-gateway -n agentgateway-system --timeout=120s
```

## 4. Create the virtual MCP backend

One `EnterpriseAgentgatewayBackend` with two targets (same mix as the [OSS virtual MCP docs](https://agentgateway.dev/docs/kubernetes/latest/mcp/virtual/): selector + static):

- **selector** — any Service labeled `app: mcp-server-everything` (the in-cluster server)
- **static** — GitHub Copilot MCP over HTTPS

`failureMode: FailOpen` keeps the other target serving if GitHub or the in-cluster server is down. Default is `FailClosed`, which fails the whole session if either target cannot initialize.

Put the PAT on the **GitHub target** (`policies.auth.secretRef`), not on the HTTPRoute. The official HTTPS guide sets `Authorization` on the route because that example has only GitHub. Here the same header would also go to mcp-server-everything.

```
kubectl apply -f- <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayBackend
metadata:
  name: virtual-mcp
  namespace: agentgateway-system
spec:
  entMcp:
    failureMode: FailOpen
    targets:
      - name: mcp-server-everything
        selector:
          services:
            matchLabels:
              app: mcp-server-everything
      - name: github-copilot
        static:
          host: api.githubcopilot.com
          port: 443
          path: /mcp/
          protocol: StreamableHTTP
          policies:
            tls:
              sni: api.githubcopilot.com
            auth:
              secretRef:
                name: github-pat
EOF
```

Check the backend is accepted:

```
kubectl get enterpriseagentgatewaybackend virtual-mcp -n agentgateway-system
```

## 5. Route `/mcp` to the backend

CORS is for MCP Inspector on `http://localhost:8080`. Do **not** put the GitHub PAT on this route — that would send it to mcp-server-everything as well. Auth stays on the GitHub target only.

```
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: virtual-mcp
  namespace: agentgateway-system
spec:
  parentRefs:
    - name: virtual-mcp-gateway
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /mcp
      filters:
        - type: CORS
          cors:
            allowOrigins:
              - "http://localhost:8080"
            allowMethods:
              - "*"
            allowHeaders:
              - "*"
      backendRefs:
        - name: virtual-mcp
          group: enterpriseagentgateway.solo.io
          kind: EnterpriseAgentgatewayBackend
EOF
```

```
kubectl describe httproute virtual-mcp -n agentgateway-system
```

`Accepted` and `ResolvedRefs` should both be `True`.

## 6. Verify with MCP Inspector

Port-forward the gateway:

```
kubectl port-forward -n agentgateway-system svc/virtual-mcp-gateway 8080:3000
```

In another terminal:

```
npx @modelcontextprotocol/inspector@0.21.2
```

Connect:

- **Transport Type**: Streamable HTTP
- **URL**: `http://localhost:8080/mcp`
- Click **Connect**, then **Tools → List tools**

With more than one target, agentgateway prefixes tool names (`prefixMode: Conditional` is the default):

| Prefix | Source |
|---|---|
| `mcp-server-everything-3001_*` | in-cluster server (`echo`, `add`, …) |
| `github-copilot_*` | GitHub Copilot MCP (`get_me`, `list_issues`, …) |

Smoke tests:

- `mcp-server-everything-3001_echo` — message `Hello world`
- `mcp-server-everything-3001_add` — `a=2`, `b=3`
- `github-copilot_get_me` — returns the GitHub user for the PAT

## Cleanup

```
kubectl delete httproute virtual-mcp -n agentgateway-system
kubectl delete enterpriseagentgatewaybackend virtual-mcp -n agentgateway-system
kubectl delete gateway virtual-mcp-gateway -n agentgateway-system
kubectl delete secret github-pat -n agentgateway-system
kubectl delete deploy,svc mcp-server-everything -n agentgateway-system
```

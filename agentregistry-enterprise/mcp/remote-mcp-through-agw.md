# Remote MCP Through Agentgateway

This demo catalogs a remote MCP server in agentregistry Enterprise and exposes
it through Agentgateway using a `Virtual` runtime.

The flow is:

```text
client -> Agentgateway Gateway -> parent HTTPRoute -> agentregistry child HTTPRoute -> AgentgatewayBackend -> remote MCP server
```

Agentregistry owns the catalog `MCPServer` and `Deployment`. The gateway admin
owns the Kubernetes `Gateway` and parent `HTTPRoute`.

## Prerequisites

- Agentregistry is installed and `arctl` is authenticated.
- Agentgateway and Gateway API CRDs are installed.
- A GatewayClass named `enterprise-agentgateway` exists.
- The agentregistry install namespace is `agentregistry-system`.
- For the GitHub Copilot MCP example, export a GitHub token:

```bash
export GITHUB_COPILOT_MCP_TOKEN="<github-token>"
```

## 1. Create The Parent Gateway And Route

The `agentregistry.solo.io/runtime` label binds Kubernetes gateway resources to
an agentregistry `Virtual` runtime. This demo uses the seeded
`virtual-default` runtime.

```bash
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: remote-mcp-gateway
  namespace: agentgateway-system
  labels:
    agentregistry.solo.io/runtime: virtual-default
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
    - protocol: HTTP
      port: 80
      name: http
      allowedRoutes:
        namespaces:
          from: All
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: remote-mcp-delegate
  namespace: agentgateway-system
  labels:
    agentregistry.solo.io/runtime: virtual-default
spec:
  parentRefs:
    - name: remote-mcp-gateway
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /registry
      backendRefs:
        - group: gateway.networking.k8s.io
          kind: HTTPRoute
          name: "*"
          namespace: agentregistry-system
EOF
```

The parent `HTTPRoute` delegates `/registry` to child `HTTPRoute` resources that
agentregistry creates in the `agentregistry-system` namespace.

## 2. Confirm The Virtual Runtime Exists

Agentregistry seeds `virtual-default` on startup.

```bash
arctl get runtime virtual-default -o yaml
```

Expected shap:

```yaml
apiVersion: ar.dev/v1alpha1
kind: Runtime
metadata:
  name: virtual-default
spec:
  type: Virtual
```

**If it does not exist, create it:**

```bash
arctl apply -f - <<EOF
apiVersion: ar.dev/v1alpha1
kind: Runtime
metadata:
  name: virtual-default
spec:
  type: Virtual
EOF
```

## 3. Catalog The Remote MCP Server

This example catalogs GitHub Copilot MCP as a remote MCP server.

For demo purposes, the token is rendered into the agentregistry catalog entry.
For production, use the secret mechanism supported by your deployment instead
of committing or sharing literal credentials.

```bash
arctl apply -f - <<EOF
apiVersion: ar.dev/v1alpha1
kind: MCPServer
metadata:
  name: github-copilot-remote-mcp
  tag: latest
spec:
  title: GitHub Copilot Remote MCP
  description: GitHub Copilot MCP exposed through Agentgateway
  remote:
    type: streamable-http
    url: https://api.githubcopilot.com/mcp
    headers:
      - name: Authorization
        value: "Bearer ${GITHUB_COPILOT_MCP_TOKEN}"
EOF
```

Verify it exists in the catalog:

```bash
arctl get mcp github-copilot-remote-mcp --tag latest -o yaml
```

## 4. Deploy The Remote MCP To The Virtual Runtime

The `runtimeConfig.route.pathSuffix` is appended under the parent route prefix.
With the parent route above, this exposes the remote MCP at:

```text
/registry/github-copilot
```

```bash
arctl apply -f - <<EOF
apiVersion: ar.dev/v1alpha1
kind: Deployment
metadata:
  name: github-copilot-remote-mcp-agw
spec:
  targetRef:
    kind: MCPServer
    name: github-copilot-remote-mcp
    tag: latest
  runtimeRef:
    kind: Runtime
    name: virtual-default
  runtimeConfig:
    route:
      pathSuffix: /github-copilot
EOF
```

Verify the Deployment:

```bash
arctl get deployment github-copilot-remote-mcp-agw -o yaml
```

Look for:

- `Ready=True`
- `reason: DeployedViaAgentgateway`
- `status.details.agentgateway.exposedAt`

## 5. Inspect Generated Agentgateway Resources

Agentregistry should create child resources in its install namespace.

```bash
kubectl -n agentregistry-system get httproutes.gateway.networking.k8s.io
kubectl -n agentregistry-system get agentgatewaybackends.agentgateway.dev
```

Describe the generated child route and backend if you need to troubleshoot:

```bash
kubectl -n agentregistry-system describe httproute
kubectl -n agentregistry-system describe agentgatewaybackend
```

## 6. Get The Gateway Address

```bash
kubectl -n agentgateway-system get gateway remote-mcp-gateway
kubectl -n agentgateway-system get svc
```

Depending on your environment, the Gateway address might appear on the Gateway
status or on the Agentgateway-managed Service.

Set the gateway host or IP:

```bash
export AGW_ADDRESS="<gateway-address>"
```

## 7. Call The Exposed MCP Endpoint

The exact MCP client request depends on the MCP client you use. As a basic
connectivity check, send a request to the delegated path:

```bash
curl -i "http://${AGW_ADDRESS}/registry/github-copilot"
```

For real MCP traffic, configure your MCP client to use:

```text
http://<gateway-address>/registry/github-copilot
```

If the parent route has `hostnames`, include the expected Host header:

```bash
curl -i \
  -H "Host: mcp.example.com" \
  "http://${AGW_ADDRESS}/registry/github-copilot"
```

## Troubleshooting

### Deployment Has `NoGatewayBound`

Confirm the Gateway and parent HTTPRoute both have the runtime label:

```bash
kubectl -n agentgateway-system get gateway remote-mcp-gateway --show-labels
kubectl -n agentgateway-system get httproute remote-mcp-delegate --show-labels
```

The label value must match the agentregistry runtime name:

```text
agentregistry.solo.io/runtime=virtual-default
```

### No Child HTTPRoute Was Created

Check the agentregistry Deployment status:

```bash
arctl get deployment github-copilot-remote-mcp-agw -o yaml
```

Common causes:

- The `runtimeRef.name` does not match the Gateway/HTTPRoute label.
- The parent HTTPRoute delegates to the wrong namespace.
- The remote MCP catalog entry is missing `spec.remote`.
- The `runtimeConfig.route.pathSuffix` is missing or collides with another Deployment.

### Upstream TLS Or Auth Fails

For an `https://` remote MCP URL, agentregistry configures Agentgateway to use
TLS to the upstream. If the upstream needs custom TLS, mTLS, or custom auth
handling, attach the appropriate Agentgateway policy to the generated backend.

## Cleanup

```bash
arctl delete deployment github-copilot-remote-mcp-agw
arctl delete mcp github-copilot-remote-mcp --tag latest

kubectl -n agentgateway-system delete httproute remote-mcp-delegate
kubectl -n agentgateway-system delete gateway remote-mcp-gateway
```

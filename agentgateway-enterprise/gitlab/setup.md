# GitLab MCP Server Integration with OAuth

This guide configures the Agentgateway to reach GitLab's MCP Server using OAuth authentication (passing the token through) via GitLab as the identity provider.

## Prerequisites

1. Create a GitLab OAuth Application.
2. Have VS Code installed

## 1. Deploy Gateway, Backend, and HTTPRoute

```bash
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: agentgateway-proxy
  namespace: agentgateway-system
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
  - name: http
    port: 8080
    protocol: HTTP
    allowedRoutes:
      namespaces:
        from: Same
---
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: gitlab-mcp-backend
  namespace: agentgateway-system
spec:
  policies:
    http:
      requestTimeout: 10s
  mcp:
    targets:
      - name: gitlab
        static:
          host: gitlab.com
          port: 443
          path: /api/v4/mcp
          protocol: StreamableHTTP
          policies:
            tls: {}
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: mcp-gitlab
  namespace: agentgateway-system
spec:
  parentRefs:
    - name: agentgateway-proxy
      namespace: agentgateway-system
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: gitlab-mcp-backend
          group: agentgateway.dev
          kind: AgentgatewayBackend
EOF
```

Outcome with VS Code

![](images/1.png)
![](images/2.png)

This session ID can be anything. You can keep it as the default.

![](images/3.png)

This can be global or local
![](images/4.png)
![](images/5.png)
![](images/6.png)
![](images/7.png)
![](images/8.png)
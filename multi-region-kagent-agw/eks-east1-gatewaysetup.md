
```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: agentgateway-route-bedrock
  namespace: agentgateway-system
  labels:
    app: agentgateway-route-bedrock
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
    - name: http
      port: 8082
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: bedrock
  namespace: agentgateway-system
spec:
  mcp:
    targets:
      - name: bedrock
        static:
          host: BEDROCK-HOST
          port: 80
          path: /BEDROCK-PATH
          protocol: StreamableHTTP
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: claude
  namespace: agentgateway-system
  labels:
    app: agentgateway-route-bedrock
spec:
  parentRefs:
    - name: agentgateway-route-bedrock
      namespace: agentgateway-system
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /ai
    filters:
    - type: URLRewrite
      urlRewrite:
        path:
          type: ReplaceFullPath
          replaceFullPath: /v1/chat/completions
    backendRefs:
    - name: bedrock
      namespace: agentgateway-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```
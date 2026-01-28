## LLM Connectivity

```
export ANTHROPIC_API_KEY=
```

```
kubectl apply -f- <<EOF
kind: Gateway
apiVersion: gateway.networking.k8s.io/v1
metadata:
  name: agentgateway-route
  namespace: agent-system
  labels:
    app: agentgateway
spec:
  gatewayClassName: agentgateway-enterprise
  listeners:
  - protocol: HTTP
    port: 8080
    name: http
    allowedRoutes:
      namespaces:
        from: All
EOF
```

```
export INGRESS_GW_ADDRESS=$(kubectl get svc -n agentgateway-system agentgateway-route -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESS
```

```
kubectl apply -f- <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: anthropic-secret
  namespace: agentgateway-system
  labels:
    app: agentgateway-route
type: Opaque
stringData:
  Authorization: $CLAUDE_API_KEY
EOF
```

```
kubectl apply -f- <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  labels:
    app: agentgateway-route
  name: anthropic
  namespace: agentgateway-system
spec:
  ai:
    provider:
        openai:
          model: "claude-3-5-haiku-latest"
  policies:
    auth:
      secretRef:
        name: anthropic-secret
EOF
```

```
kubectl get backend -n agentgateway-system
```

```
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: claude
  namespace: agentgateway-system
  labels:
    app: agentgateway-route
spec:
  parentRefs:
    - name: agentgateway-route
      namespace: agentgateway-system
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /anthropic
    filters:
    - type: URLRewrite
      urlRewrite:
        path:
          type: ReplaceFullPath
          replaceFullPath: /v1/chat/completions
    backendRefs:
    - name: anthropic
      namespace: agentgateway-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```

```
curl "$INGRESS_GW_ADDRESS:8080/anthropic" -H content-type:application/json -H x-api-key:$ANTHROPIC_API_KEY -H "anthropic-version: 2023-06-01" -d '{
  "messages": [
    {
      "role": "system",
      "content": "You are a skilled cloud-native network engineer."
    },
    {
      "role": "user",
      "content": "Write me a paragraph containing the best way to think about Istio Ambient Mesh"
    }
  ]
}' | jq
```

## TLS Without Waypoint

```
kubectl apply -f- <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: jwt
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: mcp-gateway
  traffic:
    jwtAuthentication:
      providers:
        - issuer: solo.io
          jwks:
            inline: '{"keys": [{"kty": "RSA", "kid": "solo-public-key-001", "use": "sig", "alg": "RS256", "n": "vdV2XxH70WcgDKedYXNQ3Dy1LN8LKziw3pxBe0M-QG3_urCbN-oTPL2e0xrj5t2JOV-eBNaII17oZ6z9q84lLzn4mgU_UzP-Efv6iTZLlC_SD30AknifnoX8k38zbJtuwkvVcZvkam0LM5oIwSf4wJVpdPKHb3o_gGRpCBxWdQHPdBWMBPwOeqFfONFrM0bEnShFWf3d87EgckdVcrypelLyUZJ_ACdEGYUhS6FHmyojA1g6zKryAAWsH5Y-UCUuJd7VlOCMoBpAKK0BSdlF3WVSYHDlyMSB5H61eYCXSpfKcGhoHxViLgq6yjUR7TOHkJ-OtWna513TrkRw2Y0hsQ", "e": "AQAB"}]}'
EOF
```

## oAuth2-proxy

You'll see `4180` as the port via the backend ref. `4180` is the default port that oauth2-proxy listens on.

```
kubectl apply -f- <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: jwt
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: mcp-gateway
  frontend:
    accessLog:
      attributes:
        add:
          - name: github.user
            expression: extauthz.githubUser
          - name: github.email
            expression: extauthz.githubEmail
  traffic:
    extAuth:
      backendRef:
        name: oauth2-proxy
        port: 4180
      http:
        responseMetadata:
          githubUser: 'response.headers["x-auth-request-user"]'
          githubEmail: 'response.headers["x-auth-request-email"]'
        allowedResponseHeaders:
          - x-auth-request-user
          - x-auth-request-email
EOF
```
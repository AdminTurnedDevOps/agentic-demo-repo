## MCP Server Connection

1. . Deploy the MCP Server
```
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-website-fetcher
  namespace: default
spec:
  selector:
    matchLabels:
      app: mcp-website-fetcher
  template:
    metadata:
      labels:
        app: mcp-website-fetcher
    spec:
      containers:
      - name: mcp-website-fetcher
        image: ghcr.io/peterj/mcp-website-fetcher:main
        imagePullPolicy: Always
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-website-fetcher
  namespace: default
spec:
  selector:
    app: mcp-website-fetcher
  ports:
  - port: 80
    targetPort: 8000
    appProtocol: kgateway.dev/mcp
EOF
```

2. Create the Backend
```
kubectl apply -f - <<EOF
apiVersion: gateway.kgateway.dev/v1alpha1
kind: Backend
metadata:
  name: mcp-backend
  namespace: gloo-system
spec:
  type: MCP
  mcp:
    targets:
    - name: mcp-target
      static:
        host: mcp-website-fetcher.default.svc.cluster.local
        port: 80
        protocol: StreamableHTTP
        #protocol: SSE
EOF
```

3. Create the Gateway
```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: agentgateway
  namespace: gloo-system
spec:
  gatewayClassName: agentgateway-enterprise
  listeners:
  - name: http
    port: 8080
    protocol: HTTP
    allowedRoutes:
      namespaces:
        from: Same
EOF
```

4. Create the HTTPRoute
```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: mcp-route
  namespace: gloo-system
spec:
  parentRefs:
  - name: agentgateway
  rules:
  - backendRefs:
    - name: mcp-backend
      group: gateway.kgateway.dev
      kind: Backend
EOF
```

5. Test the Gateway/route
```
export GATEWAY_IP=$(kubectl get svc agentgateway -n gloo-system -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo $GATEWAY_IP
```

6. Open MCP Inspector
```
npx modelcontextprotocol/inspector#0.16.2
```

URL to put into Inspector: `http://YOUR_ALB_LB_IP:8080/mcp`

## Secure Connectivity With JWT

1. Add in a traffic policy for auth based on a JWT token
```
kubectl apply -f- <<EOF
apiVersion: gloo.solo.io/v1alpha1
kind: GlooTrafficPolicy
metadata:
  name: jwt
  namespace: gloo-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: agentgateway
  glooJWT:
    beforeExtAuth:
      providers:
        selfminted:
          issuer: solo.io
          jwks:
            local:
              key: '{"keys":[{"kty":"RSA","kid":"solo-public-key-001","use":"sig","alg":"RS256","n":"AOfIaJMUm7564sWWNHaXt_hS8H0O1Ew59-nRqruMQosfQqa7tWne5lL3m9sMAkfa3Twx0LMN_7QqRDoztvV3Wa_JwbMzb9afWE-IfKIuDqkvog6s-xGIFNhtDGBTuL8YAQYtwCF7l49SMv-GqyLe-nO9yJW-6wIGoOqImZrCxjxXFzF6mTMOBpIODFj0LUZ54QQuDcD1Nue2LMLsUvGa7V1ZHsYuGvUqzvXFBXMmMS2OzGir9ckpUhrUeHDCGFpEM4IQnu-9U8TbAJxKE5Zp8Nikefr2ISIG2Hk1K2rBAc_HwoPeWAcAWUAR5tWHAxx-UXClSZQ9TMFK850gQGenUp8","e":"AQAB"}]}'
EOF
```

2. Save the token for "Bob"
```
eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6InNvbG8tcHVibGljLWtleS0wMDEifQ.eyJpc3MiOiJzb2xvLmlvIiwib3JnIjoic29sby5pbyIsInN1YiI6ImJvYiIsInRlYW0iOiJvcHMiLCJleHAiOjIwNzQyNzQ5NTQsImxsbXMiOnsibWlzdHJhbGFpIjpbIm1pc3RyYWwtbGFyZ2UtbGF0ZXN0Il19fQ.GF_uyLpZSTT1DIvJeO_eish1WDjMaS4BQSifGQhqPRLjzu3nXtPkaBRjceAmJi9gKZYAzkT25MIrT42ZIe3bHilrd1yqittTPWrrM4sWDDeldnGsfU07DWJHyboNapYR-KZGImSmOYshJlzm1tT_Bjt3-RK3OBzYi90_wl0dyAl9D7wwDCzOD4MRGFpoMrws_OgVrcZQKcadvIsH8figPwN4mK1U_1mxuL08RWTu92xBcezEO4CdBaFTUbkYN66Y2vKSTyPCxg3fLtg1mvlzU1-Wgm2xZIiPiarQHt6Uq7v9ftgzwdUBQM1AYLvUVhCN6XkkR9OU3p0OXiqEDjAxcg
```

3. Try to re-connect to the MCP Server. You'll see something similar to the below:
```
Connection Error - Check if your MCP server is running and proxy token is correct
```

4. Click on **Authentication**
- Header Name: **Authorization**
- Bearer Token: Bobs Token from step 2

## Lock Down Tool List

1. Create a policy that specifies no tools listed
```
kubectl apply -f- <<EOF
apiVersion: gateway.kgateway.dev/v1alpha1
kind: TrafficPolicy
metadata:
  name: jwt-rbac
  namespace: gloo-system
spec:
  targetRefs:
    - group: gateway.kgateway.dev
      kind: Backend
      name: mcp-backend
  rbac:
    policy:
      matchExpressions:
        - 'mcp.tool.name == ""'
EOF
```

2. Disconnect and reconnect via the MCP Inspector and you should see no tools

3. Update the policy to include the **Fetch** tool

```
kubectl apply -f- <<EOF
apiVersion: gateway.kgateway.dev/v1alpha1
kind: TrafficPolicy
metadata:
  name: jwt-rbac
  namespace: gloo-system
spec:
  targetRefs:
    - group: gateway.kgateway.dev
      kind: Backend
      name: mcp-backend
  rbac:
    policy:
      matchExpressions:
        - 'mcp.tool.name == "fetch"'
EOF
```
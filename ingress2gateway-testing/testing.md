```
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: cors-ingress
  namespace: default
  annotations:
    nginx.ingress.kubernetes.io/enable-cors: "true"
    nginx.ingress.kubernetes.io/cors-allow-origin: "https://app.example.com,https://dashboard.example.com"
    nginx.ingress.kubernetes.io/cors-allow-methods: "GET,POST,PUT,DELETE,OPTIONS"
    nginx.ingress.kubernetes.io/cors-allow-headers: "Authorization,Content-Type,X-Requested-With"
    nginx.ingress.kubernetes.io/cors-expose-headers: "X-Custom-Header,X-Request-ID"
    nginx.ingress.kubernetes.io/cors-allow-credentials: "true"
    nginx.ingress.kubernetes.io/cors-max-age: "7200"
spec:
  ingressClassName: nginx
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /v1
        pathType: Prefix
        backend:
          service:
            name: api-service
            port:
              number: 80
EOF
```

```
./ingress2gateway print --providers=ingress-nginx --emitter=kgateway
```

```
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  annotations:
    gateway.networking.k8s.io/generator: ingress2gateway-v0.3.0
  name: nginx
  namespace: default
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
  - hostname: admin.example.com
    name: admin-example-com-http
    port: 80
    protocol: HTTP
  - hostname: api.example.com
    name: api-example-com-http
    port: 80
    protocol: HTTP
status: {}
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  annotations:
    gateway.networking.k8s.io/generator: ingress2gateway-v0.3.0
  name: auth-ingress-admin-example-com
  namespace: default
spec:
  hostnames:
  - admin.example.com
  parentRefs:
  - name: nginx
  rules:
  - backendRefs:
    - name: admin-service
      port: 80
    matches:
    - path:
        type: PathPrefix
        value: /
status:
  parents: []
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  annotations:
    gateway.networking.k8s.io/generator: ingress2gateway-v0.3.0
  name: cors-ingress-api-example-com
  namespace: default
spec:
  hostnames:
  - api.example.com
  parentRefs:
  - name: nginx
  rules:
  - backendRefs:
    - name: api-service
      port: 80
    matches:
    - path:
        type: PathPrefix
        value: /v1
status:
  parents: []
---
apiVersion: gateway.kgateway.dev/v1alpha1
kind: TrafficPolicy
metadata:
  name: auth-ingress
  namespace: default
spec:
  basicAuth:
    secretRef:
      key: auth
      name: basic-auth
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: auth-ingress-admin-example-com
status:
  ancestors: null
---
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: cors-ingress-policy
  namespace: default
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: cors-ingress-api-example-com
  traffic:
    cors:
      allowCredentials: true
      allowHeaders:
      - Authorization
      - Content-Type
      - X-Requested-With
      allowMethods:
      - GET
      - POST
      - PUT
      - DELETE
      - OPTIONS
      allowOrigins:
      - https://app.example.com
      - https://dashboard.example.com
      exposeHeaders:
      - X-Custom-Header
      - X-Request-ID
      maxAge: 7200
```

## Functional Testing

1. Apply the Gateway, HTTPRoute, and EnterpriseAgentgatewayPolicy
```
kubectl apply -f - <<EOF
# Paste the Gateway, HTTPRoute, and EnterpriseAgentgatewayPolicy YAML from above
EOF
```

2. Verify the Gateway is accepted
```
kubectl get gateway nginx -o jsonpath='{.status.conditions[?(@.type=="Accepted")].status}'
```
Expected: `True`

3. Verify HTTPRoute is attached
```
kubectl get httproute cors-ingress-api-example-com -o jsonpath='{.status.parents[0].conditions[?(@.type=="Accepted")].status}'
```
Expected: `True`

4. Verify EnterpriseAgentgatewayPolicy is attached
```
kubectl get enterpriseagentgatewaypolicy cors-ingress-policy -o jsonpath='{.status.ancestors[0].conditions[?(@.type=="Attached")].status}'
```
Expected: `True`

5. Get the Gateway external IP
```
GATEWAY_IP=$(kubectl get gateway nginx -o jsonpath='{.status.addresses[0].value}')
echo $GATEWAY_IP
```

6. Test CORS preflight request (OPTIONS with allowed origin)
```
curl -I --resolve api.example.com:80:$GATEWAY_IP \
  -X OPTIONS \
  -H "Origin: https://app.example.com" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Authorization,Content-Type" \
  http://api.example.com/v1/
```
Expected: `200 OK` with CORS headers (access-control-allow-origin, access-control-allow-methods, etc.)

7. Test CORS preflight with disallowed origin (should not include CORS headers)
```
curl -I --resolve api.example.com:80:$GATEWAY_IP \
  -X OPTIONS \
  -H "Origin: https://evil.example.com" \
  -H "Access-Control-Request-Method: POST" \
  http://api.example.com/v1/
```

8. Test actual request with allowed origin
```
curl -I --resolve api.example.com:80:$GATEWAY_IP \
  -H "Origin: https://app.example.com" \
  http://api.example.com/v1/
```
Expected: Response includes `access-control-allow-origin: https://app.example.com`
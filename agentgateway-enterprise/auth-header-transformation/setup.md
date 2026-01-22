# Auth Header Transformation Setup

This guide demonstrates how to transform an incoming `Authorization` header to a custom header (`Foo`) on outbound requests, while removing the original `Authorization` header.

## Overview

**Use case:** Your upstream service expects authentication in a custom header format, but clients send standard `Authorization: Bearer xxx` headers.

**What this does:**
- Copies `Authorization` header value to `Foo` header
- Removes the original `Authorization` header
- Forwards the transformed request to the upstream

## 1. Deploy the test app (httpbin Backend)

httpbin echoes back the headers it receives, making it perfect for verifying transformations.

```bash
kubectl run httpbin --image=kennethreitz/httpbin --port=80
kubectl expose pod httpbin --port=80
```

Wait for httpbin to be ready:

```bash
kubectl wait --for=condition=Ready pod/httpbin --timeout=60s
```

## 2. Deploy the Gateway

```bash
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: agentgateway-header-test
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
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: httpbin-route
spec:
  parentRefs:
  - name: agentgateway-header-test
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: httpbin
      port: 80
EOF
```

## 3. Apply the Header Transformation Policy

This policy transforms the `Authorization` header to `Foo` and removes the original:

```bash
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: auth-header-transform
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: httpbin-route
  traffic:
    transformation:
      request:
        set:
        - name: Foo
          value: 'request.headers["authorization"]'
        remove:
        - authorization
EOF
```

## 4. Test the Transformation

Get the gateway address:

```bash
export GATEWAY_IP=$(kubectl get gateway agentgateway-header-test -o jsonpath='{.status.addresses[0].value}')
echo "Gateway IP: $GATEWAY_IP"
```

Send a request with an Authorization header and check the response:

```bash
curl -s -H "Authorization: Bearer test-token-123" http://$GATEWAY_IP:8080/headers | jq
```

**Expected output:**

```json
{
  "headers": {
    "Accept": "*/*",
    "Foo": "Bearer test-token-123",
    "Host": "<gateway-ip>:8080",
    "User-Agent": "curl/8.7.1"
  }
}
```

**Verify:**
- `Foo` header contains `Bearer test-token-123` (copied from Authorization)
- `Authorization` header is NOT present (successfully removed)

## Confirmation

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Taking an incoming Authorization header (`Authorization: Bearer xxxxx`) | ✅ Confirmed | Sent `Authorization: Bearer test-token-123` via curl |
| Transforming it to a different header on outbound request (`Foo: Bearer xxxxx`) | ✅ Confirmed | httpbin received `Foo: Bearer test-token-123` |
| Removing the original Authorization header | ✅ Confirmed | `Authorization` header was NOT present in httpbin's response |

**Note:** This test used httpbin as a stand-in for an upstream MCP server. httpbin echoes back all headers it receives, which proves the transformation happened before the request reached the upstream. The same transformation would apply to any backend (including an actual MCP server) referenced by the HTTPRoute.

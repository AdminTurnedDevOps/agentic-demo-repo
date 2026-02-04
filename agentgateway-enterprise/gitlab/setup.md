# GitLab MCP Server Integration with OAuth

This guide configures the AgentGateway to reach GitLab's MCP Server using OAuth authentication via GitLab as the identity provider.

You'll see `localhost` referenced a lot. This is based on the assumption that:
1. The Gateway doesn't have an ALB IP
2. There is no hostname

If you have a hostname for the Gateway or a public ALB IP, use that instead of `localhost` in this doc.

## Prerequisites

1. Create a GitLab OAuth Application:
   - Go to **GitLab → Settings → Applications** (or Admin Area → Applications for instance-wide)
   - Set **Redirect URI** to: `http://localhost:8080/callback` (adjust for production)
   - Select scopes: `openid`, `read_api`, `read_user`
   - Note your **Application ID** (Client ID) and **Secret** (Client Secret)

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
            value: /mcp-gitlab
      backendRefs:
        - name: gitlab-mcp-backend
          group: agentgateway.dev
          kind: AgentgatewayBackend
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: oauth-callback
  namespace: agentgateway-system
spec:
  parentRefs:
    - name: agentgateway-proxy
      namespace: agentgateway-system
  rules:
    - matches:
        - path:
            type: Exact
            value: /callback
      backendRefs:
        - name: gitlab-mcp-backend
          group: agentgateway.dev
          kind: AgentgatewayBackend
EOF
```

#### For Token Passthrough/OBO

Within the agentgateway helm installation, token exchange needs to be configured:
```
tokenExchange:
  enabled: true
  issuer: "enterprise-agentgateway.agentgateway-system.svc.cluster.local:7777"
  tokenExpiration: 24h
  subjectValidator:
    validatorType: remote
    remoteConfig:
      url: "https://gitlab.com/oauth/discovery/keys"  # GitLab's JWKS
  actorValidator:
    validatorType: k8s
```

Deploy a separate backend and HTTPRoute for OBO:

```bash
kubectl apply -f - <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: gitlab-mcp-backend-obo
  namespace: agentgateway-system
spec:
  mcp:
    targets:
      - name: gitlab-obo
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
  name: mcp-gitlab-obo
  namespace: agentgateway-system
spec:
  parentRefs:
    - name: agentgateway-proxy
      namespace: agentgateway-system
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /mcp-gitlab-obo
      backendRefs:
        - name: gitlab-mcp-backend-obo
          group: agentgateway.dev
          kind: AgentgatewayBackend
EOF
```

Retrieve the JWKS from the enterprise-agentgateway STS:

```bash
# Port-forward to the control plane
kubectl port-forward -n agentgateway-system deploy/enterprise-agentgateway 7777:7777 &
PF_PID=$!
sleep 2

# Fetch the JWKS
export CERT_KEYS=$(curl -s http://localhost:7777/.well-known/jwks.json)

# Stop the port-forward
kill $PF_PID
```

Then apply an EnterpriseAgentgatewayPolicy to enable OBO token exchange on this route:

```bash
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: gitlab-obo-policy
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
      name: mcp-gitlab-obo
  traffic:
    jwtAuthentication:
      mode: Strict
      providers:
      - issuer: enterprise-agentgateway.agentgateway-system.svc.cluster.local:7777
        jwks:
          inline: $CERT_KEYS
EOF
```

## 2. Set Environment Variables

```bash
export GITLAB_CLIENT_ID=<your-gitlab-application-id>
export GITLAB_CLIENT_SECRET=<your-gitlab-client-secret>
```

```bash
kubectl create secret generic gitlab-oauth-secret \
  -n agentgateway-system \
  --from-literal=oauth=$GITLAB_CLIENT_SECRET
```

## 3. Create the AuthConfig for GitLab OAuth

GitLab supports OIDC, so the ext-auth server can discover endpoints automatically via `https://gitlab.com/.well-known/openid-configuration`.

```bash
kubectl apply -f - <<EOF
apiVersion: extauth.solo.io/v1
kind: AuthConfig
metadata:
  name: oauth-gitlab
  namespace: agentgateway-system
spec:
  configs:
    - oauth2:
        oidcAuthorizationCode:
          appUrl: http://35.227.40.96:8080
          callbackPath: /callback
          clientId: $GITLAB_CLIENT_ID
          clientSecretRef:
            name: gitlab-oauth-secret
            namespace: agentgateway-system
          issuerUrl: https://gitlab.com
          scopes:
            - openid
            - read_api
            - read_user
          session:
            cookieOptions:
              notSecure: true  # Set to false in production with HTTPS
          headers:
            accessTokenHeader: "Authorization"
            useBearerSchemaForAuthorization: true
EOF
```

## 4. Apply the EnterpriseAgentgatewayPolicy

This links the OAuth AuthConfig to the Gateway, enforcing authentication on all traffic.

The `headerModifiers` section ensures the `X-Forwarded-Host` header includes the port, so ext-auth correctly constructs the original URL for post-OAuth redirect.

```bash
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: oauth-gitlab
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: agentgateway-proxy
  traffic:
    headerModifiers:
      request:
        set:
          - name: "X-Forwarded-Host"
            value: "35.227.40.96:8080"
          - name: "X-Forwarded-Port"
            value: "8080"
    entExtAuth:
      authConfigRef:
        name: oauth-gitlab
        namespace: agentgateway-system
      backendRef:
        name: ext-auth-service-enterprise-agentgateway
        namespace: agentgateway-system
        port: 8083
EOF
```

## 5. Verification

Verify all resources are created:

```bash
kubectl get gateway agentgateway-proxy -n agentgateway-system
kubectl get agentgatewaybackend gitlab-mcp-backend -n agentgateway-system
kubectl get httproute mcp-gitlab -n agentgateway-system
kubectl get authconfig oauth-gitlab -n agentgateway-system
kubectl get enterpriseagentgatewaypolicy oauth-gitlab -n agentgateway-system
```

## 6. Test the OAuth Flow

1. Port-forward to access the gateway locally (if you don't have a gateway IP or hostname):

```bash
kubectl port-forward -n agentgateway-system svc/agentgateway-proxy 8080:8080
```

2. Get the OAuth session cookie:
   1. Open your browser and go to: `http://35.227.40.96:8080/mcp-gitlab`
   2. Complete the GitLab OAuth flow
   3. Open developer tools → Application → Cookies
   4. Copy the `id_token` cookie value

## 7. Using the GitLab MCP Server

GitLab's MCP server uses the Streamable HTTP protocol, which requires initializing a session before making other requests.

### Step 1: Initialize the MCP Session

```bash
curl -v http://35.227.40.96:8080/mcp-gitlab \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -H "Cookie: id_token=<your-id-token>" \
  -d '{
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {
        "name": "test-client",
        "version": "1.0.0"
      }
    },
    "id": 1
  }'
```

Look for the `mcp-session-id` header in the response and save it:

```bash
export MCP_SESSION_ID=<session-id-from-response-header>
```

### Step 2: List Available Tools

```bash
curl -v http://35.227.40.96:8080/mcp-gitlab \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -H "Cookie: id_token=<your-id-token>" \
  -H "Mcp-Session-Id: $MCP_SESSION_ID" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/list",
    "id": 2
  }'
```

### Step 3: Call a Tool

```bash
curl -v http://35.227.40.96:8080/mcp-gitlab \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -H "Cookie: id_token=<your-id-token>" \
  -H "Mcp-Session-Id: $MCP_SESSION_ID" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "list_projects",
      "arguments": {
        "owned": true,
        "per_page": 5
      }
    },
    "id": 3
  }'
```

### Troubleshooting

1. **406 Not Acceptable** - Add `Accept: application/json, text/event-stream` header
2. **422 session header required** - You need to call `initialize` first and include the `Mcp-Session-Id` header
3. **Check ext-auth logs** for token validation errors:
   ```bash
   kubectl logs -n agentgateway-system -l app=ext-auth-service-enterprise-agentgateway -f
   ```
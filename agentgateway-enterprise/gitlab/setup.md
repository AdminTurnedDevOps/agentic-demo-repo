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
          appUrl: http://35.231.66.113:8080
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
          headers:
            accessTokenHeader: "Authorization"
          session:
            cookieOptions:
              notSecure: true
EOF
```

## 4. Apply the EnterpriseAgentgatewayPolicy

This links the OAuth AuthConfig to the Gateway, enforcing authentication on all traffic.

The `headerModifiers` section ensures ext-auth receives proper `X-Forwarded-Host` headers to correctly preserve and redirect to the original URL after OAuth completes.

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

## 6. Test the Setup

### Phase 1: Verify OAuth Flow

1. Port-forward to access the gateway locally (if you don't have a gateway IP or hostname):

```bash
kubectl port-forward -n agentgateway-system svc/agentgateway-proxy 8080:8080
```

2. Open browser to trigger OAuth redirect:

```bash
open "http://35.231.66.113:8080/mcp-gitlab"
```

**Checkpoint:** You should see the GitLab OAuth consent screen asking for `read_api`, `read_user`, `openid` permissions. After login, you'll be redirected back to `/mcp-gitlab`.

### Phase 2: Extract Session Cookie

After completing OAuth in browser:

1. Open DevTools → Application → Cookies → `http://35.227.40.96:8080`
2. Copy the `id_token` cookie value

You can watch ext-auth logs during OAuth flow to verify token processing:

```bash
kubectl logs -n agentgateway-system -l app=ext-auth-service-enterprise-agentgateway -f
```

### Phase 3: Initialize MCP Session

```bash
export ID_TOKEN=""

curl -v http://35.231.66.113:8080/mcp-gitlab \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -H "Cookie: id_token=$ID_TOKEN" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'
```

**Expected response:**
```json
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26","capabilities":{...},"serverInfo":{"name":"GitLab MCP Server",...}}}
```

**Checkpoint:** Look for `mcp-session-id` header in the response headers.

```bash
export MCP_SESSION_ID=<session-id-from-response-header>
```

### Phase 4: List Available Tools

```bash
curl http://35.231.66.113:8080/mcp-gitlab \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -H "Cookie: id_token=$ID_TOKEN" \
  -H "Mcp-Session-Id: $MCP_SESSION_ID" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":2}' | jq .
```

**Expected:** List of GitLab MCP tools like `list_projects`, `get_issue`, etc.

### Phase 5: Call a Tool

```bash
curl http://35.231.66.113:8080/mcp-gitlab \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -H "Cookie: id_token=$ID_TOKEN" \
  -H "Mcp-Session-Id: $MCP_SESSION_ID" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"list_projects","arguments":{"owned":true,"per_page":5}},"id":3}' | jq .
```

### Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| OAuth redirect fails | ext-auth misconfigured | Check ext-auth logs, verify AuthConfig |
| 401/403 on MCP calls | Token not passed correctly | Verify `id_token` cookie is set |
| 406 Not Acceptable | Missing Accept header | Add `Accept: application/json, text/event-stream` |
| 422 session required | No MCP session | Call `initialize` first, include `Mcp-Session-Id` header |
| Connection refused | Gateway not running | Check pods, verify IP/port |

**Diagnostic commands:**

```bash
# Check all pods are running
kubectl get pods -n agentgateway-system

# Check gateway status
kubectl get gateway agentgateway-proxy -n agentgateway-system

# Watch gateway proxy logs
kubectl logs -n agentgateway-system -l app=agentgateway-proxy -f

# Watch ext-auth logs
kubectl logs -n agentgateway-system -l app=ext-auth-service-enterprise-agentgateway -f
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
cat <<'EOF' | envsubst '$CERT_KEYS' | kubectl apply -f -
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
          inline: '${CERT_KEYS}'
EOF
```
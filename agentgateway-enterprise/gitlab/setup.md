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

## 1. Set Environment Variables

```bash
export GITLAB_CLIENT_ID=<your-gitlab-application-id>
export GITLAB_CLIENT_SECRET=<your-gitlab-client-secret>
```

## 2. Create the OAuth Secret

```bash
kubectl create secret generic gitlab-oauth-secret \
  -n agentgateway-system \
  --from-literal=oauth=$GITLAB_CLIENT_SECRET
```

## 3. Deploy Gateway, Backend, and HTTPRoute

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
EOF
```

## 4. Create the AuthConfig for GitLab OAuth

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
          appUrl: http://localhost:8080
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
EOF
```

## 5. Apply the EnterpriseAgentgatewayPolicy

This links the OAuth AuthConfig to the Gateway, enforcing authentication on all traffic.

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

## 6. Verification

Verify all resources are created:

```bash
kubectl get gateway agentgateway-proxy -n agentgateway-system
kubectl get agentgatewaybackend gitlab-mcp-backend -n agentgateway-system
kubectl get httproute mcp-gitlab -n agentgateway-system
kubectl get authconfig oauth-gitlab -n agentgateway-system
kubectl get enterpriseagentgatewaypolicy oauth-gitlab -n agentgateway-system
```

## 7. Test the OAuth Flow

Port-forward to access the gateway locally:

```bash
kubectl port-forward -n agentgateway-system svc/agentgateway-proxy 8080:8080
```

Test that OAuth redirect is working:

```bash
curl -v http://localhost:8080/mcp-gitlab
```

You should see a `302` redirect to `https://gitlab.com/oauth/authorize`. Open the URL in a browser to complete the GitLab OAuth flow.

Verify traffic reached the ext-auth server:

```bash
kubectl logs -n agentgateway-system -l app=ext-auth-service-enterprise-agentgateway --tail=50 | grep gitlab
```
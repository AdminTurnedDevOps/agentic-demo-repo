## ExtAuth Server

Uses Solos extauth server with an AuthConfig for OAuth. Port `8083` is the default extauth service port. This guide uses Google OAuth, which fully supports OIDC.

## Why Solos Extauth Server?

The core value proposition is centralizing and standardizing authentication/authorization at the gateway layer, so your LLMs, MCP servers, and agents don't have to implement auth themselves.

Key Benefits include:
1. Unified Auth Across AI Traffic Types

Solo's extauth handles auth for all three traffic patterns agentgateway manages: LLM provider calls, MCP server connections, and agent-to-agent (A2A) communication. One auth layer, multiple backends.

2. Built-in OIDC/OAuth2 Support
You get production-ready integration with identity providers (Keycloak, Entra ID, Auth0, Okta) without writing auth code.

Two modes:
- Authorization code flow — for end-user web apps hitting your AI APIs (redirects to IdP, exchanges codes for tokens)
- Access token validation — for programmatic/service-to-service access (validate tokens already obtained)

## 1. Deploy a Test Backend

Deploy a simple httpbin service to test the OAuth flow.

Since this is the Enterprise Agentgateway, in production the backend would typically be something like MCP Servers.

Example:

```
backendRefs:
- name: my-mcp-server
  port: 3000
```

Other common backends:

- LLM proxy services - Services that proxy requests to OpenAI, Anthropic, etc.
- Internal AI APIs - Your own ML/AI inference services
- Tool services - APIs that AI agents call to perform actions (database queries, file operations, etc.)

The OAuth flow protects these backends by ensuring only authenticated users can access them.

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: httpbin
  namespace: agentgateway-system
---
apiVersion: v1
kind: Service
metadata:
  name: httpbin
  namespace: agentgateway-system
spec:
  ports:
  - port: 8000
    targetPort: 8080
    name: http
  selector:
    app: httpbin
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: httpbin
  namespace: agentgateway-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: httpbin
  template:
    metadata:
      labels:
        app: httpbin
    spec:
      serviceAccountName: httpbin
      containers:
      - name: httpbin
        image: mccutchen/go-httpbin
        ports:
        - containerPort: 8080
EOF
```

## 2. Create a Gateway and HTTPRoute

```bash
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: agentgateway-extauth
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
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: agw-extauth-route
  namespace: agentgateway-system
spec:
  parentRefs:
  - name: agentgateway-extauth
    namespace: agentgateway-system
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: httpbin
      port: 8000
EOF
```

## 3. Create a Google OAuth Client

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Navigate to **APIs & Services** → **Credentials**
3. Click **Create Credentials** → **OAuth client ID**
4. Select **Web application**
5. Set **Authorized redirect URIs** to: `http://localhost:8080/callback`
6. Note your **Client ID** and **Client Secret**

## 4. Create a Kubernetes Secret

The ext-auth server expects the client secret under a key named `oauth`.

```bash
export CLIENT_ID=
export CLIENT_SECRET=
```

```bash
kubectl create secret generic google-oauth-secret \
  -n agentgateway-system \
  --from-literal=oauth=$CLIENT_SECRET
```

## 5. Create the AuthConfig

Google is OIDC-compliant, so ext-auth can automatically discover endpoints via `https://accounts.google.com/.well-known/openid-configuration`.

```
kubectl port-forward -n agentgateway-system svc/agentgateway-extauth 8080:8080
```

```bash
kubectl apply -f- <<EOF
apiVersion: extauth.solo.io/v1
kind: AuthConfig
metadata:
  name: oauth-google
  namespace: agentgateway-system
spec:
  configs:
    - oauth2:
        oidcAuthorizationCode:
          appUrl: http://localhost:8080
          callbackPath: /callback
          clientId: $CLIENT_ID
          clientSecretRef:
            name: google-oauth-secret
            namespace: agentgateway-system
          issuerUrl: https://accounts.google.com
          scopes:
            - email
            - profile
          session:
            cookieOptions:
              notSecure: true  # Set to false in production with HTTPS
EOF
```

## 6. Apply the EnterpriseAgentgatewayPolicy

```bash
kubectl apply -f- <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: oauth
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: agentgateway-extauth
  traffic:
    entExtAuth:
      authConfigRef:
        name: oauth-google
        namespace: agentgateway-system
      backendRef:
        name: ext-auth-service-enterprise-agentgateway
        namespace: agentgateway-system
        port: 8083
EOF
```

## 7. Testing

Verify resources are created:

```bash
kubectl get authconfig oauth-google -n agentgateway-system
kubectl get enterpriseagentgatewaypolicy oauth -n agentgateway-system
kubectl get pods -n agentgateway-system -l app=httpbin
```

## Test the OAuth flow

1. Make a request - you should be redirected to Google OAuth
```
curl -v $INGRESS_GW_ADDRESS:8080/
```

If OAuth is working, you'll see a `302` redirect to `https://accounts.google.com/o/oauth2/v2/auth`. Open the URL in a browser to complete the full OAuth flow.

You can click it, log in, etc. It won't go anywhere because there's technically nothing to log into, but this confirms that the oAuth flow works.

You can, however, confirm that the traffic did go through the extauth server.

```
kubectl logs -n agentgateway-system ext-auth-service-enterprise-agentgateway-PODNAME --tail=50 | grep googleusercontent
```

You see an output similar to the below:
```
{"level":"info","ts":"2026-01-29T04:44:24Z","logger":"ext-auth.ext-auth-service","msg":"received callback request","version":"0.71.4","client_id":"10077854408-mqjv2o89oqiri9rtctvivm5gcip2fv8k.apps.googleusercontent.com"}
```
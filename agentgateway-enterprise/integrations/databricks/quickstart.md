apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayBackend
metadata:
  name: ent-databricks-statements-openapi-backend
  namespace: agentgateway-system
spec:
  entMcp:
    targets:
    - name: ent-databricks-statements-openapi
      static:
        host: YOUR-DBC-INSTANCE.cloud.databricks.com
        port: 443
        protocol: OpenAPI
        openAPI:
          schemaRef:
            name: databricks-statements-openapi-schema
---
# 2. HTTPRoute
#    - Routes /databricks/statements/openapi/mcp and .well-known paths to EAGBE
#    - backendRef uses enterpriseagentgateway.solo.io group
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: databricks-statements-openapi-mcp
  namespace: agentgateway-system
spec:
  parentRefs:
  - name: agentgateway
  rules:
  - backendRefs:
    - group: enterpriseagentgateway.solo.io
      kind: EnterpriseAgentgatewayBackend
      name: ent-databricks-statements-openapi-backend
    matches:
    - path:
        type: PathPrefix
        value: /databricks/statements/openapi/mcp
    - path:
        type: PathPrefix
        value: /.well-known/oauth-protected-resource/databricks/statements/openapi/mcp
    - path:
        type: PathPrefix
        value: /.well-known/oauth-authorization-server/databricks/statements/openapi/mcp
---
# 3. EnterpriseAgentgatewayPolicy (TLS + CORS)
#    - Targets the HTTPRoute (not the backend)
#    - TLS for upstream HTTPS + CORS for browser/MCP clients
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: databricks-statements-openapi-policy
  namespace: agentgateway-system
spec:
  backend:
    tls: {}
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: databricks-statements-openapi-mcp
  traffic:
    cors:
      allowCredentials: false
      allowHeaders:
      - '*'
      allowMethods:
      - '*'
      allowOrigins:
      - '*'
      maxAge: 5
---
# 4. EnterpriseAgentgatewayPolicy (JWT Auth)
#    - JWT validation via Entra ID, targets EAGBE (requires CRD patch)
#    - Provides .well-known metadata + resourceMetadata for token exchange
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: databricks-statements-openapi-authn
  namespace: agentgateway-system
spec:
  backend:
    mcp:
      authentication:
        audiences:
        - api://<REDACTED>
        issuer: https://sts.windows.net/<REDACTED>/
        jwks:
          backendRef:
            group: agentgateway.dev
            kind: AgentgatewayBackend
            name: entra-jwks
          cacheDuration: 5m
          jwksPath: <REDACTED>/discovery/v2.0/keys
        mode: Strict
        resourceMetadata:
          agentgateway.dev/issuer-proxy: http://enterprise-agentgateway.agentgateway-system.svc.cluster.local:7777/oauth-issuer
          authorizationServers:
          - https://<MCP_GATEWAY_HOSTNAME>/databricks/statements/openapi/mcp
          resource: https://<MCP_GATEWAY_HOSTNAME>/databricks/statements/openapi/mcp
          scopesSupported:
          - api://<REDACTED>/agentgateway
  targetRefs:
  - group: enterpriseagentgateway.solo.io
    kind: EnterpriseAgentgatewayBackend
    name: ent-databricks-statements-openapi-backend
---
# 5. EnterpriseAgentgatewayPolicy (Token Exchange)
#    - OAuth token exchange for upstream Databricks auth
#    - Targets EnterpriseAgentgatewayBackend directly (requires CRD patch)
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: databricks-statements-openapi-exchange
  namespace: agentgateway-system
spec:
  backend:
    tokenExchange:
      elicitation:
        secretName: databricks-statements-openapi-token-exchange
  targetRefs:
  - group: enterpriseagentgateway.solo.io
    kind: EnterpriseAgentgatewayBackend
    name: ent-databricks-statements-openapi-backend
---
# 6. Secret - Databricks OAuth app credentials
#    - Registered at Databricks workspace dbc-c2685736-8254
#    - redirect_uri: https://<MCP_GATEWAY_HOSTNAME>/oauth-issuer/callback/upstream
#    - IMPORTANT: authorize_url and access_token_url MUST match the
#      workspace where the OAuth app is registered AND the EAGBE upstream host
apiVersion: v1
kind: Secret
metadata:
  name: databricks-statements-openapi-token-exchange
  namespace: agentgateway-system
type: Opaque
stringData:
  app_id: databricks
  client_id: "<REDACTED>"
  client_secret: "<REDACTED>"
  authorize_url: "https://dbc-c2685736-8254.cloud.databricks.com/oidc/v1/authorize"
  access_token_url: "https://dbc-c2685736-8254.cloud.databricks.com/oidc/v1/token"
  scopes: "all-apis offline_access"
  mcp_resource: "/databricks/statements/openapi/mcp"
---
# 7. ConfigMap - Databricks OpenAPI schema (truncated)
#    - Full schema contains Databricks REST API spec
#    - Referenced by EAGBE's spec.entMcp.targets[].openAPI.schemaRef
apiVersion: v1
kind: ConfigMap
metadata:
  name: databricks-statements-openapi-schema
  namespace: agentgateway-system
data:
  schema: |
    {"openapi":"3.0.3","info":{"title":"Databricks","description":"Databricks..."}, "...truncated -- full schema has Databricks REST API spec..."}
---
# 8. AgentgatewayBackend (OSS) - entra-jwks (SHARED)
#    - Azure AD JWKS endpoint for JWT key resolution
#    - Referenced by EAGPol authn's jwks.backendRef
#    - Shared across ALL backends using Entra ID authentication
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: entra-jwks
  namespace: agentgateway-system
spec:
  policies:
    tls: {}
  static:
    host: login.microsoftonline.com
    port: 443
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: databricks-elicitation-mcp
  namespace: agentgateway-system
spec:
  parentRefs:
  - name: agentgateway
  rules:
    - matches:
        - path:
            type: Exact
            value: /databricks/mcp  
        - path:
            type: Exact
            value: /.well-known/oauth-protected-resource/databricks/mcp  
        - path:
            type: Exact
            value: /.well-known/oauth-authorization-server/databricks/mcp                          
      backendRefs:
      - name: databricks-elicitation-mcp-backend
        group: agentgateway.dev
        kind: AgentgatewayBackend
---
# MCP Backend with multiple targets
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: databricks-elicitation-mcp-backend
  namespace: agentgateway-system
spec:
  mcp:
    targets:
      - name: databricks
        static:
          host: your-domain.cloud.databricks.com
          port: 443
          path: /api/2.0/mcp/genie/01f0c67c0cda1eb5b34096d638d3be44
          protocol: StreamableHTTP  # Explicitly set protocol
          policies:
            tls: {}  # Enable TLS for HTTPS backend (backendTLS equivalent)        
---
# Backend for Auth0 JWKS endpoint
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: auth0-elicitation-jwks
  namespace: agentgateway-system
spec:
  static:
    host: YOUR-HOST-solo.auth0.com
    port: 443
  policies:
    tls: {}     
---
# Policy for CORS, header modification, and backend TLS
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: databricks-elicitation-mcp-policy
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
      name: databricks-elicitation-mcp
        
  backend:
    mcp:
      authentication:
        mode: Strict
        issuer: https://YOUR-HOST-solo.auth0.com/
        audiences:
          - https://YOUR-HOST-agw.ngrok.io/mcp
        jwks:
          backendRef:
            name: auth0-elicitation-jwks
            kind: AgentgatewayBackend
            group: agentgateway.dev
          jwksPath: .well-known/jwks.json
        provider: Auth0
        resourceMetadata:
          authorizationServers:
            - https://YOUR-HOST-agw.ngrok.io/databricks/mcp
          resource: https://YOUR-HOST-agw.ngrok.io/databricks/mcp
          scopesSupported:
            - profile
            - openid
            - offline_access
          bearerMethodsSupported:
            - header
            - body
            - query
          resourceDocumentation: https://YOUR-HOST-agw.ngrok.io/databricks/mcp/docs
          resourcePolicyUri: https://YOUR-HOST-agw.ngrok.io/databricks/mcp/policies
  traffic:                           
    cors:
      allowOrigins:
        - "*"
      allowHeaders:
        - "*"
      allowMethods:
        - "*"
      allowCredentials: false
    headerModifiers:
      request:
        remove:
          - x-forwarded-for
          - x-forwarded-host
          - x-forwarded-proto
---
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: databricks-elicitation-mcp-exchange
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: agentgateway.dev
      kind: AgentgatewayBackend
      name: databricks-elicitation-mcp-backend
  backend:
    tokenExchange:
      elicitation:
        secretName: databricks-token-exchange
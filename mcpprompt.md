# Claude Code Prompt: MCP Security Demo with OAuth + agentgateway

## Objective

Create two complete, working demos that showcase MCP server security using OAuth authentication through agentgateway. One demo will use **Microsoft Entra ID** and the other will use **Auth0**. Both demos should be self-contained and easy to run for a workshop setting.

## Context

I'm building workshop demos to show how OAuth can secure MCP servers. The key architectural point is that **agentgateway sits between the MCP client (agent) and the MCP server**, validating JWT tokens and enforcing tool-level authorization based on claims.

The flow is:
1. User authenticates with the identity provider (Entra ID or Auth0)
2. Agent/client receives a JWT access token
3. Agent calls MCP tools through agentgateway with `Authorization: Bearer <token>`
4. agentgateway validates the JWT against the provider's JWKS endpoint
5. agentgateway evaluates authorization rules (CEL expressions) against JWT claims
6. If authorized, the request is forwarded to the MCP server

## Requirements

### Directory Structure

Create the following structure:

```
mcp-oauth-demos/
├── README.md                    # Overview and quick start for both demos
├── entra-id/
│   ├── README.md                # Entra ID specific setup instructions
│   ├── setup-entra.sh           # Script to guide Entra app registration
│   ├── agentgateway-config.yaml # agentgateway config for Entra
│   ├── docker-compose.yaml      # Optional: containerized setup
│   ├── test-client/             # Simple test client to demonstrate the flow
│   │   ├── index.html           # Browser-based OAuth flow demo
│   │   └── test-mcp.sh          # CLI script to test with a token
│   └── mcp-server/              # Simple MCP server with a few tools
│       └── server.py            # Python MCP server (or Node.js alternative)
├── auth0/
│   ├── README.md                # Auth0 specific setup instructions
│   ├── setup-auth0.sh           # Script to guide Auth0 app/API setup
│   ├── agentgateway-config.yaml # agentgateway config for Auth0
│   ├── docker-compose.yaml      # Optional: containerized setup
│   ├── test-client/
│   │   ├── index.html
│   │   └── test-mcp.sh
│   └── mcp-server/
│       └── server.py
└── shared/
    ├── mcp-server/              # Shared MCP server code (both demos can use)
    │   ├── server.py            # Python MCP server with demo tools
    │   ├── requirements.txt
    │   └── Dockerfile
    └── scripts/
        ├── generate-test-jwt.py # Utility to generate test JWTs for debugging
        └── decode-jwt.sh        # Utility to decode and inspect JWTs
```

### MCP Server Requirements

Create a simple MCP server with the following tools that demonstrate different authorization levels:

1. **`echo`** - Public tool, anyone can call (no auth required in demo mode, or any authenticated user)
2. **`get_user_info`** - Returns info about the authenticated user (from JWT claims)
3. **`list_files`** - Requires `files:read` scope
4. **`delete_file`** - Requires `files:delete` scope AND `role=admin` claim
5. **`system_status`** - Requires `role=admin` claim

This demonstrates:
- Public vs authenticated access
- Scope-based authorization
- Claim-based authorization (roles)
- Combining scopes and claims

### agentgateway Configuration

#### For Entra ID (`entra-id/agentgateway-config.yaml`):

```yaml
# agentgateway configuration for Microsoft Entra ID
version: "1"

binds:
  - port: 3000

listeners:
  - name: mcp-listener
    routes:
      - policies:
          cors:
            allowOrigins: ["*"]
            allowHeaders: ["*"]
          
          jwtAuth:
            mode: strict
            # Entra ID issuer format - PLACEHOLDER to be replaced
            issuer: "https://login.microsoftonline.com/{TENANT_ID}/v2.0"
            audiences: 
              - "{CLIENT_ID}"  # Your app's client ID
            jwks:
              # Entra ID JWKS endpoint
              url: "https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"
          
          mcpAuthorization:
            rules:
              # Public tool - any authenticated user
              - 'mcp.tool.name == "echo"'
              
              # Any authenticated user can get their own info
              - 'mcp.tool.name == "get_user_info"'
              
              # Requires files:read scope (check 'scp' claim for Entra)
              - 'mcp.tool.name == "list_files" && jwt.scp.contains("files.read")'
              
              # Requires files:delete scope AND admin role
              - 'mcp.tool.name == "delete_file" && jwt.scp.contains("files.delete") && jwt.roles.contains("admin")'
              
              # Requires admin role
              - 'mcp.tool.name == "system_status" && jwt.roles.contains("admin")'

        backends:
          - mcp:
              targets:
                - name: demo-mcp-server
                  sse:
                    url: "http://localhost:8080/sse"
```

#### For Auth0 (`auth0/agentgateway-config.yaml`):

```yaml
# agentgateway configuration for Auth0
version: "1"

binds:
  - port: 3000

listeners:
  - name: mcp-listener
    routes:
      - policies:
          cors:
            allowOrigins: ["*"]
            allowHeaders: ["*"]
          
          jwtAuth:
            mode: strict
            # Auth0 issuer format - PLACEHOLDER to be replaced
            issuer: "https://{AUTH0_DOMAIN}/"
            audiences: 
              - "{API_IDENTIFIER}"  # Your Auth0 API identifier
            jwks:
              url: "https://{AUTH0_DOMAIN}/.well-known/jwks.json"
          
          mcpAuthorization:
            rules:
              # Public tool - any authenticated user
              - 'mcp.tool.name == "echo"'
              
              # Any authenticated user can get their own info
              - 'mcp.tool.name == "get_user_info"'
              
              # Requires files:read scope
              - 'mcp.tool.name == "list_files" && jwt.scope.contains("files:read")'
              
              # Requires files:delete scope AND admin role (custom claim)
              - 'mcp.tool.name == "delete_file" && jwt.scope.contains("files:delete") && jwt["https://mcp-demo/roles"].contains("admin")'
              
              # Requires admin role (custom claim)
              - 'mcp.tool.name == "system_status" && jwt["https://mcp-demo/roles"].contains("admin")'

        backends:
          - mcp:
              targets:
                - name: demo-mcp-server
                  sse:
                    url: "http://localhost:8080/sse"
```

### Setup Scripts

#### `entra-id/setup-entra.sh`:

Create a guided script that:
1. Explains what needs to be configured in Azure Portal
2. Prompts for Tenant ID, Client ID after user creates the app registration
3. Explains how to configure API permissions/scopes (`files.read`, `files.delete`)
4. Explains how to create App Roles (`admin`, `user`)
5. Updates the agentgateway config with the actual values
6. Provides curl commands to test token acquisition (using device code flow for simplicity)

#### `auth0/setup-auth0.sh`:

Create a guided script that:
1. Explains what needs to be configured in Auth0 Dashboard
2. Prompts for Auth0 Domain and API Identifier
3. Explains how to create the API with scopes (`files:read`, `files:delete`)
4. Explains how to add custom claims via Auth0 Actions/Rules for roles
5. Updates the agentgateway config with the actual values
6. Provides test commands

### Test Client

Create a simple test client that can:
1. Obtain a token (browser-based for interactive demo, or use pre-obtained tokens)
2. Call the MCP server through agentgateway with the token
3. Show success/failure for different tools based on the token's claims

Include shell scripts that demonstrate:
```bash
# Test with a regular user token
./test-mcp.sh --token $USER_TOKEN --tool echo
./test-mcp.sh --token $USER_TOKEN --tool list_files  # Should fail without scope

# Test with an admin token
./test-mcp.sh --token $ADMIN_TOKEN --tool system_status  # Should succeed
```

### README Documentation

Each README should include:

1. **Overview** - What this demo shows
2. **Prerequisites** - What's needed (agentgateway binary, Python/Node, etc.)
3. **Architecture Diagram** - ASCII or Mermaid diagram showing the flow
4. **Step-by-Step Setup** - Detailed instructions
5. **Running the Demo** - How to start everything
6. **Demo Script** - Suggested talking points and commands to run during a live demo
7. **Troubleshooting** - Common issues and solutions
8. **Security Considerations** - What this demo simplifies vs production requirements

### Important Implementation Notes

1. **agentgateway JWKS fetching**: agentgateway can fetch JWKS from a URL. Use the provider's standard JWKS endpoint.

2. **Entra ID claim names**: 
   - Scopes are in the `scp` claim (space-separated string)
   - App roles are in the `roles` claim (array)
   - Use `preferred_username` or `email` for user identity

3. **Auth0 claim names**:
   - Scopes are in the `scope` claim (space-separated string)
   - Custom claims must be namespaced (e.g., `https://mcp-demo/roles`)
   - Requires an Auth0 Action to add custom claims

4. **CEL expression syntax in agentgateway**:
   - Access JWT claims with `jwt.claim_name`
   - For nested or namespaced claims, use `jwt["claim.name"]`
   - String contains: `jwt.scope.contains("value")`
   - Array contains: `jwt.roles.contains("admin")`
   - Combine with `&&` and `||`

5. **Token acquisition for demos**:
   - For Entra: Device Code flow is easiest for CLI demos
   - For Auth0: Use the Auth0 Dashboard "Test" feature or a simple SPA

6. **MCP Server**: Use Python with the `mcp` package or Node.js with `@modelcontextprotocol/sdk`. The server should:
   - Run on port 8080
   - Expose SSE endpoint at `/sse`
   - Log incoming requests and the user identity from JWT (passed through by agentgateway if configured)

### Deliverables Checklist

- [ ] Root README.md with overview of both demos
- [ ] Entra ID demo fully working with all files
- [ ] Auth0 demo fully working with all files
- [ ] Shared MCP server that both demos use
- [ ] Setup scripts that guide configuration
- [ ] Test scripts that demonstrate authorization working
- [ ] Clear documentation for workshop presentation

### Workshop Flow Suggestion

The demos should support this narrative:

1. "Here's an MCP server with several tools of varying sensitivity"
2. "Without security, any agent can call any tool"
3. "Let's add OAuth - here's how it works with [Entra/Auth0]"
4. "agentgateway sits in the middle and validates tokens"
5. "Watch what happens when a regular user tries to call admin tools"
6. "Now with an admin token, those tools are accessible"
7. "This is how you implement least-privilege for MCP"

## Additional Context

- I have agentgateway available and am familiar with configuring it
- **The demos MUST run in Kubernetes** - this is critical as the workshop is about agentic AI meeting Kubernetes
- Audience is technical but may not be deeply familiar with OAuth internals
- The goal is to show the pattern in a cloud-native context

## Kubernetes Deployment Requirements

All components should be deployed to Kubernetes with proper manifests:

### Directory Structure Update

```
mcp-oauth-demos/
├── README.md
├── entra-id/
│   ├── README.md
│   ├── setup-entra.sh              # Guide for Entra app registration
│   ├── k8s/
│   │   ├── namespace.yaml
│   │   ├── mcp-server-deployment.yaml
│   │   ├── mcp-server-service.yaml
│   │   ├── agentgateway-configmap.yaml   # agentgateway config as ConfigMap
│   │   ├── agentgateway-deployment.yaml
│   │   ├── agentgateway-service.yaml
│   │   ├── secrets.yaml            # Template for client secrets (not committed)
│   │   └── kustomization.yaml      # For easy deployment
│   └── test-client/
│       └── test-mcp.sh
├── auth0/
│   ├── README.md
│   ├── setup-auth0.sh
│   ├── k8s/
│   │   ├── namespace.yaml
│   │   ├── mcp-server-deployment.yaml
│   │   ├── mcp-server-service.yaml
│   │   ├── agentgateway-configmap.yaml
│   │   ├── agentgateway-deployment.yaml
│   │   ├── agentgateway-service.yaml
│   │   ├── secrets.yaml
│   │   └── kustomization.yaml
│   └── test-client/
│       └── test-mcp.sh
└── shared/
    ├── mcp-server/
    │   ├── server.py
    │   ├── requirements.txt
    │   └── Dockerfile
    └── base/                        # Base Kustomize resources
        ├── mcp-server-deployment.yaml
        └── kustomization.yaml
```

### Kubernetes Architecture: kgateway + agentgateway

This demo uses the **kgateway** stack where:
- **kgateway** is the Kubernetes-native control plane (CRDs, operators)
- **agentgateway** is the data plane that handles traffic
- Configuration is done via Kubernetes CRDs, not static config files

### Directory Structure Update (kgateway-native)

```
mcp-oauth-demos/
├── README.md
├── prerequisites/
│   ├── install-kgateway.sh         # Install kgateway + agentgateway
│   └── verify-installation.sh
├── entra-id/
│   ├── README.md
│   ├── setup-entra.sh              # Guide for Entra app registration
│   ├── k8s/
│   │   ├── namespace.yaml
│   │   ├── mcp-server-deployment.yaml
│   │   ├── mcp-server-service.yaml
│   │   ├── gateway.yaml            # Gateway CRD for agentgateway listener
│   │   ├── mcp-target.yaml         # MCPTarget CRD pointing to MCP server
│   │   ├── gloo-traffic-policy.yaml # GlooTrafficPolicy with JWT + RBAC
│   │   ├── secrets.yaml.template   # Template for JWKS or client secrets
│   │   └── kustomization.yaml
│   └── test-client/
│       └── test-mcp.sh
├── auth0/
│   ├── README.md
│   ├── setup-auth0.sh
│   ├── k8s/
│   │   ├── namespace.yaml
│   │   ├── mcp-server-deployment.yaml
│   │   ├── mcp-server-service.yaml
│   │   ├── gateway.yaml
│   │   ├── mcp-target.yaml
│   │   ├── gloo-traffic-policy.yaml
│   │   ├── secrets.yaml.template
│   │   └── kustomization.yaml
│   └── test-client/
│       └── test-mcp.sh
└── shared/
    ├── mcp-server/
    │   ├── server.py
    │   ├── requirements.txt
    │   └── Dockerfile
    └── scripts/
        ├── get-test-token-entra.sh
        └── get-test-token-auth0.sh
```

### kgateway CRD Examples

#### Gateway CRD (`gateway.yaml`):

```yaml
apiVersion: gateway.kgateway.dev/v1
kind: Gateway
metadata:
  name: mcp-gateway
  namespace: mcp-demo-entra
spec:
  listeners:
    - name: mcp
      port: 3000
      protocol: HTTP
```

#### MCPTarget CRD (`mcp-target.yaml`):

```yaml
apiVersion: gateway.kgateway.dev/v1alpha1
kind: MCPTarget
metadata:
  name: demo-mcp-server
  namespace: mcp-demo-entra
spec:
  # Reference to the MCP server running in the cluster
  backend:
    service:
      name: mcp-server
      port: 8080
  # SSE transport
  transport: sse
```

#### GlooTrafficPolicy for JWT + MCP Authorization (`gloo-traffic-policy.yaml` for Entra):

```yaml
apiVersion: gateway.kgateway.dev/v1alpha1
kind: GlooTrafficPolicy
metadata:
  name: mcp-oauth-policy
  namespace: mcp-demo-entra
spec:
  targetRefs:
    - group: gateway.kgateway.dev
      kind: Gateway
      name: mcp-gateway
  policy:
    # JWT validation configuration
    glooJWT:
      providers:
        entra:
          issuer: "https://login.microsoftonline.com/{TENANT_ID}/v2.0"
          audiences:
            - "{CLIENT_ID}"
          jwks:
            remote:
              url: "https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"
              cacheDuration: 5m
    
    # MCP-specific authorization rules using CEL
    mcpAuthorization:
      rules:
        # Public tool - any authenticated user
        - 'mcp.tool.name == "echo"'
        
        # Any authenticated user can get their own info
        - 'mcp.tool.name == "get_user_info"'
        
        # Requires files.read scope (Entra uses 'scp' claim)
        - 'mcp.tool.name == "list_files" && jwt.scp.contains("files.read")'
        
        # Requires files.delete scope AND admin role
        - 'mcp.tool.name == "delete_file" && jwt.scp.contains("files.delete") && jwt.roles.contains("admin")'
        
        # Requires admin role only
        - 'mcp.tool.name == "system_status" && jwt.roles.contains("admin")'
```

#### GlooTrafficPolicy for Auth0:

```yaml
apiVersion: gateway.kgateway.dev/v1alpha1
kind: GlooTrafficPolicy
metadata:
  name: mcp-oauth-policy
  namespace: mcp-demo-auth0
spec:
  targetRefs:
    - group: gateway.kgateway.dev
      kind: Gateway
      name: mcp-gateway
  policy:
    glooJWT:
      providers:
        auth0:
          issuer: "https://{AUTH0_DOMAIN}/"
          audiences:
            - "{API_IDENTIFIER}"
          jwks:
            remote:
              url: "https://{AUTH0_DOMAIN}/.well-known/jwks.json"
              cacheDuration: 5m
    
    mcpAuthorization:
      rules:
        - 'mcp.tool.name == "echo"'
        - 'mcp.tool.name == "get_user_info"'
        - 'mcp.tool.name == "list_files" && jwt.scope.contains("files:read")'
        - 'mcp.tool.name == "delete_file" && jwt.scope.contains("files:delete") && jwt["https://mcp-demo/roles"].contains("admin")'
        - 'mcp.tool.name == "system_status" && jwt["https://mcp-demo/roles"].contains("admin")'
```

### Testing from Outside the Cluster

Include instructions for:
1. Port-forwarding the gateway: `kubectl port-forward svc/mcp-gateway 3000:3000 -n mcp-demo-entra`
2. Or using an Ingress/LoadBalancer for the Gateway
3. Test scripts that work against the exposed endpoint

### Workshop Demo Flow (kgateway-native)

1. Show kgateway is installed: `kubectl get pods -n kgateway-system`
2. Deploy the MCP server: `kubectl apply -f mcp-server-deployment.yaml`
3. Create the Gateway: `kubectl apply -f gateway.yaml` - "This spins up agentgateway as the data plane"
4. Create the MCPTarget: `kubectl apply -f mcp-target.yaml` - "This tells agentgateway about our MCP server"
5. Apply the traffic policy: `kubectl apply -f gloo-traffic-policy.yaml` - "This is where the OAuth magic happens"
6. Show the resources: `kubectl get gateway,mcptarget,glootrafficpolicy -n mcp-demo-entra`
7. Port-forward and test with different tokens
8. Show logs: `kubectl logs -l app=agentgateway -n mcp-demo-entra` - token validation in action
9. **Live policy update**: Modify the GlooTrafficPolicy to change rules, apply it, show immediate effect - "No restart needed, kgateway pushes the config to agentgateway"

### Key Differences from Standalone agentgateway

| Standalone agentgateway | kgateway + agentgateway |
|------------------------|-------------------------|
| Static YAML config file | Kubernetes CRDs |
| Manual restart for config changes | Dynamic config push via control plane |
| Single instance | Scaled by Kubernetes |
| Manual deployment | Operator-managed lifecycle |
| Config in ConfigMap | Config in GlooTrafficPolicy, MCPTarget CRDs |

This approach shows the audience the **Kubernetes-native way** to manage MCP security, which is the whole point of kagent/kgateway

This Kubernetes-native approach reinforces the workshop theme of "Agentic AI Meets Kubernetes" and shows the audience patterns they can directly apply in their own clusters.

Please create all the files needed for these demos. Start with the shared MCP server and Dockerfile, then build out the Kubernetes manifests for the Entra ID demo, then the Auth0 demo. Make sure everything is well-documented and easy to follow.

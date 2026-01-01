# MCP OAuth Security Demos

Demos for securing MCP servers with OAuth authentication using kgateway/agentgateway on Kubernetes. Includes examples for both **Microsoft Entra ID** and **Auth0**.

**IGNORE ALL THINGS MICROSOFT ENTRA ID IN THIS README**. Entra ID is currently in WIP

## Project Structure

```
mcp-oauth-demos/
├── prerequisites/         # kgateway installation scripts
├── entra-id/              # Microsoft Entra ID demo
│   ├── setup.md           # Setup instructions
│   ├── k8s/               # Kubernetes manifests
├── auth0/                 # Auth0 demo
│   ├── setup.md           # Setup instructions
│   ├── k8s/               # Kubernetes manifests
└── shared/
    ├── mcp-server/        # Python MCP server (Streamable HTTP)
    └── scripts/           # Token helpers
```

## What This Does

Shows how agentgateway can validate JWT tokens and enforce tool-level authorization for MCP servers:
- `echo`, `get_user_info` - Any authenticated user
- `list_files` - Requires `files:read` scope
- `delete_file` - Requires `files:delete` scope AND `admin` role
- `system_status` - Requires `admin` role

## Prerequisites

- Kubernetes cluster
- kubectl and helm installed
- Docker
- jq

## Quick Start

### 1. Set Up Identity Provider

For each provider (auth0 or Entra) there is a `setup.md`. You'll need to set up your provider so you can pass in the domain and API ID.

**For Entra ID:** Follow [entra-id/SETUP.md](entra-id/SETUP.md)

**For Auth0:** Follow [auth0/SETUP.md](auth0/SETUP.md)

### 2. Install kgateway/agentgateway

1. Install OSS or Enterprise kgateway/agentgateway

### 3. Build the MCP Server

```
cd ../shared/mcp-server
docker build -t mcp-oauth-demo:latest --platform=linux/amd64 .
```

```
docker tag mcp-oauth-demo:latest YOUR_REGISTRY/mcp-oauth-demo:latest
```

```
docker push YOUR_REGISTRY/mcp-oauth-demo:latest
```

### 4. Deploy to Kubernetes

#### For Auth0
```
kubectl apply -k auth0/k8s/
```

#### For EntraID
```
kubectl apply -k entraid/k8s/
```

5. ### Test Without Auth

1. Open MCP Inspector
```
npx modelcontextprotocol/inspector#0.16.2
```

2. Put in `http://ALB_PUB_IP:3000/mcp` and click **Connect**

You should be able to see all of your tools.

![](images/5.png)

### 6. Set Up MCP oAuth
Edit and replace:
- `{AUTH0_DOMAIN}` with your Auth0 domain (e.g., `your-tenant.us.auth0.com`)
- `{API_IDENTIFIER}` with your API identifier (e.g., `https://mcp-oauth-demo`)

1. Set the following env variables:
```
export AUTH0_DOMAIN=YOUR_DOMAIN.us.auth0.com
export API_IDENTIFIER=https://mcp-oauth-demo
```

2. Deploy the Auth0 JWKS proxy service (required for agentgateway to fetch JWKS from Auth0). Before applying the config, you'll have to open the `auth0-jwks-proxy.yaml` and add in your `proxy_pass` on line 17 and `proxy_set_header` on line 19
```bash
kubectl apply -f auth0/k8s/auth0-jwks-proxy.yaml
```

3. Apply the Traffic Policy to route traffic for agentgateway to authenticate via your oAuth provider.

Notice the MCP Server tools that are available and not available when you apply this policy.
```bash
cat <<EOF | kubectl apply -f -
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: mcp-oauth-policy
  namespace: agentgateway-system
  labels:
    app: mcp-gateway
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: mcp-gateway
  traffic:
    cors:
      allowOrigins:
        - "*"
      allowMethods:
        - GET
        - POST
        - OPTIONS
      allowHeaders:
        - "*"
      exposeHeaders:
        - "*"
      maxAge: 86400
    jwtAuthentication:
      providers:
        - issuer: "https://${AUTH0_DOMAIN}/"
          audiences:
            - "${API_IDENTIFIER}"
          jwks:
            remote:
              jwksPath: ".well-known/jwks.json"
              backendRef:
                group: ""
                kind: Service
                name: auth0-jwks
                namespace: agentgateway-system
                port: 8443
  backend:
    mcp:
      authorization:
        action: Allow
        policy:
          matchExpressions:
            # Public tool - any authenticated user can call
            - 'mcp.tool.name == "echo"'

            # Any authenticated user can get their own info
            - 'mcp.tool.name == "get_user_info"'

            # Requires files:read scope
            # Auth0 scopes are in the 'scope' claim as a space-separated string
            - 'mcp.tool.name == "list_files" && jwt.scope.contains("files:read")'

            # Requires files:delete scope AND admin role (custom claim)
            # Auth0 custom claims must be namespaced (e.g., https://mcp-demo/roles)
            # Access namespaced claims using bracket notation: jwt["claim-name"]
            - 'mcp.tool.name == "delete_file" && jwt.scope.contains("files:delete") && jwt["https://mcp-demo/roles"].contains("admin")'

            # Requires admin role only (custom claim)
            - 'mcp.tool.name == "system_status" && jwt["https://mcp-demo/roles"].contains("admin")'
EOF
```

### 7. Test With MCP Auth

There are scripts to get a test auth0 token and a test entraid token. Those are the scripts that you would run to get a token to authenticate to an MCP server from a client like MCP inspector.

1. Run the script (e.g., ./get-test-token-entra.sh)
2. It gives you a URL and code to enter in your browser
3. You authenticate with your identity provider
4. The script outputs the JWT token

You'd then use that token as a Bearer token in the Authorization header (`Authorization: Bearer <your_token>`) when connecting to the MCP server through agentgateway

```
cd ../shared/scripts
```

```
/get-test-token-auth0.sh
```

# Test tools

1. Open MCP Inspector
```
npx modelcontextprotocol/inspector#0.16.2
```

2. Add in the URL via Streamable HTTP
```
http://ALB_PUB_IP:3000/mcp
```

![](images/1.png)

3. Click **Connect**

You'll see an error similiar to the image below on the terminal

![](images/2.png)

4. Open **Authentication**

Type in `YOUR_TOKEN`

![](images/3.png)

You should now be able to connect and see the tools based on your permissions

![](images/4.png)
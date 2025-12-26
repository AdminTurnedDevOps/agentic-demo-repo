# MCP OAuth Security Demos

Demos for securing MCP servers with OAuth authentication using kgateway/agentgateway on Kubernetes. Includes examples for both **Microsoft Entra ID** and **Auth0**.

## What This Does

Shows how agentgateway can validate JWT tokens and enforce tool-level authorization for MCP servers:
- `echo`, `get_user_info` - Any authenticated user
- `list_files` - Requires `files:read` scope
- `delete_file` - Requires `files:delete` scope AND `admin` role
- `system_status` - Requires `admin` role

## Prerequisites

- Kubernetes cluster (minikube, kind, EKS, etc.)
- kubectl and helm installed
- Docker
- jq

## Quick Start

### 1. Install kgateway

```
cd prerequisites

./install-kgateway.md
```

### 2. Build the MCP Server

```
cd ../shared/mcp-server
docker build -t mcp-oauth-demo:latest .
```

### 3. Configure Identity Provider

**For Entra ID:**
```bash
cd ../../entra-id
./setup-entra.sh
```

**For Auth0:**
```bash
cd ../../auth0
./setup-auth0.sh
```

### 4. Deploy to Kubernetes

```bash
kubectl apply -k k8s/
```

### 5. Test

There are scripts to get a test auth0 token and a test entraid token. Those are the scripts that you would run to get a token to authenticate to an MCP server from a client like MCP inspector.

1. Run the script (e.g., ./get-test-token-entra.sh)
2. It gives you a URL and code to enter in your browser
3. You authenticate with your identity provider
4. The script outputs the JWT token

You'd then use that token as a Bearer token in the Authorization header when connecting to the MCP server through agentgateway

```
cd ../shared/scripts
```

```
./get-test-token-entra.sh
```
OR

```/get-test-token-auth0.sh
```

# Test tools
cd ../../entra-id/test-client  # or ../../auth0/test-client
./test-mcp.sh --token $TOKEN --tool echo
./test-mcp.sh --token $TOKEN --tool system_status  # Will fail without admin role
```

## Project Structure

```
mcp-oauth-demos/
├── prerequisites/          # kgateway installation scripts
├── entra-id/              # Microsoft Entra ID demo
│   ├── setup-entra.sh     # Setup wizard
│   ├── k8s/               # Kubernetes manifests
│   └── test-client/       # Test scripts
├── auth0/                 # Auth0 demo
│   ├── setup-auth0.sh     # Setup wizard
│   ├── k8s/               # Kubernetes manifests
│   └── test-client/       # Test scripts
└── shared/
    ├── mcp-server/        # Python MCP server (Streamable HTTP)
    └── scripts/           # Token helpers
```

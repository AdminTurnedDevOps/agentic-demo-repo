# Claude Desktop with AgentGateway

Route MCP server traffic from Claude Desktop through the agentgateway for security, observability, and rate limiting.

## Prerequisites

- Claude Desktop installed
- AgentGateway deployed and running (see [agentgateway-enterprise/setup.md](../../agentgateway-enterprise/setup.md))

## Deploy MCP Servers

1. MCP Server number one:
```
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-math-script
  namespace: default
data:
  server.py: |
    import uvicorn
    from mcp.server.fastmcp import FastMCP
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response

    mcp = FastMCP("Math-Service")

    @mcp.tool()
    def add(a: int, b: int) -> int:
        return a + b

    @mcp.tool()
    def multiply(a: int, b: int) -> int:
        return a * b

    async def handle_mcp(request: Request):
        try:
            data = await request.json()
            method = data.get("method")
            msg_id = data.get("id")
            result = None
            
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "Math-Service", "version": "1.0"}
                }
            
            elif method == "notifications/initialized":
                # Notifications are fire-and-forget, return empty 202 response
                return Response(status_code=202)

            elif method == "tools/list":
                tools_list = await mcp.list_tools()
                result = {
                    "tools": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": t.inputSchema
                        } for t in tools_list
                    ]
                }

            elif method == "tools/call":
                params = data.get("params", {})
                name = params.get("name")
                args = params.get("arguments", {})
                
                # Call the tool
                tool_result = await mcp.call_tool(name, args)
                
                # --- FIX: Serialize the content objects manually ---
                serialized_content = []
                for content in tool_result:
                    if hasattr(content, "type") and content.type == "text":
                        serialized_content.append({"type": "text", "text": content.text})
                    elif hasattr(content, "type") and content.type == "image":
                         serialized_content.append({
                             "type": "image", 
                             "data": content.data, 
                             "mimeType": content.mimeType
                         })
                    else:
                        # Fallback for dictionaries or other types
                        serialized_content.append(content if isinstance(content, dict) else str(content))

                result = {
                    "content": serialized_content,
                    "isError": False
                }

            elif method == "ping":
                result = {}

            else:
                return JSONResponse(
                    {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "Method not found"}},
                    status_code=404
                )

            return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "result": result})

        except Exception as e:
            # Print error to logs for debugging
            import traceback
            traceback.print_exc()
            return JSONResponse(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}},
                status_code=500
            )

    app = Starlette(routes=[
        Route("/mcp", handle_mcp, methods=["POST"]),
        Route("/", lambda r: JSONResponse({"status": "ok"}), methods=["GET"])
    ])

    if __name__ == "__main__":
        print("Starting Fixed Math Server on port 8000...")
        uvicorn.run(app, host="0.0.0.0", port=8000)
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-math-server
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mcp-math-server
  template:
    metadata:
      labels:
        app: mcp-math-server
    spec:
      containers:
      - name: math
        image: python:3.11-slim
        command: ["/bin/sh", "-c"]
        args:
        - |
          pip install "mcp[cli]" uvicorn starlette && 
          python /app/server.py
        ports:
        - containerPort: 8000
        volumeMounts:
        - name: script-volume
          mountPath: /app
        readinessProbe:
          httpGet:
            path: /
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
      volumes:
      - name: script-volume
        configMap:
          name: mcp-math-script
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-math-server
  namespace: default
spec:
  selector:
    app: mcp-math-server
  ports:
  - port: 80
    targetPort: 8000
EOF
```

## Gateway/Backend Setup

1. Create a Gateway
```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: agentgateway-mcp
  namespace: gloo-system
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
  - name: http
    port: 8080
    protocol: HTTP
    allowedRoutes:
      namespaces:
        from: Same
EOF
```

2. Create a Backend with two MCP Servers
```
kubectl apply -f - <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: demo-mcp-server
  namespace: gloo-system
spec:
  mcp:
    targets:
      - name: demo-mcp-server
        static:
          host: mcp-math-server.default.svc.cluster.local
          port: 80
          path: /mcp
          protocol: StreamableHTTP
EOF
```

3. Create the HTTPRoute
```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: mcp-route
  namespace: gloo-system
spec:
  parentRefs:
  - name: agentgateway-mcp
  rules:
  - backendRefs:
    - name: demo-mcp-server
      namespace: gloo-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```

5. Test the Gateway/route
```
export GATEWAY_IP=$(kubectl get svc agentgateway-mcp -n gloo-system -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo $GATEWAY_IP
```

```
npx modelcontextprotocol/inspector#0.16.2
```

URL to put into Inspector: `http://YOUR_ALB_LB_IP:8080/mcp`

## Configure Claude Desktop

The Claude Desktop config file location:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

### Basic Configuration (No Auth)

If the config file doesn't exist, create it:

**macOS**:
```bash
mkdir -p ~/Library/Application\ Support/Claude
cat > ~/Library/Application\ Support/Claude/claude_desktop_config.json << 'EOF'
{
  "mcpServers": {
    "math-service": {
      "command": "npx",
      "args": ["-y", "supergateway", "--streamableHttp", "http://34.75.119.135:8080/mcp"]
    }
  }
}
EOF
```

Replace `YOUR_GATEWAY_IP` with your actual gateway IP.

After saving the config, restart Claude Desktop for changes to take effect.

## Verify Connection

1. Open Claude Desktop
2. Check that the MCP server tools are available
3. Test a tool call to verify traffic flows through the gateway

### With JWT Authentication

If you've configured JWT auth on the gateway (see [mcp-security/setup.md](../../agentgateway-enterprise/mcp-security/setup.md#secure-connectivity-with-jwt)):

```json
{
  "mcpServers": {
    "math-service": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://YOUR_GATEWAY_IP:8080/mcp"],
      "env": {
        "MCP_HEADERS": "Authorization: Bearer <your-jwt-token>"
      }
    }
  }
}
```

## What This Enables

- **JWT Authentication**: Secure access to MCP servers
- **RBAC for Tools**: Control which tools are accessible per user/token
- **Observability**: Monitor and trace MCP tool calls
- **Rate Limiting**: Control usage and costs

## Limitations

Claude Desktop's core LLM API traffic (conversations with Claude) cannot be routed through the agentgateway. Only MCP server traffic is proxied.

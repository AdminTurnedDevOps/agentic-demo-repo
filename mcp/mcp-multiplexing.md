# Multiplexing Demo

This demo will use a backend object that has the type of `static` for MCP Servers so there is a fixed set of tools vs a dynamic configuration that could create tools on the fly based on introspecting data.

There will be two MCP Servers:
- One that lives in Kubernetes
- One that is a `stdio` type, so its local


## Prereqs

Ensure to do the following prerequisites:
- Install agentgateway first. You can find the installation docs [here](https://github.com/AdminTurnedDevOps/agentic-demo-repo/blob/main/agentgateway-enterprise/setup.md)

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
    from starlette.responses import JSONResponse

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
                return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "result": True})

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

2. MCP Server number two:
```
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-date-script
  namespace: default
data:
  server.py: |
    import uvicorn
    import datetime
    from mcp.server.fastmcp import FastMCP
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    mcp = FastMCP("Date-Service")

    @mcp.tool()
    def get_current_date() -> str:
        """Returns the current date in ISO format (YYYY-MM-DD)."""
        return datetime.date.today().isoformat()

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
                    "serverInfo": {"name": "Date-Service", "version": "1.0"}
                }
            elif method == "notifications/initialized":
                return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "result": True})
            elif method == "tools/list":
                tools_list = await mcp.list_tools()
                result = {
                    "tools": [{"name": t.name, "description": t.description, "inputSchema": t.inputSchema} for t in tools_list]
                }
            elif method == "tools/call":
                params = data.get("params", {})
                
                # 1. Call the tool
                tool_result = await mcp.call_tool(params.get("name"), params.get("arguments", {}))
                
                # 2. FIX: Manually Serialize the Pydantic Objects
                serialized_content = []
                for content in tool_result:
                    # Check if it's the TextContent object causing the crash
                    if hasattr(content, "type") and content.type == "text":
                        serialized_content.append({"type": "text", "text": content.text})
                    elif isinstance(content, dict):
                        serialized_content.append(content)
                    else:
                        serialized_content.append(str(content))

                result = {"content": serialized_content, "isError": False}

            elif method == "ping":
                result = {}
            else:
                return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "Method not found"}}, status_code=404)

            return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "result": result})

        except Exception as e:
            # Catch serialization errors and print them
            import traceback
            traceback.print_exc()
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}, status_code=500)

    app = Starlette(routes=[
        Route("/mcp", handle_mcp, methods=["POST"]),
        Route("/", lambda r: JSONResponse({"status": "ok"}), methods=["GET"])
    ])

    if __name__ == "__main__":
        print("Starting Fixed Date Server...")
        uvicorn.run(app, host="0.0.0.0", port=8000)
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-date-server
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mcp-date-server
  template:
    metadata:
      labels:
        app: mcp-date-server
    spec:
      containers:
      - name: date-server
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
          name: mcp-date-script
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-date-server
  namespace: default
spec:
  selector:
    app: mcp-date-server
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
  name: agentgateway
  namespace: gloo-system
spec:
  gatewayClassName: agentgateway-enterprise
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
apiVersion: gateway.kgateway.dev/v1alpha1
kind: Backend
metadata:
  name: mcp-backend
  namespace: gloo-system
spec:
  type: MCP
  mcp:
    targets:
    - name: math-mcp-server
      static:
        host: mcp-math-server.default.svc.cluster.local
        port: 80
        protocol: StreamableHTTP
    - name: date-mcp-server
      static:
        host: mcp-date-server.default.svc.cluster.local
        port: 80
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
  - name: agentgateway
  rules:
  - backendRefs:
    - name: mcp-backend
      group: gateway.kgateway.dev
      kind: Backend
EOF
```

5. Test the Gateway/route
```
export GATEWAY_IP=$(kubectl get svc agentgateway -n gloo-system -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo $GATEWAY_IP
```

```
npx modelcontextprotocol/inspector#0.16.2
```

URL to put into Inspector: `http://YOUR_ALB_LB_IP:8080/mcp`
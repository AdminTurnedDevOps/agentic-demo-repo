# Stateless MCP

Tldr; MCP Stateless eliminates initialization handshakes and session IDs to allow simple request/response scaling on standard cloud infrastructure. The "Mcp-Session-Id" is not required for stateless Model Context Protocol (MCP) requests. Instead, requests carry their own metadata, context, and protocol version directly.

## What Stateless Brings

The removal of initialization handshakes and session IDs.

An initialization handshake was the startup exchange used by MCP versions through 2025-11-25:

1. Client sends an initialize request containing its protocol version, capabilities, and client information.
2. Server returns an InitializeResult with the negotiated version, server capabilities, and server information. It could also return MCP-Session-Id.
3. Client sends notifications/initialized.
4. Normal MCP requests begin.

It established what features both sides supported before tools or resources were used.

In MCP 2026-07-28, this handshake was removed. Each request instead carries its protocol version and client metadata, making requests independently processable and stateless.

Session IDs were removed as anything with a session ID is stateful because that ID serves as a lookup key for data stored on a server or database.

## Header Setup


MCP headers that mirror request metadata like:
- MCP-Protocol-Version
- Mcp-Method
- Mcp-Name
- Mcp-Param-*

Must match its corresponding JSON-RPC body field.

Example:
```
POST /mcp HTTP/1.1
Content-Type: application/json
Accept: application/json, text/event-stream
MCP-Protocol-Version: 2026-07-28
Mcp-Method: tools/call
Mcp-Name: get_weather

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "get_weather",
    "arguments": {
      "location": "Seattle, WA"
    },
    "_meta": {
      "io.modelcontextprotocol/protocolVersion": "2026-07-28",
      "io.modelcontextprotocol/clientInfo": {
        "name": "example-client",
        "version": "1.0.0"
      },
      "io.modelcontextprotocol/clientCapabilities": {}
    }
  }
}
```

## Setup

Three objects:
1. `Gateway`
2. `AgentgatewayBackend`
3. `HTTPRoute`

```
export GITHUB_PAT=

kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: github-pat
  namespace: agentgateway-system
type: Opaque
stringData:
  Authorization: "Bearer ${GITHUB_PAT}"
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: mcp-gateway
  namespace: agentgateway-system
  labels:
    app: github-mcp-server
spec:
  gatewayClassName: agentgateway
  listeners:
    - name: mcp
      port: 3000
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: github-mcp-server
  namespace: agentgateway-system
spec:
  mcp:
    sessionRouting: Stateless
    targets:
      - name: github-copilot
        static:
          host: api.githubcopilot.com
          port: 443
          path: /mcp/
          protocol: StreamableHTTP
          policies:
            tls: {}
            auth:
              secretRef:
                name: github-pat
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: mcp-route
  namespace: agentgateway-system
  labels:
    app: github-mcp-server
spec:
  parentRefs:
    - name: mcp-gateway
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /mcp
      backendRefs:
        - name: github-mcp-server
          namespace: agentgateway-system
          group: agentgateway.dev
          kind: AgentgatewayBackend
EOF
```

```
export GATEWAY_IP=$(kubectl get svc mcp-gateway -n agentgateway-system -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo $GATEWAY_IP
```

```
npx modelcontextprotocol/inspector#0.18.0
```

use `http://$GATEWAY_IP:3000/mcp`
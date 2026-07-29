Using the Code Mode backend translates non-MCP tools into MCP-looking tools so Agents can use them. Code Mode is used to interact with tools/APIs that aren't MCP Servers/tools, but you still want to use them in your agentic workflow, so it "translates" them to look like mcp server tools so they can be used by your Agents. The protocol bridge is OpenAPI.

1. Create a gateway for your traffic to route through
```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: codemode-gateway
  namespace: agentgateway-system
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
    - name: mcp
      port: 80
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
EOF
```

2. Create a `ConfigMap` that calls out to the Geocoding API
```
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: open-meteo-geocoding-openapi
  namespace: agentgateway-system
data:
  openapi.json: |
    {
      "openapi": "3.0.0",
      "info": { "title": "Open-Meteo Geocoding", "version": "1.0.0" },
      "servers": [{ "url": "https://geocoding-api.open-meteo.com/v1" }],
      "paths": {
        "/search": {
          "get": {
            "operationId": "geocode_city",
            "description": "Resolve a city name to latitude/longitude and country.",
            "parameters": [
              { "name": "name", "in": "query", "required": true,
                "schema": { "type": "string" },
                "description": "City name, e.g. \"Paris\"." },
              { "name": "count", "in": "query", "required": false,
                "schema": { "type": "integer", "default": 1 },
                "description": "Max results to return." }
            ],
            "responses": { "200": { "description": "OK" } }
          }
        }
      }
    }
EOF
```

3. Implement a backend that uses the OpenAPI format spec and a static host target to call the the Geocoding API endpoint.

```
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayBackend
metadata:
  name: geocoding-code-mode
  namespace: agentgateway-system
spec:
  entMcp:
    toolMode: Code
    codeMode:
      timeout: 10s 
    targets:
      - name: geocoding
        static:
          host: geocoding-api.open-meteo.com
          port: 443
          protocol: OpenAPI
          openAPI:
            schemaRef:
              name: open-meteo-geocoding-openapi
          policies:
            tls: {}
EOF
```

4. Create a route to said Geocoding endpoint
```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: geocoding-mcp
  namespace: agentgateway-system
spec:
  parentRefs:
    - name: codemode-gateway
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /mcp/geocoding
      backendRefs:
        - group: enterpriseagentgateway.solo.io
          kind: EnterpriseAgentgatewayBackend
          name: geocoding-code-mode
EOF
```

Open MCP Inspector, another MCP client, or use `curl` to test your Gateway.

Open MCP Inspector
```
npx modelcontextprotocol/inspector#0.18.0
```
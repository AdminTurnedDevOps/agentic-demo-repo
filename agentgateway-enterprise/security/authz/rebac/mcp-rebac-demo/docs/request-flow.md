# Request Flow

## tools/list

1. Client sends `POST /mcp` with bearer JWT.
2. Agentgateway validates JWT.
3. Agentgateway calls `extAuth` on adapter (`/extauth`) with body/headers.
4. Adapter allows list operation.
5. Request routes to MCP backend (`rebac-auth-adapter /mcp`).
6. Adapter calls OpenFGA `ListObjects` with subject `user:<sub>` and relation `discover`.
7. Adapter forwards `tools/list` to upstream MCP servers and returns only tools whose OpenFGA objects are visible.

## tools/call

1. Client sends `tools/call`.
2. Agentgateway validates JWT.
3. Agentgateway calls adapter `/extauth`.
4. Adapter maps tool to OpenFGA object and runs `Check(user, invoke, tool)`.
5. If denied: gateway returns 403.
6. If allowed: request routes to adapter `/mcp`.
7. Adapter runs the same `Check` and forwards to target MCP server.

## Contextual tuples

Adapter converts runtime JWT claims into contextual tuples per request:

- `team` claim -> `user:<sub> member team:<team>`
- `approver_projects` claim -> `user:<sub> approver project:<id>`

This demonstrates runtime relationship enrichment without persisting every fact.

# Solo Docs 2.1.x Quick Map

Use these official pages first when exact field behavior or policy semantics matter.

## Core
- Docs home: https://docs.solo.io/agentgateway/2.1.x/
- Install: https://docs.solo.io/agentgateway/2.1.x/setup/install/

## LLM Traffic Management
- Provider failover: https://docs.solo.io/agentgateway/2.1.x/traffic-management/llm/load-balancing/failover/
  - Use for `priorityGroups` and provider fallback behavior.

## Security
- Prompt guards: https://docs.solo.io/agentgateway/2.1.x/security/prompt-guard/
  - Use for regex/content rejection on request or response.
- Access MCP tools with CEL: https://docs.solo.io/agentgateway/2.1.x/security/access-tools/
  - Use for CEL authorization over requests and tool metadata (for example `mcp.tool.name`).
- Authenticate MCP: https://docs.solo.io/agentgateway/2.1.x/security/authenticate-mcp/
  - Use for OIDC discovery, dynamic client registration, and MCP auth mode.

## MCP Connectivity
- Connect static MCP targets: https://docs.solo.io/agentgateway/2.1.x/connect-mcp/static/
  - Use for direct upstream MCP services via `targets[].static`.
- Connect dynamic MCP targets: https://docs.solo.io/agentgateway/2.1.x/connect-mcp/dynamic/
  - Use for virtual MCP server backends selected by labels/annotations.

## Practical Guidance
- Prefer official docs when adding new fields or policy types.
- Prefer repo examples when choosing naming conventions, namespace layout, and tested end-to-end flows.
- If docs and repo differ, treat docs as source of truth and adjust manifests accordingly.

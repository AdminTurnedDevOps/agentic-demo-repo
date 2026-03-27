# Agentgateway.dev Kubernetes Latest Quick Map

Use this file for OSS Kubernetes latest behavior and current upstream patterns.

## Core
- Docs home:
  - https://agentgateway.dev/docs/kubernetes/latest/
- Install:
  - https://agentgateway.dev/docs/kubernetes/latest/install/
- Setup:
  - https://agentgateway.dev/docs/kubernetes/latest/setup/

## Traffic and Connectivity
- LLM routing and provider configuration:
  - https://agentgateway.dev/docs/kubernetes/latest/llm/
- MCP overview:
  - https://agentgateway.dev/docs/kubernetes/latest/mcp/
- Dynamic MCP targets:
  - https://agentgateway.dev/docs/kubernetes/latest/mcp/dynamic-mcp/
- Connect MCP via HTTPS:
  - https://agentgateway.dev/docs/kubernetes/latest/mcp/connect-via-https/

## Practical Guidance
- Use `agentgateway.dev` pages as the source of truth for OSS Kubernetes latest.
- Use `docs.solo.io/agentgateway/2.1.x` as the source of truth for Solo enterprise 2.1.x fields and policy behavior.
- Use repository examples as implementation templates after selecting the correct documentation track.
- If docs and repo examples differ, follow the official docs for the deployment mode and version you are targeting.

## Fast Search Commands
- Find all Gateway API + Agent Gateway resource examples in this repo:
```bash
rg -n "kind:\\s*(Gateway|HTTPRoute|GRPCRoute|AgentgatewayBackend|AgentgatewayPolicy|EnterpriseAgentgatewayPolicy)" /Users/michaellevan/gitrepos/agentic-demo-repo
```
- Find MCP resource patterns:
```bash
rg -n "mcp:|targets:|dynamic|static|tool|oauth|jwt" /Users/michaellevan/gitrepos/agentic-demo-repo
```

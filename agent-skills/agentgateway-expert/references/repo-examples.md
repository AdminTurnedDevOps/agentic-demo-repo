# Repo Examples Map

Use this file to pick a concrete starting point from this repository before writing new manifests.

## LLM Routing and Resilience
- Failover with provider priorities:
  - `/Users/michael/gitrepos/agentic-demo-repo/agw-llm-proxying/failover/failover.md`
  - Shows multi-provider `AgentgatewayBackend` with `priorityGroups` and `HTTPRoute` wiring.
- Team/header-based routing with CEL policy:
  - `/Users/michael/gitrepos/agentic-demo-repo/agw-llm-proxying/cel/team-based-routing.md`
  - Shows `EnterpriseAgentgatewayPolicy` authorization with `matchExpressions`.

## MCP Gateway Patterns
- Basic MCP gateway and backend:
  - `/Users/michael/gitrepos/agentic-demo-repo/agw-llm-proxying/mcp-gateway/setup.md`
  - Shows `Gateway` + MCP `AgentgatewayBackend` + `HTTPRoute` plus MCP inspector test flow.
- OAuth pass-through to external MCP provider (GitLab):
  - `/Users/michael/gitrepos/agentic-demo-repo/agentgateway-enterprise/mcp-oauth/gitlab/setup.md`
  - Shows static MCP target to remote HTTPS endpoint with TLS policy.
- OAuth pass-through to external MCP provider (Atlassian):
  - `/Users/michael/gitrepos/agentic-demo-repo/agentgateway-enterprise/mcp-oauth/atlassian/setup.md`

## Prompt Guard and Content Controls
- Anthropic + prompt guard:
  - `/Users/michael/gitrepos/agentic-demo-repo/agentgateway-enterprise/claude-prompt-guards/setup.md`
  - Shows `policies.ai.routes`, auth secret refs, and regex-based prompt guard rejection.

## Observability
- OTel tracing for Agent Gateway:
  - `/Users/michael/gitrepos/agentic-demo-repo/agw-llm-proxying/observability/tracing.md`
  - Shows OTLP collector setup and custom trace field extraction from LLM metadata.

## OSS Kubernetes and Local Modes
- OSS Kubernetes install and examples:
  - `/Users/michael/gitrepos/agentic-demo-repo/agentgateway-oss-k8s`
- Local CLI examples:
  - `/Users/michael/gitrepos/agentic-demo-repo/agentgateway-oss-local`

## Fast Search Commands
- Find all AgentgatewayBackend specs:
```bash
rg -n "kind:\\s*AgentgatewayBackend|spec:\\s*$|priorityGroups|promptGuard|mcp:" /Users/michael/gitrepos/agentic-demo-repo
```
- Find enterprise policies and CEL expressions:
```bash
rg -n "kind:\\s*EnterpriseAgentgatewayPolicy|matchExpressions|authorization" /Users/michael/gitrepos/agentic-demo-repo
```
- Find route linkage issues (`parentRefs`, backend group/kind):
```bash
rg -n "parentRefs|backendRefs|group:\\s*agentgateway.dev|kind:\\s*HTTPRoute" /Users/michael/gitrepos/agentic-demo-repo
```

---
name: agentgateway-expert
description: Expert guidance for Solo Agent Gateway 2.1.x design, configuration, and troubleshooting. Use when Codex needs to create, review, or debug Kubernetes Gateway API and Agent Gateway resources such as Gateway, HTTPRoute, AgentgatewayBackend, and EnterpriseAgentgatewayPolicy; implement LLM provider routing/failover, prompt guards, MCP connectivity/auth/tool access, and observability; or map requirements to working manifests by reusing examples from this repository and docs.solo.io/agentgateway/2.1.x.
---

# Agentgateway Expert

Build production-ready Agent Gateway configurations quickly and safely by combining official 2.1.x patterns with repo-proven examples.

Load only the references needed for the task:
- For official behavior and field semantics, read `references/solo-docs-2.1x.md`.
- For implementation patterns already used in this repo, read `references/repo-examples.md`.

## Workflow

1. Classify the request
- Decide deployment mode: enterprise Kubernetes, OSS Kubernetes, or local CLI.
- Decide traffic type: LLM, MCP, or general HTTP.
- Decide scope: new setup, policy hardening, feature extension, or troubleshooting.

2. Start from the minimum viable resource set
- Prefer the baseline pattern: `Gateway` + `AgentgatewayBackend` + `HTTPRoute`.
- Add `EnterpriseAgentgatewayPolicy` only when auth, RBAC, prompt guards, or other controls are required.
- Keep names/labels/namespaces consistent across all manifests before adding advanced options.

3. Choose the right backend style
- For LLM routing/failover: use `spec.ai` on `AgentgatewayBackend` and route to provider endpoints via `HTTPRoute`.
- For MCP static targets: use `spec.mcp.targets[].static` with host/port/path/protocol.
- For MCP dynamic/virtual targets: use label selectors and ensure Service protocol/path annotations match MCP expectations.

4. Apply security and policy layers deliberately
- Use prompt guards for request/response content control.
- Use MCP auth when clients need OAuth discovery and dynamic client registration.
- Use JWT auth for static service clients that already carry tokens.
- Use CEL authorization policies for route-level or tool-level control.

5. Verify with executable checks
- Run `kubectl apply --dry-run=server -f <file-or-dir>` before live apply when possible.
- Confirm objects and readiness:
  - `kubectl get gateway,httproute -A`
  - `kubectl get agentgatewaybackend -A`
  - `kubectl get enterpriseagentgatewaypolicy -A`
- Validate the request path and headers with targeted `curl` or MCP inspector tests.

6. Troubleshoot systematically
- If traffic is not routed: verify `parentRefs`, backend group/kind/name, and route matches/rewrites.
- If provider auth fails: verify secret keys/headers and backend auth references.
- If MCP tools are missing or denied: verify auth policy targetRefs, JWT claims, and CEL expressions.
- If no external access: check Gateway/Service status and port-forward first to isolate cluster-internal behavior.

## Output Requirements

Return:
- Complete manifests, not partial fragments, unless explicitly asked for a patch snippet.
- A short apply order and a short verification checklist.
- A concise explanation of why each policy exists and what failure it prevents.

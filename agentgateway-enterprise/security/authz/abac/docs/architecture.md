# Architecture

## Request path

1. Client sends HTTP request to Agentgateway.
2. Agentgateway applies `EnterpriseAgentgatewayPolicy` on the Gateway.
3. `traffic.entExtAuth` triggers Enterprise ExtAuth.
4. Enterprise ExtAuth loads the configured `AuthConfig`.
5. `AuthConfig.spec.configs[].opaServerAuth` calls OPA.
6. OPA evaluates ABAC policy from request headers + path + method.
7. OPA returns allow/deny.
8. ExtAuth returns allow/deny to Agentgateway.
9. Agentgateway enforces the decision:
   - deny: request is rejected before LLM provider call
   - allow: HTTPRoute rewrites path to `/v1/messages` and forwards to `AgentgatewayBackend` (`anthropic`)
10. `AgentgatewayBackend` calls Claude with Anthropic credentials from `anthropic-secret`.

## Key implementation details

- `EnterpriseAgentgatewayPolicy.spec.traffic.entExtAuth.authConfigRef` references `AuthConfig`.
- `backendRef` is intentionally omitted in `entExtAuth` to use the default built-in ext-auth service.
- OPA runs as a separate service (`opa.abac-demo.svc.cluster.local:8181`) and is queried by `opaServerAuth`.
- No JWT is used. Identity and context are supplied via request headers and HTTP request attributes.
- Destination backend is AI-native: `AgentgatewayBackend` with Anthropic Claude model.

## ABAC attributes used

- Subject/resource/context headers:
  - `x-tenant`
  - `x-team`
  - `x-role`
- Request context:
  - HTTP path
  - HTTP method

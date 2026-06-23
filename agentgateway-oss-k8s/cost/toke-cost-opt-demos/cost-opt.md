# Agentgateway Cost and Token Optimization Demos

1. Demo 1: Token & cost visibility (per gateway). Scrape `agentgateway_gen_ai_client_token_usage` + latency histograms sliced by gateway/model/provider; Grafana dashboard; per-request `cost{}` in the access log.

2. Demo 2: Cost management (catalog + attribution). Model-cost catalog via agctl costs import → ConfigMap → hot-reload; per-team/gateway chargeback; tiered pricing + cache-savings breakdown.

3. Demo 3: Cost optimization & control. Cost-aware model routing (cheap default → premium escalate) + native token/cost rate limiting as budget enforcement (localRateLimit type: tokens, remoteRateLimit CEL cost) + CEL cost-policy tagging (llm.cost.total).

4. Demo 4: MCP cost/token savings (tool virtualization). Aggregate multiple MCP servers behind one MCP gateway endpoint, then apply CEL/RBAC authorization rules (mcp.tool.name, jwt.*) that filter the tools/list response per client. The gateway's merge_tools drops disallowed tools before they ever reach the agent. Because every exposed tool's JSON schema is injected into the LLM prompt as input tokens, curating the toolset (e.g. 40 aggregated tools → 6 relevant ones per agent) directly shrinks the input-token payload.
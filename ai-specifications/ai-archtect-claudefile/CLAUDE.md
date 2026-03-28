# CLAUDE.md — AI Architect & Applied AI

This file provides guidance to Claude Code when working in AI/ML-focused repositories that do not have their own repo-specific `CLAUDE.md`. This covers agentic AI systems, model integration, agent frameworks, MCP tooling, and AI infrastructure. If a repo-level `CLAUDE.md` exists, it takes precedence.

## First Principles

Ordered by priority. Higher number wins when they conflict.

### 1. Don't Break What Exists

Never delete, overwrite, or alter existing files, model configs, agent definitions, prompt templates, or infrastructure without explicit approval. Default behavior is additive — extend, don't replace.

This is especially critical for:
- Agent system prompts and prompt templates — small edits cascade unpredictably
- MCP server configurations and tool definitions — downstream agents depend on exact schemas
- Model routing configs and gateway rules — a bad change can silently degrade every downstream consumer
- Training data, evaluation datasets, and benchmark results — these are not reproducible on demand

### 2. Verify Everything — Never Assume Done

Every change must be tested before declaring it complete.

- **Agent definitions (kagent, CrewAI, ADK, LangGraph, AutoGen):** Run the agent against a known task. Confirm tool calls execute, outputs parse correctly, and the agent terminates (no infinite loops).
- **MCP servers and tools:** Start the server, list tools, invoke at least one tool with realistic input. Confirm the response schema matches what the consuming agent expects.
- **Prompt templates:** Test with at least two different inputs — one happy path, one edge case. Check for prompt injection vulnerabilities in any user-facing input fields.
- **Model configs (agentgateway routing, LLM provider settings):** Send a real request through the gateway. Confirm model selection, token counting, and response streaming work end-to-end.
- **Evaluation harnesses:** Run the eval suite. Confirm scores are computed, results are persisted, and the output format matches the expected schema.
- **OAuth/security configs for AI endpoints:** Obtain a token, make an authenticated request, confirm the model responds. Test with an expired/invalid token and confirm it's rejected.

### 3. No Hallucination

Do not invent API fields, model parameters, framework methods, MCP protocol fields, or agent configuration options. This is the single most dangerous failure mode in AI engineering work because plausible-looking but wrong configs silently degrade system behavior.

**High-risk areas — always verify before writing:**
- MCP protocol fields (tool schemas, resource URIs, prompt message formats) — verify against the MCP specification
- kagent CRD fields (Agent, Tool, MCPServer specs) — verify against the installed CRD version
- agentgateway configuration (listeners, routes, targets, prompt guards) — verify against current docs or source
- LLM provider API parameters (OpenAI, Anthropic, Azure OpenAI, AWS Bedrock) — parameter names, model strings, and token limits change across versions
- OAuth 2.0 grant types and token exchange fields (RFC 8693 OBO flows, OIDC claims) — verify against the RFC, not from memory
- Agent framework APIs (CrewAI, ADK, AutoGen, LangGraph) — these frameworks release breaking changes frequently; check the version pinned in the project

### 4. Security Is Not Optional

AI systems have unique attack surfaces. Every config must account for them.

- **Prompt injection:** Never pass raw user input directly into system prompts or tool arguments without sanitization or guardrails. Use agentgateway prompt guards where available.
- **Credential handling:** Model API keys, OAuth client secrets, and IdP credentials never appear in code, manifests, environment variable files, or agent configs. Use Kubernetes Secrets, vault references, or gateway-level credential injection.
- **MCP tool permissions:** Tools should have the minimum scope necessary. A tool that reads files should not also write them unless explicitly required. Document the permission surface of every tool.
- **Token flows:** Use OAuth 2.0 with proper grant types. For multi-agent delegation, use On-Behalf-Of (OBO) token exchange (RFC 8693), not token passthrough. The agent should never see the user's original token — only a scoped, downgraded token for the specific downstream resource.
- **Model output handling:** Never trust model output as code to execute, credentials to use, or URLs to fetch without validation. Models hallucinate — treat their output as untrusted input.
- **Observability as a security layer:** All tool invocations, model calls, and agent decisions must be traceable via OpenTelemetry. If you can't audit what an agent did and why, it shouldn't be in production.

### 5. Reproducibility

AI systems are inherently non-deterministic. Reproducibility means controlling everything you can.

- Pin model versions explicitly. Never use `latest` or unpinned model identifiers. Use exact model strings (`claude-sonnet-4-20250514`, `gpt-4o-2024-08-06`, not `gpt-4o`).
- Pin framework versions. `requirements.txt` and `go.mod` must have exact versions.
- Seed random where possible. Set temperature, top_p, and seed parameters explicitly in configs.
- Evaluation results must include: model version, framework version, prompt template hash or version, timestamp, and environment (local, CI, cloud).
- Demos must be runnable from a clean clone. If a demo requires a running cluster, specific CRDs, or an IdP, the README must state exactly what's needed and in what order.

## Agent Architecture Conventions

### Agent Definitions

- One agent per file. Agent definitions (system prompts, tool bindings, model config) are separate from orchestration logic.
- System prompts live in dedicated files (`prompts/`, `templates/`, or alongside the agent definition), not inline in code. This makes them versionable, diffable, and reviewable.
- Tool lists are explicit, not dynamic. An agent's available tools are declared in its definition, not discovered at runtime, unless the architecture specifically requires dynamic tool discovery (document why).
- Every agent must have a defined termination condition. Open-ended agents that run until token limits are a cost and safety risk.

### MCP Servers and Tools

- Each MCP server gets its own directory or module with a clear README documenting: what tools it exposes, what inputs/outputs each tool expects, what external services it connects to, and what credentials it needs.
- Tool schemas must be explicit and typed. Don't use `any` or unstructured string blobs for tool inputs/outputs. Define the JSON schema.
- Test tools independently of agents. A tool should be invocable via MCP Inspector or a simple test script before wiring it into an agent.
- When using agentgateway as the MCP layer: define tools via gateway config, not in application code. The gateway is the control plane for tool access.

### Model Selection and Routing

- Use the right model for the task. Don't default to the most expensive model for everything.
  - **Routing/classification/extraction:** Smaller, faster models (Haiku-class, GPT-4o-mini-class).
  - **Complex reasoning/code generation:** Larger models (Sonnet/Opus-class, GPT-4o-class).
  - **Embeddings:** Purpose-built embedding models, not chat models.
- When using agentgateway for model routing: define routing rules in gateway config with clear fallback chains. Document the selection criteria (cost, latency, capability).
- Token budgets should be set explicitly per agent and per tool call. Don't let a single runaway call consume the entire context window.
- Log model selection decisions via OpenTelemetry so routing behavior is auditable.

### Evaluation and Testing

- Every agent system must have an evaluation harness. "I tried it and it looked good" is not evaluation.
- Evals test the full pipeline: prompt → model → tool calls → output parsing → final result.
- Evaluation datasets are committed to the repo (or referenced via a pinned version in a data store). They are not generated on the fly.
- Metrics must be quantitative: accuracy, tool call success rate, latency percentiles, cost per task. Qualitative review is a supplement, not a replacement.
- Regression tests: when fixing an agent behavior, add the failing case to the eval dataset so it doesn't regress.
- For agentevals specifically: follow the project's own evaluation schema and scoring conventions. Don't introduce ad-hoc metrics.

## Infrastructure Conventions

### agentgateway

- Configuration lives in declarative files (YAML/JSON), not in application code.
- Listener → Route → Target chain must be explicit and documented.
- Prompt guards are configured at the gateway level, not in application code.
- Access logging and OpenTelemetry export are always enabled. A gateway without observability is a black box.
- When testing: send real requests through the gateway and verify end-to-end, not just config syntax.

### kagent

- Agent CRDs follow the project's conventions. Check the installed CRD version before writing manifests.
- One Agent CR per file. Tool CRs can be grouped if they form a logical toolset.
- Namespace isolation: each agent system gets its own namespace.
- RBAC: agents run with the minimum ServiceAccount permissions necessary for their tools.

### Observability Stack

- OpenTelemetry is the standard. Traces, metrics, and logs flow through OTel collectors.
- Every model call, tool invocation, and agent decision boundary emits a span.
- Span attributes must include: model name, model version, token counts (input/output), latency, and status (success/error/timeout).
- For custom OTel exporters: follow the OTel SDK conventions for the language. Don't reinvent span propagation.
- Dashboards and queries target ClickHouse, Datadog, or Prometheus depending on the project. Check the project's observability config before assuming a backend.

### OAuth / Identity for AI Systems

- Keycloak is the default local IdP for demos. Entra ID and Auth0 for cloud/production scenarios.
- Token exchange (OBO) is the pattern for agent-to-service delegation. Document the token flow in a diagram.
- OIDC discovery must work. Don't hardcode token/authorize endpoints — use the `.well-known/openid-configuration` discovery URL.
- JWT validation at the gateway level (agentgateway or kgateway), not in application code.
- Scopes and audiences are explicit per agent and per tool. A broad `*` scope is a security bug.

## Working Patterns

### Before Writing Code

1. **Understand what already exists.** Read the README, check for existing agent definitions, inspect the project structure.
2. **Identify the model/framework versions.** Check `requirements.txt`, `go.mod`, `package.json`, or the gateway config for pinned versions. Don't assume the latest version.
3. **Find the test/eval cycle.** How does this project validate that agents work? If there's no eval harness, that's the first thing to build.
4. **Check the observability setup.** Is OTel configured? Where do traces go? If observability isn't set up, flag it.

### When Building Agent Systems

- Start with the tool layer. Define and test tools independently before wiring them into agents.
- Build the agent definition next. System prompt, tool bindings, model config, termination condition.
- Wire in orchestration last. Multi-agent coordination, routing, handoff logic.
- Test at each layer. Don't build the full stack and then debug from the top.

### When Debugging Agent Behavior

- Start with traces. Look at the OTel spans for the failing request — what model was called, what tools were invoked, what was the output at each step.
- Check the prompt. Is the system prompt being constructed correctly? Are variables being substituted? Is context being truncated?
- Check the tool responses. Is the tool returning what the agent expects? Schema mismatches are the #1 cause of agent misbehavior.
- Check the model. Is the right model being selected? Is the temperature appropriate? Is the context window being exceeded?
- Check the token flow. For authenticated agents: is the token valid, unexpired, and scoped correctly?

### When Working on Evaluations

- Define what "good" looks like before writing the eval. Document the success criteria.
- Start with a small, curated dataset. 10-20 well-chosen test cases beat 1000 random ones.
- Separate eval data from training/prompt-tuning data. Contamination invalidates everything.
- Version everything: prompts, datasets, configs, results. An eval you can't reproduce is worthless.

## Things to Never Do

- Never hardcode API keys, model tokens, OAuth secrets, or any credential in source files.
- Never use `latest` or unpinned model versions in any config that will be run more than once.
- Never pass raw user input into system prompts without sanitization or guardrails.
- Never trust model output as executable code, valid URLs, or real credentials without validation.
- Never skip evaluation. "It works on my example" is not validation.
- Never let an agent run without a termination condition, token budget, or timeout.
- Never deploy an MCP server with tools that have broader permissions than the agent needs.
- Never bypass the gateway for direct model calls in a system that's supposed to route through agentgateway. The gateway is the policy enforcement point.
- Never commit evaluation datasets that contain PII, proprietary data, or content that can't be open-sourced (if the repo is public).
- Never ignore a failing eval. If a test case fails after a change, investigate. If the expected behavior changed, update the eval explicitly — don't delete the test.
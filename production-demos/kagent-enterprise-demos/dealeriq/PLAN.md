# DealerIQ - Lead-Gen Agentic Workflow Demo Plan

A live, repeatable demo of an AI lead-generation assistant for dealerships, built on the
Solo enterprise agentic stack. One assistant, built two ways (Declarative kagent Agent and
BYO LangGraph agent), working real dealership workflows (lead qualification, inventory
matching, and customer offers) with identity-scoped tool access, centralized session
state, human-in-the-loop approvals, and full-stack observability with spend circuit
breakers.

## Platform Versions

| Component | Version | Status on cluster |
|---|---|---|
| kagent enterprise | 0.5.5 | installed (`kagent`, `kagent-mgmt` releases) |
| enterprise agentgateway | 2026.8.2 | installed (`agentgateway-system`) |
| agentregistry enterprise | 2026.8.0 | installed (`agentregistry-system`) |
| Istio ambient (Solo) | 1.27.0-solo | installed |

Target cluster: `gke_field-engineering-us_us-east1_kagent-ee-felevan`

## Demo Narrative

DealerIQ is the dealership's AI assistant for working inbound leads. Two staff members
use the same assistant and get different experiences based on who they are:

| User | Role | Access |
|---|---|---|
| `reader` | BDC / internet sales rep | Qualify leads, match inventory, draft outreach |
| `writer` | Sales manager | Everything, plus approving customer offers |

Identity is the existing kagent UI Keycloak realm (`kagent-dev` on Cloud Run).
Users `reader`, `writer`, and `admin` already exist; the demo does not deploy Keycloak
and does not modify `keycloak-test`. AccessPolicy matches `preferred_username`.

## Components

### dealer-leads-mcp (built for this demo)

Python FastMCP server with a seeded mock dataset (CRM leads + vehicle inventory, cars and
light trucks). Deployed in-cluster behind a waypoint so every tool call is mediated and
policy-enforced by agentgateway.

| Tool | Tier | Demo role |
|---|---|---|
| `get_lead_details` | read | Pull an inbound lead (web form / trade-in inquiry) |
| `score_lead` | read | Qualify: intent, budget fit, timeline |
| `search_inventory` | read | Match on-lot vehicles to the lead |
| `get_vehicle_history` | read | Attach history data to a listing pitch |
| `draft_followup` | read | Compose (not send) outreach |
| `send_customer_offer` | privileged + approval | HITL centerpiece: outbound discounted offer |
| `update_lead_status` | privileged | Mutate CRM state (qualified / won / lost) |
| `export_leads` | privileged | Bulk PII export: denied for all users (deny-by-default proof) |

### Agents (built for this demo)

- **`dealer-assistant`**: Declarative kagent Agent (`kagent.dev/v1alpha2`), ModelConfig
  pointing at the demo LLM route on agentgateway.
- **`dealer-assistant-byo`**: BYO LangGraph agent. kagent SDK wiring (identity shim,
  checkpointer, HITL relay) confined to initialization; core graph logic is standard
  LangGraph.

### Reused from the cluster

- enterprise-agentgateway install, `enterprise-agentgateway` / `-waypoint` gateway classes
- kagent management UI + ClickHouse tracing + OTel pipeline
- agentgateway UI cost dashboard
- Existing LLM route pattern (modeled on `agentgateway-route-gemini`)

### Explicitly out of scope

- Substrate/ATE: not shown, not referenced, no sandboxagents or ATE-adjacent resources
- Existing demo namespaces (`policies`, `semantic-routing`, `keycloak-test`): untouched
- Framework Coupling section: removed from demo scope

## Execution References

Everything in this section exists so the plan can be executed without prior conversation
context.

### Source-of-truth repositories (local)

| Repo | Path | Use for |
|---|---|---|
| kagent (OSS) | `~/gitrepos/kagent` | Agent / ModelConfig / RemoteMCPServer schemas; Python SDK (checkpointer, A2A + HITL handlers) |
| kagent-enterprise | `~/gitrepos/kagent-enterprise` | `AccessPolicy` CRD (`policy.kagent-enterprise.solo.io/v1alpha1`); mgmt plane; `dev-keycloak/` declarative realm-import pattern |
| agentgateway-enterprise | `~/gitrepos/agentgateway-enterprise` | Enterprise gateway CRDs (`enterpriseagentgateway.solo.io/v1alpha1`); budgets (`ent-controller/`); STS/OBO token exchange; cost dashboard |
| agentregistry-enterprise | `~/gitrepos/agentregistry-enterprise` | `dev/keycloak/` realm pattern (secondary reference) |

**Rule:** verify every API version, kind, and field name against the installed CRDs
(`kubectl get crd <name> -o yaml`) and these repos at the pinned versions (never against
docs or memory) before writing any manifest. This applies especially to the tool
approval flag (spike 0b), AccessPolicy match fields (0c), and the SDK checkpointer /
interrupt wiring (0a).

### Existing cluster resources to model on (read-only, never modify)

| Resource | Namespace | Pattern it provides |
|---|---|---|
| `agentgateway-route-gemini` | agentgateway-system | LLM route: ModelConfig → gateway → provider |
| `monthly-usd-budget-for-gemini` + `enable-budget-enforcement` | agentgateway-system | working budget + enforcement policy pair (Accepted/Enforced) |
| `mcp-rate-limit` | agentgateway-system | rate-limit policy shape |
| `agent-k8shelper-waypoint` | kagent | per-agent waypoint wiring |
| `deny-github-tool-server`, `deny-reader-agent-access` | policies | AccessPolicy shapes known-good on 0.5.5 |
| `gemini-agent` | kagent | Declarative Agent spec shape |

### Keycloak realm requirements

- Reuse the existing UI issuer: `https://demo-keycloak-907026730415.us-east4.run.app/realms/kagent-dev`.
- Users: `reader` (BDC), `writer` (sales manager). `admin` is unused in the talk track.
- AccessPolicy matches `preferred_username` (proven by `deny-reader-agent-access`).
- Do not deploy Keycloak in `dealeriq`. Do not touch `keycloak-test`.
- Optional password-grant helper `scripts/get-token.sh` reads `DEALERIQ_PASSWORD` from the
  environment; demos themselves use UI login.

### Conventions & constraints

- **Images:** build and push to a durable registry with pinned, immutable tags. Never use
  short-TTL registries (e.g., ttl.sh); expired demo images have already broken agents on
  this cluster.
- **Secrets:** Kubernetes Secrets only (LLM API keys, Keycloak credentials, MCP config).
  No tokens in manifests, env literals, or code.
- **Additive-only:** every created resource lives in the `dealeriq` namespace.
  Nothing outside it is modified or deleted.
- **Runbook framing:** the talk track demonstrates capabilities only: no gap,
  limitation, or roadmap commentary anywhere in RUNBOOK.md.
- **kubectl skew:** client v1.33 vs server v1.35.7-gke.1027000; the version-skew warning
  is expected noise.

### Prerequisites (must be true before Phase 0)

- `kagent-controller` healthy and Ready (a Valkey/controller fix is being handled
  separately, outside this plan). If the controller is crash-looping, stop; do not
  debug it as part of this work; confirm the fix has landed first.
- LLM provider key available for the demo route (existing Gemini route pattern is the
  reference).
- `validate.sh` encodes these checks so they are re-verified before every phase and
  every delivery.

## Repository Layout

```
production-demos/kagent-enterprise-demos/dealeriq/
├── PLAN.md                  # this file
├── README.md                # description, architecture diagram, prerequisites, quickstart
├── RUNBOOK.md               # screen-safe, step-by-step demo script (shared on screen)
├── Makefile                 # setup / deploy / seed / demo-reset / clean
├── mcp/
│   ├── server.py            # FastMCP dealer-leads-mcp
│   ├── data/                # seeded leads + inventory (JSON)
│   ├── Dockerfile
│   └── manifests/           # namespace, ConfigMap, MCPServer + waypoint wiring
├── agents/
│   ├── declarative/         # Agent, ModelConfig manifests
│   └── byo/                 # LangGraph agent source, Dockerfile, manifests
├── identity/
│   └── README.md            # existing kagent-dev users (reader / writer / admin)
├── policies/
│   ├── 00-deny-all.yaml     # zero-trust baseline AccessPolicy
│   ├── 10-reader.yaml       # read-tier tools for preferred_username=reader
│   ├── 20-writer.yaml       # manager tools for preferred_username=writer
│   └── 30-live-edit/        # the Demo 1 live policy change, pre-staged
├── gateway/
│   ├── llm-route/           # demo Gateway/HTTPRoute/Backend for model traffic
│   ├── budget.yaml          # EnterpriseAgentgatewayBudget (small cap for circuit-breaker demo)
│   └── rate-limit.yaml
└── scripts/
    ├── get-token.sh         # optional password-grant helper (DEALERIQ_PASSWORD)
    ├── drive-load.sh        # generate model traffic for the budget-trip demo
    └── validate.sh          # pre-demo health checks (controller, MCP, routes, budget state)
```

All demo resources live in the `dealeriq` namespace, so `make clean` removes
everything without touching the rest of the cluster. No Keycloak is deployed here.

## The Four Demos

### Demo 1 - Governance: BYO vs. Declarative Agents

Story: same assistant, different users, different capabilities, enforced by the
platform, not the agent code.

1. Baseline: deny-all AccessPolicy applied. Agent has 8 tools bound in its spec.
2. `reader` logs in, asks the assistant to work a fresh lead; the assistant can see and
   use only the read-tier tools its policy allows.
3. `writer` runs the same request: full toolset including `send_customer_offer` and
   `update_lead_status`.
4. Show the actor token (decoded JWT): agent identity + calling user identity combined
   via on-behalf-of token exchange; agentgateway evaluates policy against that token.
5. Live change: apply the pre-staged policy granting `reader` the
   `update_lead_status` tool. Next turn, `reader` can use it. No agent restart, no
   redeploy.
6. BYO parity: repeat the probe against `dealer-assistant-byo`: identical enforcement,
   same policies, zero policy duplication.
7. `export_leads` remains denied for everyone throughout, deny-by-default posture.

Key manifests: `policies/*.yaml`. Key visual: kagent UI chat + decoded token + one
`kubectl apply`.

### Demo 2 - State & Session Management

Story: sessions are a platform service: durable, centralized, framework-independent.

1. `reader` works lead #4127 across multiple turns: pull details → score → match
   inventory → "which truck fits their budget?" Each turn builds on prior context.
2. Kill the agent pod mid-session (`kubectl delete pod`). Resume the same session:
   full context intact.
3. Repeat the multi-turn + resume flow on the BYO agent: LangGraph runs with kagent's
   checkpointer, wired at initialization.
4. Proof of centralization: query kagent's Postgres: sessions for both agents in the
   same store. One persistence layer for the platform, no per-framework datastores.

Key visual: chat continuity across a visible pod kill; a short psql query.

### Demo 3 - Human-in-the-Loop

Story: no AI sends a discounted offer to a customer without a manager's sign-off.

1. `reader` asks the assistant to send the matched customer an offer with a discount.
2. `send_customer_offer` is approval-flagged: execution freezes at the platform layer,
   pending approval, visible in the session.
3. Session sharing: `writer` opens the shared session from the session list, reviews the
   proposed offer (tool + arguments), and approves.
4. The tool executes; the offer is sent; the outcome lands in the session.
5. The full interaction, including the approval decision, is captured in the trace,
   which tees up Demo 4.
6. BYO variant: the same approval flow through the LangGraph agent using LangGraph's
   native interrupt mechanism, relayed to the kagent UI via the SDK's A2A handler.

Key visual: frozen execution → second user approving in the UI → tool completes.

### Demo 4 - Observability & Circuit Breakers

Story: every token, every call, every decision: visible, attributable, and capped.

1. Trace deep-dive on the Demo 3 run: input/output tokens per request, model used, tool
   calls, policy decisions, approval decision: one trace, end to end.
2. Side-by-side: a declarative-agent trace and a BYO-agent trace: same format, same
   fields, same pipeline.
3. Cost dashboard (agentgateway UI): spend sliced by model/provider across the demo
   traffic.
4. Circuit breaker: the demo LLM route carries a small `EnterpriseAgentgatewayBudget`.
   Run `drive-load.sh` to push lead-scoring traffic → watch spend climb on the dashboard
   → budget trips → next live request from the assistant is rejected at the gateway →
   dashboard shows the stop.
5. Rate limiting on the same route as the second guardrail.

Key visual: the live moment the gateway starts refusing model calls because the budget
is exhausted.

## RUNBOOK.md Specification (screen-safe)

RUNBOOK.md is shared on screen during delivery. The presenter bounces between the kagent
UI, the agentgateway UI, and this file, so it must read well to a customer audience, not
just the presenter.

**Structure (one section per demo):**

1. **Title + story beat**: one audience-facing sentence (e.g., "No AI sends a discounted
   offer to a customer without a manager's sign-off").
2. **Numbered steps**, each containing only:
   - a plain-English line stating what happens next
   - the exact copy-paste command in a code block (when a terminal step), or a
     `>> SWITCH TO: kagent UI > Sessions` cue line (when a UI step)
   - **What you'll see:** one line describing the expected result, so the audience can
     confirm the outcome with the presenter
3. Chat prompts to type as the personas are written verbatim in code blocks; no
   improvising mid-demo.

**Rules:**

- No presenter-only talk track, no speaker notes, no internal commentary; everything in
  the file is safe for customers to read.
- Capabilities only (per Conventions): no gap/limitation/roadmap language.
- Short lines, generous whitespace, large logical sections, readable at screen-share
  resolution.
- Every command is copy-paste complete: no placeholders that need editing live
  (tokens/URLs come from `scripts/get-token.sh` output or env set during pre-demo
  checklist).
- Opens with a one-page "Before you go live" block: the pre-demo checklist commands
  (`validate.sh`, `make demo-reset`, warm-up turns); this page is run *before*
  screensharing starts.
- No secrets anywhere in the file, including example output.

## Build Phases

### Phase 0 - Verification spikes (before any polish)

Engineering validation on the live cluster so every demo is proven before it is scripted:

- **0a. BYO HITL round-trip:** LangGraph interrupt → SDK A2A relay → pending approval in
  kagent UI → approve → resume. Proven end-to-end on 0.5.5.
- **0b. Approval flag shape:** confirm the exact tool-approval field/config in the 0.5.5
  Agent/tool spec from the kagent + kagent-enterprise repos (source of truth: CRDs and
  SDK, not docs).
- **0c. Identity chain:** Keycloak token → OBO/actor token exchange → AccessPolicy
  `UserGroup` claim matching → per-tool enforcement at the waypoint. Verified with both
  personas.

Exit criteria: all three flows demonstrated with throwaway resources. Learnings feed the
real manifests in Phases 1–3. (If 0a needs adjustment, Demo 3 runs the approval flow on
the declarative agent; the demo's story is unchanged.)

### Phase 1 - Foundation

- Identity: existing `kagent-dev` users `reader` / `writer` (no Keycloak in `dealeriq`)
- `dealer-leads-mcp`: server, dataset, image, deployment, waypoint wiring
- Namespace, service accounts, ambient label for waypoints

Gate: tools callable through the gateway as `writer`; calls visible in traces.

### Phase 2 - Agents

- `dealer-assistant` (declarative): Agent + ModelConfig against the demo LLM route
- `dealer-assistant-byo`: LangGraph agent with SDK wiring at init (identity, checkpointer,
  HITL relay); image build; manifests

Gate: both agents answer lead-workflow questions in the kagent UI; both hit the MCP
server through the waypoint.

### Phase 3 - Policies + HITL

- AccessPolicy set: deny-all baseline, `reader` read tier, `writer` full tier,
  pre-staged live-edit policy
- Approval flag on `send_customer_offer`; shared-session approval flow
- End-to-end rehearsal of Demos 1–3

Gate: both personas produce the correct tool visibility; approval flow works from freeze
to completion; `export_leads` denied everywhere.

### Phase 4 - Observability + Circuit Breakers

- Demo LLM route + budget + rate limit manifests
- `drive-load.sh` calibrated so the budget trips in a predictable, demo-friendly window
- Budget reset path proven (spend state cleared between runs)
- Trace and dashboard walkthrough validated

Gate: Demo 4 rehearsable end-to-end twice in a row from `make demo-reset`.

### Phase 5 - Packaging + Rehearsal

- `Makefile`: `setup`, `deploy`, `seed`, `demo-reset`, `clean`
- `README.md` (architecture diagram included) + `RUNBOOK.md` built to the screen-safe
  spec below
- `scripts/validate.sh` pre-flight: controller healthy, MCP reachable, routes programmed,
  budget at zero, both personas authenticate
- Full clean-state rehearsal: `make clean && make setup && make deploy` then all four demos

Gate: complete run executed from scratch on the target cluster.

## Repeat-Delivery Tooling

| Target | Behavior |
|---|---|
| `make setup` | Namespace, copied secrets, images built/pushed |
| `make deploy` | MCP server, agents, policies, gateway resources |
| `make seed` | (Re)load the mock CRM/inventory dataset |
| `make demo-reset` | Zero the budget spend, clear demo chat sessions, restore baseline policies, re-seed MCP data. Does not delete Agents or CRDs. |
| `make clean` | Remove the `dealeriq` namespace; nothing else touched |

`validate.sh` runs before every delivery: fails fast with a named reason rather than
letting a demo fail live.

## Pre-Demo Checklist

- [ ] `validate.sh` green
- [ ] `make demo-reset` executed
- [ ] `reader` and `writer` log in successfully
- [ ] One warm-up turn per agent (model route warm, traces flowing)

## Build Order Summary

| Phase | Deliverable | Depends on |
|---|---|---|
| 0 | Three verified flows (HITL, approval flag, identity chain) | healthy kagent controller |
| 1 | MCP server live (existing `reader` / `writer` users) | 0c |
| 2 | Both agents live | 1 |
| 3 | Demos 1–3 rehearsable | 2, 0a, 0b |
| 4 | Demo 4 rehearsable | 2 |
| 5 | `make` lifecycle + runbook + full rehearsal | 3, 4 |

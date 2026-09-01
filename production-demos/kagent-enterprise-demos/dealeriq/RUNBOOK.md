# DealerIQ runbook

DealerIQ is the dealership AI assistant for inbound leads. BDC and sales management use the **same** assistant. AccessPolicy on the MCP waypoint decides which lead-management tools run: qualify a lead, match on-lot inventory, draft outreach, send a discounted offer, update lead status. The UI login is `reader` (BDC) or `writer` (sales manager). Those logins do not travel on the agent-to-MCP path on this cluster, so Demo 1 changes tools by applying policy, not by switching the username.

The working example is lead **4127**: Jordan Hale, used midsize pickup, $38,000 budget, this month. Stock **T-2201** is the matching Tacoma.

| Login | Role |
|---|---|
| `reader` | BDC / internet sales |
| `writer` | Sales manager |

One assistant, two builds: **dealer-assistant** (declarative kagent Agent) and **dealer-assistant-byo** (BYO LangGraph). Both call the same lead-management MCP server through agentgateway. Offers require a manager approval. Spend on the model route is capped.

These assistants are not part of the kagent install. `make deploy` applies them into the `dealeriq` namespace.

Blocks labeled **Prompt** are pasted into the kagent UI chat and sent. `bash` blocks are terminal commands.

## Before you go live

Run this page **before** screensharing starts.

### 1. Deploy the demo (first time on this cluster, or after `make clean`)

```bash
cd production-demos/kagent-enterprise-demos/dealeriq
make setup
make deploy
```

**What you'll see:** Images build and push, then `MCPServer/dealer-leads-mcp`, `Agent/dealer-assistant`, and `Agent/dealer-assistant-byo` become Ready. Skip this step if those three are already Ready.

### 2. Reset demo state and preflight

```bash
cd production-demos/kagent-enterprise-demos/dealeriq
make demo-reset
./scripts/validate.sh
```

**What you'll see:** `validate.sh green`. Both agents still listed. Lead 4127 is back to `new`.

### 3. Open the kagent UI

The goal of this section is just to show that the Agents are working prior to the demos.

```bash
kubectl get svc solo-enterprise-ui -n kagent -o jsonpath='{.status.loadBalancer.ingress[0].ip}{"\n"}'
```

If there is no LoadBalancer IP, port-forward `solo-enterprise-ui` in `kagent`.

>> SWITCH TO: browser > kagent UI (that IP, port 80)

- Log in as `reader`. Open **dealer-assistant**.

**Prompt:**

```
hello
```

Confirm a reply. Log out. Log in as `writer`. Open **dealer-assistant**. Send the same prompt. Confirm a reply.

>> SWITCH TO: agentgateway UI cost dashboard (warm traces only; do not start load yet)

---

## Demo 1: Same assistant, policy decides the tools (Governance: BYO vs. Declarative Agents)

The platform decides which lead-management tools the assistant can call. The agent spec lists eight tools either way. Baseline AccessPolicy is read-tier only for the assistant ServiceAccount. Both UI logins share that SA, so they see the same MCP tools until you apply a new policy.

### 1. Baseline

`reader` is a BDC rep. `writer` is a sales manager. Baseline AccessPolicy grants read tools only (`get_lead_details`, `score_lead`, `search_inventory`, `get_vehicle_history`, `draft_followup`). `export_leads` is granted to no one. `update_lead_status` and `send_customer_offer` are not granted yet.

### 2. Work a lead as reader

>> SWITCH TO: kagent UI > log in as `reader` > dealer-assistant

**Prompt:**

```
Work inbound lead 4127. Pull the details, score it, and match on-lot trucks to their budget.
```

**What you'll see:** The assistant uses lead details, scoring, and inventory search. It does not send an offer or change CRM status.

The facts in the reply (Jordan Hale, $38,000, T-2201 Tacoma, and so on) come from the MCP tools, not from the model inventing a CRM.

`mcp/data/leads.json`, `inventory.json`, and `history.json` are loaded into ConfigMap `dealer-leads-data` and mounted at `/data` on the `dealer-leads-mc`p pod. The agent calls tools such as `get_lead_details`, `score_lead`, and `search_inventory`. The model only writes the sentence around those results.

**Prompt:**

The below prompt is a `write` action, which means its out of scope for a reader.
```
Mark lead 4127 as qualified.
```

It'll say something along the lines of the below because `update_lead_status` is not in the allowed tool list. The assistant cannot change CRM status:

```
I currently don't have access to the update_lead_status tool in my available toolkit, so I'm unable to directly update the CRM status for Lead 4127 at this time.

Here's what I'd recommend:

Manually update Jordan Hale (Lead 4127) to "Qualified" in your CRM.
Key notes to log: Pre-approved at $38K, crew-cab pickup for towing, ready this month, has a 2016 Honda CR-V trade-in.
Would you like me to move forward with pulling vehicle history on the best inventory match and drafting a follow-up for Jordan?
```

### 3. Grant manager tools, then retry

>> SWITCH TO: terminal

```bash
kubectl apply -f policies/20-writer.yaml
```

**What you'll see:** The AccessPolicy is created.

>> SWITCH TO: kagent UI > log out > log in as `writer` > dealer-assistant > new chat

**Prompt:**

```
Work inbound lead 4127. Pull the details, score it, and match on-lot trucks to their budget.
```

**What you'll see:** The same workflow, plus manager tools are available.

**Prompt:**

```
Mark lead 4127 as qualified.
```

**What you'll see:** `update_lead_status` succeeds. This shows what the `reader` couldn't do.

### 4. Identity on the wire

>> SWITCH TO: terminal

```bash
kubectl get enterpriseagentgatewaypolicy accesspolicy-dealeriq-reader-read-tools-waypoint -n dealeriq -o jsonpath='{.spec.backend.mcp.authorization.policy.matchExpressions[0]}{"\n"}'
kubectl get enterpriseagentgatewaypolicy accesspolicy-dealeriq-writer-tools-waypoint -n dealeriq -o jsonpath='{.spec.backend.mcp.authorization.policy.matchExpressions[0]}{"\n"}'
```

^ Those policies are created when the Access Policies are created during the `make deploy` step.

**What you'll see:** CEL allow-lists keyed on `source.identity.serviceAccount` (`dealer-assistant` / `dealer-assistant-byo`) and `mcp.tool.name`. Same policies cover both agents. UI username is not on this path.

### 5. BYO parity

>> SWITCH TO: kagent UI > dealer-assistant-byo as `reader`

**Prompt:**

```
Work inbound lead 4127. Pull the details and score it.
```

**What you'll see:** The same policy set. No second copy of AccessPolicy for the LangGraph agent.

---

## Demo 2: Sessions belong to the platform (State & Session Management)

A conversation is stored centrally. Killing the pod does not drop context.

### 1. Declarative agent

>> SWITCH TO: kagent UI > `reader` > dealer-assistant

**Prompt:**

```
Pull details for lead 4127.
```

**Prompt:**

```
Score that lead and tell me which truck fits their budget.
```

**What you'll see:** The assistant refers to Jordan Hale and names stock such as T-2201 without being re-told the lead id.

>> SWITCH TO: terminal

```bash
kubectl delete pod -n dealeriq -l app.kubernetes.io/name=dealer-assistant
kubectl wait --for=condition=Ready agent/dealer-assistant -n dealeriq --timeout=180s
```

**What you'll see:** A new pod comes up.

>> SWITCH TO: kagent UI > the same session

**Prompt:**

```
Which truck did we match, and what was their budget?
```

**What you'll see:** Full context is intact after the restart.

### 2. BYO agent

Same sequence on **dealer-assistant-byo**. New chat. Same `reader` login.

>> SWITCH TO: kagent UI > `reader` > dealer-assistant-byo

**Prompt:**

```
Pull details for lead 4127.
```

**Prompt:**

```
Score that lead and tell me which truck fits their budget.
```

**What you'll see:** Jordan Hale and stock such as T-2201, same as the declarative agent.

>> SWITCH TO: terminal

```bash
kubectl delete pod -n dealeriq -l app.kubernetes.io/name=dealer-assistant-byo
kubectl wait --for=condition=Ready agent/dealer-assistant-byo -n dealeriq --timeout=300s
```

**What you'll see:** A new BYO pod comes up.

>> SWITCH TO: kagent UI > the same session

**Prompt:**

```
Which truck did we match, and what was their budget?
```

**What you'll see:** Full context is intact after the restart. Session state is not in the LangGraph pod.

**What you'll see:** Under **CHATS** in the left sidebar, that agent's conversations. Switch to **dealer-assistant-byo** to see its chats. Same UI, both runtimes. There is no separate Sessions tab.

---

## Demo 3: No discounted offer without a human (HITL)

`send_customer_offer` is approval-flagged on the Agent (`requireApproval`). AccessPolicy must also allow the tool, or the assistant cannot call it.

The freeze is real. Who may click Approve is not. kagent shows Approve / Reject to whoever has that chat open. Sessions are the **CHATS** list in the left sidebar, scoped to the current login. There is no Sessions tab and no manager-only approver.

>> SWITCH TO: kagent UI > `reader` > dealer-assistant > new chat

**Prompt:**

```
Send Jordan Hale an offer on stock T-2201 at $34,900, a $1,550 discount off list.
```

**What you'll see:** The tool does not execute. A card shows `send-customer-offer` with arguments (`lead_id` 4127, stock T-2201, price, discount) and **Approve** / **Reject**. Leave it pending while you talk. Do not treat the buttons as reader-blocked.

Click **Approve**.

**What you'll see:** The offer is sent. The session records the approval and the tool result.

The same freeze-and-approve path is available on **dealer-assistant-byo**.

---

## Demo 4: Visible, attributable, capped (Observability & Circuit Breakers)

Every token, tool call, and approval is in the trace. Spend is capped on the demo LLM route.

### 1. Trace

>> SWITCH TO: kagent UI tracing (or management traces) for the Demo 3 session

**What you'll see:** Model, token counts, tool calls, and the approval decision on one trace. Declarative and BYO traces share the same pipeline.

### 2. Cost dashboard

>> SWITCH TO: agentgateway UI > cost dashboard

**What you'll see:** Spend for `claude-sonnet-4-6` from the demo traffic.

### 3. Circuit breaker

This is backend health eviction. The mock route has two providers: `failing` (always 500) then `healthy` (always 200). Both are required. Eviction only takes an unhealthy provider out of rotation. If `failing` is the only provider, Agentgateway still sends traffic to it after eviction, so every request stays 500 and the trip is invisible. `healthy` is the failover target, so after 3 consecutive 5xx you see HTTP 200. Claude on `/anthropic` is unchanged.

>> SWITCH TO: terminal

```bash
kubectl apply -f gateway/circuit-breaker.yaml
kubectl wait --for=condition=Available deploy/dealeriq-mock-llm deploy/dealeriq-mock-llm-ok -n dealeriq --timeout=180s
kubectl rollout restart deploy/dealeriq-llm -n dealeriq
kubectl rollout status deploy/dealeriq-llm -n dealeriq --timeout=180s
```

**What you'll see:** Policy Accepted, attached to `EnterpriseAgentgatewayBackend/dealeriq-mock-llm`, with both mock providers available. Restarting only the demo gateway clears its in-memory provider health state so this demonstration starts clean. After 3 consecutive 5xx the `failing` provider is evicted for 5 minutes.

```bash
./scripts/trip-circuit.sh
```

**What you'll see:** Requests 1-3 return HTTP 500 (`mock llm injected 500`). Later requests return HTTP 200 (`healthy mock: failover after circuit breaker eviction`). That is the circuit breaker.

For another clean `500 x3` demonstration, repeat the gateway restart and rollout-status commands first. Agentgateway retains the failing provider's consecutive-failure count after an eviction expires and increases the duration of repeated evictions, so waiting five minutes alone does not reset the sequence.

The proof is the **endpoint** on the gateway log, not the script alone.

```bash
kubectl logs -n dealeriq deploy/dealeriq-llm --since=5m | grep path=/mock-llm
```

**What you'll see:** `http.status=500` with `endpoint=dealeriq-mock-llm.dealeriq.svc.cluster.local:8080` (failing). Then `http.status=200` with `endpoint=dealeriq-mock-llm-ok.dealeriq.svc.cluster.local:8080` (healthy). Same path `/mock-llm`. That is the failover.

## RESET

Reset spend and policies before the next delivery:

```bash
make demo-reset
```

#### Bonus: Rate Limiting

>> SWITCH TO: terminal

```bash
kubectl apply -f gateway/budget.yaml -f gateway/rate-limit.yaml
```

The policies above set up:
- Token budget (4,000 tokens per day, then Block)
- Request rate limiting (40 requests/minute)

>> SWITCH TO: agentgateway UI > Cost Management > Budgets > `dealeriq-daily-token-budget`

**What you'll see:** Entry `dealeriq-claude-daily`, 4,000 tokens, daily window in the **Budgets** tab

Run load to your cluster:

```bash
./scripts/drive-load.sh
```

**What you'll see:** Some HTTP 200s, then 429. Do not run `./scripts/reset-budget-counter.sh` after that. Resetting zeros spend so the next chat is allowed again.

If every request is 429 and there was never a 200:

```bash
./scripts/reset-budget-counter.sh
./scripts/drive-load.sh
```

>> SWITCH TO: kagent UI > dealer-assistant

**Prompt:**

```
Score lead 4127 again.
```

**What you'll see:** `rate limit exceeded`. The gateway uses that 429 string for a token-budget block too.

>> SWITCH TO: terminal

```bash
kubectl logs -n dealeriq deploy/dealeriq-llm --tail=20
```

**What you'll see:** `budget exceeded; blocking...` for `dealeriq-claude-daily`, `budget_limit=4000`, `outcome=over_limit_block`.

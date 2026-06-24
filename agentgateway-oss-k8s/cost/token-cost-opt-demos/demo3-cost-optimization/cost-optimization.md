---
title: "LLM Cost Optimization & Control on agentgateway OSS (routing, CEL cost policy, token budgets)"
date: 2026-06-22
description: "Demo 3 of the agentgateway cost series: route to cheap models by default and escalate to premium on demand, tag/slice spend with CEL cost attributes, and enforce token budgets with native rate limiting."
tags: ["agentgateway", "kubernetes", "llm", "cost", "routing", "rate-limiting", "cel", "finops"]
author: "adminturneddevops"
---

# Demo 3 — Cost Optimization & Control

Demos 1–2 made cost observable and chargeable. Demo 3 acts on it:

- **C-8 Cost-aware model routing** — cheap model by default, premium only when escalated.
- **C-9 CEL cost policy** — tag and slice spend using `llm.cost.total`.
- **C-10 Budget enforcement** — cap token spend with **native** rate limiting (not a custom service).

This is the third of four demos (visibility, management, **optimization & control**, MCP savings).

## Prerequisites

- **Demos 1 & 2 deployed and working**: gateways `team-a` (`claude-sonnet-4-5`) and `team-b` (`claude-opus-4-1`), kube-prometheus-stack with Demo 2's chargeback recording rules, the imported catalog ConfigMap, and the `anthropic-key` Secret in both namespaces.
- agentgateway controller + CRDs v1.3.0.
- An Anthropic key with access to both `claude-sonnet-4-5` and `claude-opus-4-1`.
- CLI tools: `kubectl`, `jq`, `curl`.

## Reality check

Budget enforcement here is **native agentgateway config** — `traffic.rateLimit` with token limits. Earlier notes that called this a "gap" requiring a custom authz service were wrong: agentgateway ships token/cost-aware rate limiting. C-10 uses it directly.

Port-forward team-a for the curl steps (as in Demo 1):

```bash
kubectl -n team-a port-forward svc/team-a 8080:8080 >/tmp/pf-a.log 2>&1 &
sleep 2
```

---

## C-8 — Cost-aware model routing

Add a premium (opus) backend in `team-a` next to the cheap (sonnet) one, then route by request intent: default traffic → sonnet; requests with header `x-priority: high` → opus.

```bash
kubectl apply -f - <<'EOF'
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: anthropic-premium
  namespace: team-a
spec:
  ai:
    provider:
      anthropic:
        model: claude-opus-4-1
  policies:
    auth:
      secretRef:
        name: anthropic-key
EOF
```

Update the team-a route: the rule with the header match is more specific, so escalated requests go to opus; everything else falls through to sonnet.

```bash
kubectl apply -f - <<'EOF'
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: llm
  namespace: team-a
spec:
  parentRefs:
  - name: team-a
  rules:
  # Escalated: premium model
  - matches:
    - path:
        type: PathPrefix
        value: /v1/chat/completions
      headers:
      - type: Exact
        name: x-priority
        value: high
    backendRefs:
    - group: agentgateway.dev
      kind: AgentgatewayBackend
      name: anthropic-premium
  # Default: cheap model
  - matches:
    - path:
        type: PathPrefix
        value: /v1/chat/completions
    backendRefs:
    - group: agentgateway.dev
      kind: AgentgatewayBackend
      name: anthropic
EOF
```

Send mixed traffic — mostly default, a few escalated:

```bash
for i in $(seq 1 15); do
  curl -s localhost:8080/v1/chat/completions -H 'content-type: application/json' \
    -d '{"model":"x","messages":[{"role":"user","content":"One-line definition of a pod."}]}' >/dev/null
done
for i in $(seq 1 3); do
  curl -s localhost:8080/v1/chat/completions -H 'content-type: application/json' -H 'x-priority: high' \
    -d '{"model":"x","messages":[{"role":"user","content":"Design a multi-region failover architecture in detail."}]}' >/dev/null
done
```

Confirm cost concentrated on the cheap model, with opus only for escalated calls (uses Demo 2's recording rule):

```promql
model:llm_cost_usd:rate5m * 3600
```

or by tokens:

```promql
sum by (gen_ai_request_model) (rate(agentgateway_gen_ai_client_token_usage_sum[5m]))
```

**Variants (optional):**
- *Weighted split* — give the default rule two `backendRefs` with `weight: 80` (sonnet) / `weight: 20` (opus) to distribute a fixed fraction to premium.
- *Cheap-primary / premium-fallback* — one `AgentgatewayBackend` with `spec.ai.groups` (priority 0 sonnet, priority 1 opus) plus an `AgentgatewayPolicy` `backend.health` eviction policy, so premium is used only when the cheap tier is unhealthy (cost + resilience).

---

## C-9 — CEL cost policy (tag and slice)

Add cost-derived fields via the gateway's static config (`AgentgatewayParameters.rawConfig`): a request-log boolean `expensive` and a low-cardinality metric label `cost_tier`. Both use the `llm.cost.total` CEL attribute (USD, evaluated post-response).

```bash
kubectl apply -f - <<'EOF'
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayParameters
metadata:
  name: team-a-params
  namespace: team-a
spec:
  logging:
    format: json
  modelCatalog:
    sources:
    - configMap:
        name: model-catalog
        key: catalog.json
  rawConfig:
    config:
      logging:
        fields:
          add:
            expensive: "llm.cost.total > 0.01"
      metrics:
        fields:
          add:
            cost_tier: "llm.cost.total > 0.01 ? 'high' : 'low'"
EOF
```

Static-config change → restart, then drive traffic:

```bash
kubectl rollout restart deploy -n team-a -l gateway.networking.k8s.io/gateway-name=team-a
kubectl rollout status deploy -n team-a -l gateway.networking.k8s.io/gateway-name=team-a --timeout=120s
# (re-run the C-8 traffic loop)
```

See the tag in the access log:

```bash
kubectl logs -n team-a deploy/team-a --tail=100 \
  | jq -r 'select(."agw.ai.usage.cost.total"!=null)
           | "\(.expensive)\t$\(."agw.ai.usage.cost.total")\t\(."gen_ai.request.model")"'
```

Slice tokens by cost tier in Prometheus:

```promql
sum by (cost_tier) (rate(agentgateway_gen_ai_client_token_usage_sum[5m]))
```

`cost_tier` stays 2-valued (`high`/`low`) to keep metric cardinality bounded.

---

## C-10 — Budget enforcement (native token rate limit)

Cap token spend with `traffic.rateLimit`. This `local` limit is per-proxy and returns **429** once the window's token budget is consumed. A deliberately low budget makes it easy to demonstrate.

```bash
kubectl apply -f - <<'EOF'
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: team-a-token-budget
  namespace: team-a
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: llm
  traffic:
    rateLimit:
      local:
      - tokens: 2000
        unit: Minutes
EOF
```

Loop until the budget is spent and watch the status flip to 429:

```bash
for i in $(seq 1 25); do
  code=$(curl -s -o /dev/null -w '%{http_code}' localhost:8080/v1/chat/completions \
    -H 'content-type: application/json' \
    -d '{"model":"x","messages":[{"role":"user","content":"Summarize the CAP theorem."}]}')
  echo "request $i -> $code"
done
```

You'll see `200`s, then `429`s once ~2000 tokens/minute are used.

> **Timing note:** token usage is known only after a request completes, so token limits apply to *subsequent* requests — the request that crosses the budget still completes; the next ones are rejected. Wait a minute and the budget refills.

### Local vs global

`local` (above) counts **per replica** — with N gateway pods the effective budget is N× what you set, and counters reset on restart. For a **cluster-wide** budget (e.g. an org/team daily cap), use `global`: a shared Envoy rate-limit server backed by Redis keeps one counter across all replicas. Standard prebuilt images, no custom application.

| | `local` | `global` |
|---|---|---|
| Counter scope | per replica | cluster-wide (Redis) |
| External deps | none | ratelimit server + Redis |
| Survives restart | no | yes |
| Best for | quick per-pod guardrail | real daily/org budgets |

## C-11 — Global / cross-replica token budget (daily team cap)

Enforce one shared daily token budget for all of team-a's traffic, regardless of replica count.

**Deploy the rate-limit server.** It's the same Envoy `ratelimit` + Redis stack used by Demo 2's virtual-keys. If you already ran Demo 2 Step 1, it's deployed — just make sure its `ratelimit-config` ConfigMap includes the `team` descriptor below and restart it. Otherwise apply Demo 2 virtual-keys **Step 1** first, then replace the ConfigMap:

```bash
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: ratelimit-config
  namespace: team-a
data:
  config.yaml: |
    domain: token-budgets
    descriptors:
      # per-user budget (virtual-keys demo)
      - key: user_id
        rate_limit: { unit: minute, requests_per_unit: 2000 }
      # org/team daily token budget (this demo)
      - key: team
        rate_limit: { unit: day, requests_per_unit: 1000000 }
EOF
kubectl rollout restart deploy/ratelimit -n team-a
kubectl rollout status deploy/ratelimit -n team-a --timeout=120s
```

**Apply the global budget policy** on the team-a route. The descriptor is a constant `team` value, so all team-a traffic shares one daily token counter:

```bash
kubectl apply -f - <<'EOF'
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: team-a-daily-budget
  namespace: team-a
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: llm
  traffic:
    rateLimit:
      global:
        domain: token-budgets
        failureMode: failClosed
        backendRef:
          name: ratelimit
          port: 8081
        descriptors:
        - entries:
          - name: team
            expression: '"team-a"'
          unit: Tokens
EOF
```

Drive traffic and confirm enforcement is shared (scale the gateway to 2 replicas and the budget still holds, unlike `local`):

```bash
for i in $(seq 1 10); do
  echo "req $i -> $(curl -s -o /dev/null -w '%{http_code}' localhost:8080/v1/chat/completions \
    -H 'content-type: application/json' \
    -d '{"model":"x","messages":[{"role":"user","content":"Explain consistent hashing."}]}')"
done
# inspect the RLS decision log
kubectl logs -n team-a deploy/ratelimit --tail=20 | grep -iE 'OVER_LIMIT|OK' || true
```

Lower `requests_per_unit` (or `unit: minute`) to make the `429` easy to hit in the demo; set `unit: day` with your real budget for production.

---

## Teardown (Demo 3 additions only)

```bash
kubectl delete agentgatewaypolicy team-a-token-budget team-a-daily-budget -n team-a
kubectl delete agentgatewaybackend anthropic-premium -n team-a
# Global RLS (if you deployed it only for C-11 and not Demo 2 virtual-keys):
kubectl delete deploy ratelimit redis -n team-a 2>/dev/null
kubectl delete svc ratelimit redis -n team-a 2>/dev/null
kubectl delete configmap ratelimit-config -n team-a 2>/dev/null
# Revert the team-a HTTPRoute to the single default rule (re-apply Demo 1's route),
# and revert team-a-params to remove the rawConfig fields if desired, then rollout restart.
```

Demos 1–2 teardown removes the rest.

## Notes / scope

- C-8 routing decisions here are explicit (header/weight/priority). Classifier-driven "intelligent" routing (ext_proc / semantic) is a separate pattern — see the repo's semantic-routing example.
- CEL cost fields evaluate post-response; they describe the request just served.
- MCP cost/token savings (tool virtualization) is **Demo 4**.

---
title: "LLM Cost Management on agentgateway OSS (catalog, chargeback, tiered pricing, cache savings)"
date: 2026-06-22
description: "Demo 2 of the agentgateway cost series: import a model-cost catalog, attribute spend per team/gateway with Prometheus recording rules, demonstrate context-tiered pricing, and quantify prompt-cache savings."
tags: ["agentgateway", "kubernetes", "llm", "cost", "finops", "chargeback", "catalog", "prometheus"]
author: "adminturneddevops"
---

# Demo 2 — Cost Management

Demo 1 made tokens and per-request cost observable. Demo 2 turns that into **cost management**:

- **B-4 Catalog setup** — import real prices from models.dev into the gateways.
- **B-5 Attribution / chargeback** — derive dollars per team/gateway in Prometheus + Grafana.
- **B-6 Tiered pricing** — show cost jump when a request crosses a context-size tier.
- **B-7 Cache savings** — quantify prompt-cache savings on Anthropic.

This is the second of four demos (visibility, **management**, optimization & control, MCP savings).

## Prerequisites

- **Demo 1 deployed and working**: gateways `team-a` (model `claude-sonnet-4-5`) and `team-b` (model `claude-opus-4-1`), kube-prometheus-stack, the `anthropic-key` Secret in both namespaces, and the `agentgateway-llm` ServiceMonitor. Traffic verified.
- agentgateway controller + CRDs v1.3.0, and the **`agctl` v1.3.0** CLI on your PATH (ships with the agentgateway controller release — see the [quickstart](https://agentgateway.dev/docs/kubernetes/latest)).
- Cluster egress to `models.dev` (catalog import) and `api.anthropic.com`.
- CLI tools: `kubectl`, `jq`, `curl`.
- `agctl` installed: https://agentgateway.dev/docs/kubernetes/main/operations/agctl/

---

## B-4 — Catalog setup

agentgateway records **tokens** as Prometheus metrics, but **dollar cost is not a native metric** — `cost_catalog_lookups` only counts catalog lookups by status. Per-request dollars land in the access log (`agw.ai.usage.cost.total`) and the built-in UI; **per-gateway dollars for dashboards are *derived*** (tokens × catalog rate) via Prometheus recording rules. That's the approach in B-5.

### Import a real catalog

`agctl costs import` pulls public pricing from models.dev and emits the catalog JSON the gateway consumes (rates are USD per 1,000,000 tokens).

```bash
agctl costs import --source models.dev --providers anthropic,openai,google --pretty -o catalog.json
```

Trimmed shape (provider keys are the gateway's provider ids — note Google lands under `gcp.gemini`):

```json
{
  "providers": {
    "anthropic": {
      "models": {
        "claude-sonnet-4-5": { "rates": { "input": "3", "output": "15", "cacheRead": "0.3", "cacheWrite": "3.75" } },
        "claude-opus-4-1":   { "rates": { "input": "15", "output": "75", "cacheRead": "1.5", "cacheWrite": "18.75" } }
      }
    }
  }
}
```

### Replace the catalog ConfigMap in both namespaces

This supersedes Demo 1's minimal inline catalog with the imported one. The data key stays `catalog.json` (matching the `AgentgatewayParameters.modelCatalog.sources[].configMap.key` from Demo 1).

```bash
for ns in team-a team-b; do
  kubectl create configmap model-catalog --from-file=catalog.json \
    -n "$ns" --dry-run=client -o yaml | kubectl apply -f -
done
```

### Apply an updated rate

> ⚠️ **On Kubernetes the catalog ConfigMap is mounted with `subPath`, so editing it does NOT live-reload.** The proxy's file-watch reload is a standalone-mode behavior. To apply new rates on K8s you must re-apply the ConfigMap **and restart** the gateway pods.

```bash
# edit a rate in catalog.json, re-apply (command above), then:
kubectl rollout restart deploy -n team-a -l gateway.networking.k8s.io/gateway-name=team-a
kubectl rollout restart deploy -n team-b -l gateway.networking.k8s.io/gateway-name=team-b
```

Drive a little traffic (Demo 1's curl loop) and confirm `agw.ai.usage.cost.total` reflects the new rate (see the jq command in B-5).

---

## B-5 — Attribution / chargeback (per team/gateway)

### Derive dollars with a recording rule

This `PrometheusRule` multiplies token rates by the catalog rates (kept in sync manually — values must match `catalog.json`) and sums by `gateway`. kube-prometheus-stack's Prometheus discovers rules labeled `release: kube-prometheus-stack`.

```bash
kubectl apply -f - <<'EOF'
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: agentgateway-chargeback
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  groups:
  - name: agentgateway-chargeback
    rules:
    # USD/sec by gateway (rates per 1e6 tokens; keep in sync with catalog.json)
    - record: gateway:llm_cost_usd:rate5m
      expr: |
        sum by (gateway) (
            rate(agentgateway_gen_ai_client_token_usage_sum{gen_ai_request_model="claude-sonnet-4-5", gen_ai_token_type="input"}[5m])  * 3  / 1e6
          + rate(agentgateway_gen_ai_client_token_usage_sum{gen_ai_request_model="claude-sonnet-4-5", gen_ai_token_type="output"}[5m]) * 15 / 1e6
          + rate(agentgateway_gen_ai_client_token_usage_sum{gen_ai_request_model="claude-opus-4-1",   gen_ai_token_type="input"}[5m])  * 15 / 1e6
          + rate(agentgateway_gen_ai_client_token_usage_sum{gen_ai_request_model="claude-opus-4-1",   gen_ai_token_type="output"}[5m]) * 75 / 1e6
        )
    # USD/sec by model
    - record: model:llm_cost_usd:rate5m
      expr: |
        (
          sum by (gen_ai_request_model) (rate(agentgateway_gen_ai_client_token_usage_sum{gen_ai_request_model="claude-sonnet-4-5", gen_ai_token_type="input"}[5m]))  * 3  / 1e6
          + sum by (gen_ai_request_model) (rate(agentgateway_gen_ai_client_token_usage_sum{gen_ai_request_model="claude-sonnet-4-5", gen_ai_token_type="output"}[5m])) * 15 / 1e6
        )
        or
        (
          sum by (gen_ai_request_model) (rate(agentgateway_gen_ai_client_token_usage_sum{gen_ai_request_model="claude-opus-4-1", gen_ai_token_type="input"}[5m]))  * 15 / 1e6
          + sum by (gen_ai_request_model) (rate(agentgateway_gen_ai_client_token_usage_sum{gen_ai_request_model="claude-opus-4-1", gen_ai_token_type="output"}[5m])) * 75 / 1e6
        )
    # Cumulative USD over 1h by gateway (chargeback window)
    - record: gateway:llm_cost_usd:increase1h
      expr: |
        sum by (gateway) (
            increase(agentgateway_gen_ai_client_token_usage_sum{gen_ai_request_model="claude-sonnet-4-5", gen_ai_token_type="input"}[1h])  * 3  / 1e6
          + increase(agentgateway_gen_ai_client_token_usage_sum{gen_ai_request_model="claude-sonnet-4-5", gen_ai_token_type="output"}[1h]) * 15 / 1e6
          + increase(agentgateway_gen_ai_client_token_usage_sum{gen_ai_request_model="claude-opus-4-1",   gen_ai_token_type="input"}[1h])  * 15 / 1e6
          + increase(agentgateway_gen_ai_client_token_usage_sum{gen_ai_request_model="claude-opus-4-1",   gen_ai_token_type="output"}[1h]) * 75 / 1e6
        )
EOF
```

Confirm in Prometheus:

```promql
gateway:llm_cost_usd:rate5m
gateway:llm_cost_usd:increase1h
```

Import `chargeback-dashboard.json` into Grafana for the $/gateway, $/model, and cumulative-$ chargeback view.

### Optional — built-in pricing view

The proxy serves the active catalog at `GET /api/costs/models` on the admin/UI listener (default port `15000`, localhost-bound; reachable via port-forward to the pod).

```bash
POD=$(kubectl get pod -n team-a -l gateway.networking.k8s.io/gateway-name=team-a -o name | head -1)
kubectl -n team-a port-forward "$POD" 15000:15000 >/tmp/pf-admin.log 2>&1 &
sleep 2
curl -s localhost:15000/api/costs/models | jq '.[0:3]'
```

> Per-request **spend analytics** (sum cost over time, grouped) in the UI require the sqlite log store (`config.database`), which is single-instance and not multi-replica friendly — out of scope here. The recording-rule path above is the portable chargeback mechanism.

---

## B-6 — Tiered / long-context pricing

Catalog `tiers` apply higher rates once a request's context exceeds `contextOver` tokens. We add a low threshold to `claude-sonnet-4-5` (team-a) so a modest prompt crosses it without a huge payload.

Patch the team-a catalog to add tiers, then restart (subPath caveat applies):

```bash
# In catalog.json, set the anthropic claude-sonnet-4-5 entry to include tiers:
#   "claude-sonnet-4-5": {
#     "rates": { "input": "3", "output": "15", "cacheRead": "0.3", "cacheWrite": "3.75" },
#     "tiers": [ { "contextOver": 2000,
#                  "rates": { "input": "6", "output": "30", "cacheRead": "0.6", "cacheWrite": "7.5" } } ]
#   }
kubectl create configmap model-catalog --from-file=catalog.json \
  -n team-a --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deploy -n team-a -l gateway.networking.k8s.io/gateway-name=team-a
kubectl rollout status deploy -n team-a -l gateway.networking.k8s.io/gateway-name=team-a --timeout=120s
```

Send a small prompt (under the tier) and a large one (over ~2000 input tokens), then compare cost in the access log:

```bash
# small
curl -s localhost:8080/v1/chat/completions -H 'content-type: application/json' \
  -d '{"model":"claude-sonnet-4-5","messages":[{"role":"user","content":"Define idempotency in one line."}]}' >/dev/null

# large: repeat a filler paragraph to exceed the context tier
BIG=$(python3 -c "print('Explain this kubernetes concept in detail. ' * 400)")
curl -s localhost:8080/v1/chat/completions -H 'content-type: application/json' \
  -d "$(jq -nc --arg c "$BIG" '{model:"claude-sonnet-4-5",messages:[{role:"user",content:$c}]}')" >/dev/null

kubectl logs -n team-a deploy/team-a --tail=100 \
  | jq -r 'select(."agw.ai.usage.cost.total"!=null)
           | "\(."gen_ai.usage.input_tokens") in-tokens  ->  $\(."agw.ai.usage.cost.total")"'
```

The large request prices at the tier rate (2× here), so its cost-per-token is higher once it crosses `contextOver`.

---

## B-7 — Cache savings (Anthropic prompt caching)

Enable prompt caching on the team-a Anthropic backend with an `AgentgatewayPolicy`. The gateway inserts cache markers; repeated prompt prefixes then bill at the cheaper `cacheRead` rate instead of full `input`.

```bash
kubectl apply -f - <<'EOF'
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: anthropic-prompt-caching
  namespace: team-a
spec:
  targetRefs:
  - group: agentgateway.dev
    kind: AgentgatewayBackend
    name: anthropic
  backend:
    ai:
      promptCaching:
        cacheSystem: true
        cacheMessages: true
        minTokens: 1024
EOF
```

Send the same large prompt twice (the first warms the cache, the second reads it):

```bash
BIG=$(python3 -c "print('You are a Kubernetes expert. Context: ' + ('lorem ipsum dolor sit amet ' * 400))")
REQ=$(jq -nc --arg c "$BIG" '{model:"claude-sonnet-4-5",messages:[{role:"user",content:($c + " Q: what is a sidecar?")}]}')

curl -s localhost:8080/v1/chat/completions -H 'content-type: application/json' -d "$REQ" >/dev/null  # warm
sleep 2
curl -s localhost:8080/v1/chat/completions -H 'content-type: application/json' -d "$REQ" >/dev/null  # read

kubectl logs -n team-a deploy/team-a --tail=50 \
  | jq -r 'select(."agw.ai.usage.cost.total"!=null)
           | {input: ."gen_ai.usage.input_tokens",
              cache_read: ."gen_ai.usage.cache_read.input_tokens",
              cache_write: ."gen_ai.usage.cache_creation.input_tokens",
              cost: ."agw.ai.usage.cost.total"}'
```

On the second call, `cache_read.input_tokens` is populated and `agw.ai.usage.cost.total` is lower — the cached prefix billed at `cacheRead` ($0.30/1M) instead of `input` ($3.00/1M), a 10× reduction on those tokens.

> Cache reporting is provider-dependent: the model + key must actually return cache-creation/cache-read usage for the numbers to appear.

---

## Teardown (Demo 2 additions only)

```bash
kubectl delete prometheusrule agentgateway-chargeback -n monitoring
kubectl delete agentgatewaypolicy anthropic-prompt-caching -n team-a
# Revert the catalog ConfigMaps if desired (re-apply Demo 1's minimal catalog), or leave the imported one.
```

Demo 1's teardown removes the gateways, namespaces, and monitoring stack.

## Notes / scope

- Recording-rule rates are **hardcoded to match `catalog.json`** — if you change catalog rates, update the rule too. (The proxy prices requests from the catalog; the rule is a separate Prometheus-side derivation for charts.)
- Optimization/control (cost-aware routing, native token rate-limit budgets, CEL cost policy) is **Demo 3**.

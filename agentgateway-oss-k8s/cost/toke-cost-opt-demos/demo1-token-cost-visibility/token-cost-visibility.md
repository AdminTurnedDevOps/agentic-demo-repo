---
title: "Token & Cost Visibility per Gateway (agentgateway OSS on Kubernetes)"
date: 2026-06-22
description: "Demo 1 of the agentgateway cost series: expose per-gateway LLM token and latency metrics in Prometheus/Grafana and surface per-request dollar cost in the access log, using two Anthropic-backed gateways."
tags: ["agentgateway", "kubernetes", "llm", "tokens", "cost", "prometheus", "grafana", "observability"]
author: "adminturneddevops"
---

# Demo 1 — Token & Cost Visibility (per gateway)

Goal: prove the agentgateway dataplane emits **per-gateway** LLM telemetry out of the box, and that **per-request dollar cost** lands in the access log.

We deploy two gateways — `team-a` and `team-b` — each routing to Anthropic with a different model. Because every LLM metric carries a `gateway` label, Prometheus/Grafana can slice token and latency usage per gateway, per model, and per provider with zero extra configuration. A small model-cost catalog turns token counts into dollars in the access log.

This is the first of four demos (the others: cost management, cost optimization & control, MCP cost savings).

## What you'll see

- `agentgateway_gen_ai_client_token_usage` (input/output tokens) sliced by `gateway`, `gen_ai_request_model`, `gen_ai_system`.
- Latency histograms: `agentgateway_gen_ai_server_time_to_first_token`, `agentgateway_gen_ai_server_time_per_output_token`, `agentgateway_gen_ai_server_request_duration`.
- A Grafana dashboard (`grafana-dashboard.json`) built fresh for this demo.
- Per-request access-log lines carrying `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, and `agw.ai.usage.cost.total`.

## Prerequisites

- Kubernetes cluster, version 1.29 or newer
- Gateway API CRDs v1.2.0 (standard channel)
- agentgateway controller + CRDs, v1.3.0 (install per the [Kubernetes quickstart](https://agentgateway.dev/docs/kubernetes/latest))
- kube-prometheus-stack (provides the Prometheus Operator `ServiceMonitor` CRD and Grafana)
- An Anthropic API key exported as the `ANTHROPIC_API_KEY` environment variable; cluster egress to `api.anthropic.com`
- CLI tools: `kubectl`, `helm` 3.14+, `jq`, `curl`

## Architecture

```text
curl (OpenAI-format) ─▶ Gateway team-a ─▶ HTTPRoute ─▶ AgentgatewayBackend (Anthropic, sonnet) ─▶ api.anthropic.com
                     ─▶ Gateway team-b ─▶ HTTPRoute ─▶ AgentgatewayBackend (Anthropic, opus)   ─▶ api.anthropic.com
                                              │
                       gen_ai_* metrics (gateway/model/provider labels) ─▶ Prometheus ─▶ Grafana
                       access log (tokens + agw.ai.usage.cost.total)     ─▶ stdout (JSON) ─▶ kubectl logs | jq
```

---

## Step 0 — Install the platform dependencies

Install the agentgateway controller + CRDs (this also registers the `agentgateway` GatewayClass) following the official quickstart linked above, and install kube-prometheus-stack:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --version 77.6.0 \
  --namespace monitoring --create-namespace
```

Confirm the `agentgateway` GatewayClass is registered:

```bash
kubectl get gatewayclass agentgateway
```

## Step 1 — Namespaces

One namespace per team gateway, plus the monitoring namespace was created in Step 0.

```bash
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: team-a
---
apiVersion: v1
kind: Namespace
metadata:
  name: team-b
EOF
```

## Step 2 — Anthropic API key Secret (per namespace)

The gateway reads the credential from a Secret data key named `Authorization` and injects it upstream (it strips a leading `Bearer ` if present). The key is sourced from your env var — never written into the manifest.

```bash
# Make sure the key is exported first:  export ANTHROPIC_API_KEY=sk-ant-...
kubectl create secret generic anthropic-key \
  --from-literal=Authorization="$ANTHROPIC_API_KEY" -n team-a

kubectl create secret generic anthropic-key \
  --from-literal=Authorization="$ANTHROPIC_API_KEY" -n team-b
```

## Step 3 — Model-cost catalog ConfigMap (per namespace)

Cost in the access log requires a catalog so the gateway knows per-token rates. Rates are US dollars per 1,000,000 tokens. This is a minimal inline catalog for just the two models used here; full catalog management (import from models.dev, hot-reload) is Demo 2. The ConfigMap must live in the same namespace as the Gateway that references it.

```bash
for ns in team-a team-b; do
kubectl apply -n "$ns" -f - <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: model-catalog
data:
  catalog.json: |
    {
      "providers": {
        "anthropic": {
          "models": {
            "claude-sonnet-4-5": {
              "rates": { "input": "3", "output": "15", "cacheRead": "0.3", "cacheWrite": "3.75" }
            },
            "claude-opus-4-1": {
              "rates": { "input": "15", "output": "75", "cacheRead": "1.5", "cacheWrite": "18.75" }
            }
          }
        }
      }
    }
EOF
done
```

## Step 4 — AgentgatewayParameters (per gateway)

Each gateway gets its own parameters: JSON logging (so the access log — including cost — is structured) and a reference to its model-catalog ConfigMap. Model-catalog references are only honored on Gateway-level parameters (referenced from `Gateway.spec.infrastructure.parametersRef`).

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
---
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayParameters
metadata:
  name: team-b-params
  namespace: team-b
spec:
  logging:
    format: json
  modelCatalog:
    sources:
    - configMap:
        name: model-catalog
        key: catalog.json
EOF
```

## Step 5 — Gateways

Two Gateways on the `agentgateway` class, each pointing at its own parameters via `infrastructure.parametersRef`. The `gateway` metric label is derived from these resource names.

```bash
kubectl apply -f - <<'EOF'
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: team-a
  namespace: team-a
spec:
  gatewayClassName: agentgateway
  infrastructure:
    parametersRef:
      group: agentgateway.dev
      kind: AgentgatewayParameters
      name: team-a-params
  listeners:
  - name: http
    protocol: HTTP
    port: 8080
    allowedRoutes:
      namespaces:
        from: Same
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: team-b
  namespace: team-b
spec:
  gatewayClassName: agentgateway
  infrastructure:
    parametersRef:
      group: agentgateway.dev
      kind: AgentgatewayParameters
      name: team-b-params
  listeners:
  - name: http
    protocol: HTTP
    port: 8080
    allowedRoutes:
      namespaces:
        from: Same
EOF
```

## Step 6 — AgentgatewayBackends (Anthropic)

One backend per team, each pinned to a different Anthropic model and authenticated from the Secret created in Step 2. With `provider.anthropic.model` set, the gateway uses that model regardless of the model in the request body.

```bash
kubectl apply -f - <<'EOF'
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: anthropic
  namespace: team-a
spec:
  ai:
    provider:
      anthropic:
        model: claude-sonnet-4-5
  policies:
    auth:
      secretRef:
        name: anthropic-key
---
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: anthropic
  namespace: team-b
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

## Step 7 — HTTPRoutes

Route the OpenAI-compatible chat path to each backend. agentgateway exposes a unified OpenAI-compatible surface and translates to Anthropic upstream.

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
  - matches:
    - path:
        type: PathPrefix
        value: /v1/chat/completions
    backendRefs:
    - group: agentgateway.dev
      kind: AgentgatewayBackend
      name: anthropic
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: llm
  namespace: team-b
spec:
  parentRefs:
  - name: team-b
  rules:
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

## Step 8 — ServiceMonitor (our own)

Scrape the gateway proxy metrics endpoint. agentgateway serves Prometheus metrics on the `metrics` port at `/metrics`. This ServiceMonitor selects both gateways by their gateway-class label across the two namespaces.

> The `release: kube-prometheus-stack` label makes this discoverable by the stack's Prometheus (its default `serviceMonitorSelector`). Adjust if your Prometheus uses a different selector.

```bash
kubectl apply -f - <<'EOF'
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: agentgateway-llm
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  namespaceSelector:
    matchNames:
    - team-a
    - team-b
  selector:
    matchLabels:
      gateway.networking.k8s.io/gateway-class-name: agentgateway
  endpoints:
  - port: metrics
    path: /metrics
    interval: 15s
EOF
```

---

## Step 9 — Wait for readiness

```bash
kubectl wait --for=condition=Programmed gateway/team-a -n team-a --timeout=120s
kubectl wait --for=condition=Programmed gateway/team-b -n team-b --timeout=120s
kubectl rollout status deploy -n team-a -l gateway.networking.k8s.io/gateway-name=team-a --timeout=120s
kubectl rollout status deploy -n team-b -l gateway.networking.k8s.io/gateway-name=team-b --timeout=120s
```

## Step 10 — Drive traffic

Port-forward each gateway and send a few chat completions with mixed prompt sizes so the histograms fill. No API key on the client — the gateway injects it.

```bash
kubectl -n team-a port-forward svc/team-a 8080:8080 >/tmp/pf-a.log 2>&1 &
kubectl -n team-b port-forward svc/team-b 8081:8080 >/tmp/pf-b.log 2>&1 &
sleep 2

for i in $(seq 1 20); do
  curl -s localhost:8080/v1/chat/completions -H 'content-type: application/json' \
    -d '{"model":"claude-sonnet-4-5","messages":[{"role":"user","content":"In two sentences, what is a service mesh?"}]}' >/dev/null
  curl -s localhost:8081/v1/chat/completions -H 'content-type: application/json' \
    -d '{"model":"claude-opus-4-1","messages":[{"role":"user","content":"Explain Kubernetes operators in one paragraph."}]}' >/dev/null
done
echo "done"
```

## Step 11 — Query the metrics (per gateway)

Run these in the Prometheus UI (`kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090`) or Grafana Explore.

Tokens per second by gateway and token type:

```promql
sum by (gateway, gen_ai_token_type) (rate(agentgateway_gen_ai_client_token_usage_sum[5m]))
```

Tokens by model:

```promql
sum by (gen_ai_request_model, gen_ai_token_type) (rate(agentgateway_gen_ai_client_token_usage_sum[5m]))
```

Tokens by provider:

```promql
sum by (gen_ai_system, gen_ai_token_type) (rate(agentgateway_gen_ai_client_token_usage_sum[5m]))
```

p95 time-to-first-token by gateway + model:

```promql
histogram_quantile(0.95, sum by (le, gateway, gen_ai_request_model) (rate(agentgateway_gen_ai_server_time_to_first_token_bucket[5m])))
```

p95 request duration by gateway:

```promql
histogram_quantile(0.95, sum by (le, gateway) (rate(agentgateway_gen_ai_server_request_duration_bucket[5m])))
```

p95 time per output token by gateway:

```promql
histogram_quantile(0.95, sum by (le, gateway) (rate(agentgateway_gen_ai_server_time_per_output_token_bucket[5m])))
```

You should see distinct `team-a` and `team-b` series, and `claude-sonnet-4-5` vs `claude-opus-4-1` series.

## Step 12 — Import the Grafana dashboard

Port-forward Grafana and import `grafana-dashboard.json` (Dashboards → New → Import). Default kube-prometheus-stack Grafana login is `admin` / `prom-operator`.

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
```

Panels split token volume and latency by gateway, model, and provider.

## Step 13 — See per-request cost in the access log

For LLM requests the proxy emits an access-log line with token counts and (because a catalog is configured) the total cost. With `logging.format: json` it's structured, so filter with `jq`:

```bash
kubectl logs -n team-a deploy/team-a --tail=200 \
  | grep -E 'gen_ai|cost' \
  | jq 'select(."agw.ai.usage.cost.total" != null)
        | {gateway: "team-a",
           model: ."gen_ai.request.model",
           input_tokens: ."gen_ai.usage.input_tokens",
           output_tokens: ."gen_ai.usage.output_tokens",
           cost_total: ."agw.ai.usage.cost.total"}'
```

Each matching line shows input/output tokens and `agw.ai.usage.cost.total` (USD) for that single request. The full per-dimension breakdown (`agw.ai.usage.cost.input`, `.output`, `.cache_read`, …) appears when request tracing is enabled — covered in Demo 2.

---

## Teardown

```bash
kubectl delete namespace team-a team-b
helm uninstall kube-prometheus-stack -n monitoring
kubectl delete namespace monitoring
# Uninstall the agentgateway controller/CRDs per the quickstart if no longer needed.
```

## Optional extension — light up the provider slice

`gen_ai_system` is constant (`anthropic`) here, so the "by provider" panels show a single series. Add a second provider (e.g. an OpenAI-backed `AgentgatewayBackend` + route on one gateway, with its own Secret) to make the provider dimension meaningful. Cost for that provider requires a matching catalog entry under its provider key (e.g. `openai`).

## Notes / scope

- Demo 1 ships a minimal inline catalog only so cost renders; importing/refreshing catalogs is **Demo 2**.
- Charting dollars in Grafana (recording rules: tokens × rate) is **Demo 2** — here cost is a per-request access-log artifact.
- Model IDs (`claude-sonnet-4-5`, `claude-opus-4-1`) must match models your key can access and the catalog keys; change all three together if you swap models.

---
title: "Virtual Keys — Per-Key Token Budgets & Cost Attribution (agentgateway OSS)"
date: 2026-06-22
description: "Demo 2 add-on: issue virtual API keys with per-user identity, enforce per-key token budgets with a global rate-limit server, and attribute cost per key — without exposing the real provider key."
tags: ["agentgateway", "kubernetes", "llm", "cost", "virtual-keys", "api-keys", "rate-limiting", "budgets"]
author: "adminturneddevops"
---

# Virtual Keys (per-key token budgets)

Virtual keys let you hand each user/app its **own** API key with its **own** token budget and cost attribution, while the real provider credential stays server-side. Three native pieces combine:

1. **API-key authentication** — clients present a gateway-issued key; the gateway maps it to identity metadata.
2. **Global token rate limiting** — a shared rate-limit server enforces a per-key token budget across all replicas.
3. **Cost attribution** — the per-key identity flows into logs/metrics for spend tracking.

This add-on to Demo 2 builds on Demo 1's `team-a` LLM gateway + Anthropic backend.

## Prerequisites

- **Demo 1 deployed**: `team-a` gateway, `anthropic` `AgentgatewayBackend`, `anthropic-key` Secret, `llm` HTTPRoute (path `/v1/chat/completions`).
- agentgateway controller + CRDs v1.3.0.
- CLI tools: `kubectl`, `jq`, `curl`, `openssl`.

## How it works

Client → gateway (validates the **virtual key**, resolves `apiKey.metadata.user_id`) → checks the user's token budget against the **global rate-limit server** (Envoy ratelimit + Redis) → forwards to Anthropic using the **real** key from Demo 1's backend auth. Token cost is debited per user; over budget → `429`.

---

## Step 1 — Deploy the global rate-limit server (Envoy ratelimit + Redis)

Global (cluster-wide) budgets need a shared counter store. This is the standard Envoy `ratelimit` service backed by Redis — prebuilt images, no custom code.

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
      - key: user_id
        rate_limit:
          unit: minute          # use 'day' for real daily budgets; 'minute' makes the demo fast
          requests_per_unit: 2000   # token budget per user per unit
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: team-a
spec:
  replicas: 1
  selector: { matchLabels: { app: redis } }
  template:
    metadata: { labels: { app: redis } }
    spec:
      containers:
      - name: redis
        image: redis:7.4.3
        ports: [{ containerPort: 6379 }]
---
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: team-a
spec:
  selector: { app: redis }
  ports: [{ port: 6379, targetPort: 6379 }]
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ratelimit
  namespace: team-a
spec:
  replicas: 1
  selector: { matchLabels: { app: ratelimit } }
  template:
    metadata: { labels: { app: ratelimit } }
    spec:
      containers:
      - name: ratelimit
        image: envoyproxy/ratelimit:3e085e5b
        command: ["/bin/ratelimit"]
        env:
        - { name: USE_STATSD, value: "false" }
        - { name: LOG_LEVEL, value: "info" }
        - { name: REDIS_SOCKET_TYPE, value: "tcp" }
        - { name: REDIS_URL, value: "redis.team-a.svc.cluster.local:6379" }
        - { name: RUNTIME_ROOT, value: "/data" }
        - { name: RUNTIME_SUBDIRECTORY, value: "ratelimit" }
        - { name: RUNTIME_WATCH_ROOT, value: "false" }
        ports: [{ containerPort: 8081 }]
        volumeMounts:
        - { name: config, mountPath: /data/ratelimit/config }
      volumes:
      - name: config
        configMap:
          name: ratelimit-config
          items: [{ key: config.yaml, path: config.yaml }]
---
apiVersion: v1
kind: Service
metadata:
  name: ratelimit
  namespace: team-a
spec:
  selector: { app: ratelimit }
  ports: [{ name: grpc, port: 8081, targetPort: 8081 }]
EOF
kubectl rollout status deploy/ratelimit -n team-a --timeout=120s
```

## Step 2 — Issue virtual keys (Secret)

Each entry's value is JSON with the key and arbitrary `metadata` (exposed in CEL as `apiKey.metadata.*`). Keys are generated locally, never hardcoded in the doc.

```bash
ALICE="vk-$(openssl rand -hex 16)"
BOB="vk-$(openssl rand -hex 16)"
kubectl create secret generic llm-virtual-keys -n team-a \
  --from-literal=alice="{\"key\":\"$ALICE\",\"metadata\":{\"user_id\":\"alice\",\"tier\":\"pro\"}}" \
  --from-literal=bob="{\"key\":\"$BOB\",\"metadata\":{\"user_id\":\"bob\",\"tier\":\"free\"}}"
echo "alice key: $ALICE"; echo "bob key: $BOB"
```

## Step 3 — Require API-key auth on the gateway

```bash
kubectl apply -f - <<'EOF'
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: virtual-key-auth
  namespace: team-a
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: team-a
  apiKeyAuthentication:
    mode: Strict
    secretRef:
      name: llm-virtual-keys
EOF
```

## Step 4 — Enforce a per-key token budget (global rate limit)

The descriptor keys on `apiKey.metadata.user_id`; `unit: Tokens` makes the cost the request's token count (debited after completion). `failClosed` denies if the RLS is unreachable (budget integrity over availability — flip to `failOpen` if you prefer).

```bash
kubectl apply -f - <<'EOF'
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: virtual-key-budget
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
          - name: user_id
            expression: apiKey.metadata.user_id
          unit: Tokens
EOF
```

## Step 5 — Test per-key budget + attribution

Port-forward team-a (from Demo 1) and call with each virtual key. No request carries the real Anthropic key.

```bash
kubectl -n team-a port-forward svc/team-a 8080:8080 >/tmp/pf-a.log 2>&1 &
sleep 2

ask () { # $1 = virtual key
  curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/v1/chat/completions \
    -H "Authorization: Bearer $1" -H 'content-type: application/json' \
    -d '{"model":"x","messages":[{"role":"user","content":"Summarize the OSI model."}]}'
}

# alice spends until her per-minute token budget is exhausted -> 429
for i in $(seq 1 15); do echo "alice $i -> $(ask "$ALICE")"; done
# bob has his own independent budget
echo "bob -> $(ask "$BOB")"
# no key -> 401/403 (Strict mode)
echo "anon -> $(curl -s -o /dev/null -w '%{http_code}' localhost:8080/v1/chat/completions -H 'content-type: application/json' -d '{"model":"x","messages":[{"role":"user","content":"hi"}]}')"
```

Expect alice to flip to `429` once her ~2000 token/minute budget is spent, while bob (separate `user_id`) still gets `200` — independent per-key budgets. Per-key cost attribution shows in the access log:

```bash
kubectl logs -n team-a deploy/team-a --tail=50 \
  | jq -r 'select(."agw.ai.usage.cost.total"!=null)
           | "user=\(.["apiKey.metadata.user_id"] // "?")  tokens=\(."gen_ai.usage.input_tokens")  cost=$\(."agw.ai.usage.cost.total")"'
```

> If `apiKey.metadata.user_id` isn't present as a log field by default, add it via Demo 3's CEL log-field pattern (`logging.fields.add: { user_id: "apiKey.metadata.user_id" }`). The budget enforcement itself does not depend on the log field.

## Teardown

```bash
kubectl delete agentgatewaypolicy virtual-key-budget virtual-key-auth -n team-a
kubectl delete secret llm-virtual-keys -n team-a
kubectl delete deploy ratelimit redis -n team-a
kubectl delete svc ratelimit redis -n team-a
kubectl delete configmap ratelimit-config -n team-a
```

## Notes / scope

- `requests_per_unit` in the RLS config is the **token** budget per `unit` here (because the gateway descriptor uses `unit: Tokens`, so each request's "hits" = its token count). Use `unit: day` for real daily budgets.
- Token cost is known only after a request completes, so the request that crosses the budget completes and the **next** is rejected.
- Virtual keys are self-issued gateway credentials — generate per environment, store securely, never commit. The real provider key stays in Demo 1's `anthropic-key` Secret.
- This same global-RLS mechanism, keyed on a route/team descriptor instead of `user_id`, gives org-level daily budgets — see Demo 3's budget-limits completion.

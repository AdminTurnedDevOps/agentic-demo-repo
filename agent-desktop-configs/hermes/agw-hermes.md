# Hermes Agent in Front, agentgateway in Back

Run Hermes Agent as the user-facing chat surface and put **agentgateway** between Hermes and every downstream LLM / MCP server / peer agent. Hermes owns the user session and agent loop; agentgateway owns model + tool egress (routing, authz, rate limits, observability).

## Architecture

```
                    inbound                              outbound
   ┌─────────────────────────────────┐      ┌──────────────────────────────┐
   │                                 │      │                              │
   │  Telegram / Discord / Slack /   │      │   LLM providers              │
   │  WhatsApp / Signal / Email /    │      │   (OpenAI, Anthropic,        │
   │  iMessage / Matrix / ntfy / …   │      │    Bedrock, Gemini, Azure,   │
   │                                 │      │    Ollama, …)                │
   └──────────────┬──────────────────┘      │                              │
                  │                          │   MCP servers                │
                  ▼                          │   (filesystem, github,       │
        ┌──────────────────┐                 │    postgres, internal tools) │
        │  Hermes gateway  │                 │                              │
        │  (per-platform   │                 │   Peer agents (A2A)          │
        │   adapters,      │                 │                              │
        │   session router)│                 └──────────────▲───────────────┘
        └────────┬─────────┘                                │
                 │                                          │
                 ▼                                          │
        ┌──────────────────┐                                │
        │  Hermes Agent    │  ── LLM calls ─┐               │
        │  (loop, memory,  │                │               │
        │   skills, hooks, │  ── MCP calls ─┼──► agentgateway
        │   state.db)      │                │               │
        │                  │  ── A2A calls ─┘               │
        └──────────────────┘                                │
                                                            │
                                                       OTel / metrics / logs
```

## Why route Hermes through agentgateway

- **One provider key set, many clients.** Future agents/scripts point at agentgateway too — no duplication.
- **Provider failover** (OpenAI down → fall back to Anthropic) without changes inside Hermes.
- **MCP fan-out + virtualization.** Hermes sees a single MCP endpoint; agentgateway aggregates the actual servers and decides which tools Hermes is allowed to see.
- **Cedar authz / JWT / rate limits / OTel traces** for every tool call, applied uniformly.
- **Audit.** Every LLM/MCP call is logged at the gateway, even when triggered from Telegram.

## Step 1: Install AGW


```bash
kubectl apply --server-side -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.0/standard-install.yaml

helm upgrade -i --create-namespace \
  --namespace agentgateway-system \
  agentgateway-crds oci://cr.agentgateway.dev/charts/agentgateway-crds

helm upgrade -i -n agentgateway-system agentgateway oci://cr.agentgateway.dev/charts/agentgateway
```

Provider keys are created inline as Kubernetes Secrets in Step 2 — never put them in committed Helm values.

## Step 2: Configure agentgateway

### LLM Connectivity

```bash
export ANTHROPIC_API_KEY=
```

```bash
kubectl apply -f- <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: anthropic-secret
  namespace: agentgateway-system
  labels:
    app: agentgateway-route
type: Opaque
stringData:
  Authorization: $ANTHROPIC_API_KEY
EOF
```

```bash
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: agentgateway-hermes-route
  namespace: agentgateway-system
  labels:
    app: agentgateway
spec:
  gatewayClassName: agentgateway
  listeners:
    - name: http
      port: 8080
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
EOF
```

```bash
kubectl apply -f - <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: anthropic
  namespace: agentgateway-system
spec:
  ai:
    provider:
        anthropic:
          model: "claude-opus-4-7"
  policies:
    auth:
      secretRef:
        name: anthropic-secret
EOF
```

```bash
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: claude
  namespace: agentgateway-system
spec:
  parentRefs:
    - name: agentgateway-hermes-route
      namespace: agentgateway-system
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /anthropic
    - path:
        type: PathPrefix
        value: /v1/chat/completions
    backendRefs:
    - name: anthropic
      namespace: agentgateway-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```

```bash
export INGRESS_GW_ADDRESS=$(kubectl get svc -n agentgateway-system agentgateway-hermes-route -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESS
```

```bash
curl "$INGRESS_GW_ADDRESS:8080/anthropic" -H content-type:application/json -d '{
  "model": "claude-opus-4-7",
  "max_tokens": 1024,
  "messages": [
    {
      "role": "system",
      "content": "You are a skilled cloud-native network engineer."
    },
    {
      "role": "user",
      "content": "Write me a paragraph containing the best way to think about Istio Ambient Mesh"
    }
  ]
}' | jq
```

## Step 3: Point Hermes LLM calls at agentgateway

Hermes' provider list lives in `~/.hermes/config.yaml`. Append an OpenAI-compatible provider whose `base_url` is agentgateway:

```bash
cat >> ~/.hermes/config.yaml <<'EOF'

providers:
  agentgateway:
    api_mode: chat_completions
    base_url: http://34.19.203.131:8080/anthropic
    api_key: dummy               # any non-empty string; route has no client-auth policy
    models:
      - claude-opus-4-7
EOF
```

> If `providers:` already exists in your config, drop the top-level `providers:` line from the heredoc and indent the `agentgateway:` block under the existing key — YAML disallows duplicate top-level keys.

Set the active model:

```bash
hermes model                     # interactive picker; choose agentgateway/<model>
```

Verify Hermes is hitting the gateway, not the provider directly:

1. Open `hermes` on the terminal and type a prompt in

2. Check the logs
```
kubectl logs agentgateway-hermes-route-77b8bf5c9f-th8s4 -n agentgateway-system
```

> Keep your *direct* provider entries in Hermes config if you want, but unset their default. The only model Hermes should pick by default is the `agentgateway/*` one.

---
title: "MCP Cost & Token Savings via Tool Virtualization (agentgateway OSS)"
date: 2026-06-22
description: "Demo 4 of the agentgateway cost series: aggregate an MCP server, virtualize (filter) its tool list with native MCP authorization, and quantify the input-token and dollar savings — fewer tool schemas means fewer tokens sent to the LLM."
tags: ["agentgateway", "kubernetes", "mcp", "tools", "cost", "tokens", "llm"]
author: "adminturneddevops"
---

# Demo 4 — MCP Cost / Token Savings (tool virtualization)

Every tool an MCP server exposes ships its JSON schema into the LLM prompt as **input tokens**. An MCP gateway that aggregates servers and **virtualizes** the tool list — showing each client only the tools it needs — shrinks that payload, cutting input tokens and cost on every LLM call that carries the toolset.

This demo: deploy a multi-tool MCP server, expose it through agentgateway, filter the tool list with native **MCP authorization**, and measure the reduction two ways — the raw `tools/list` payload, and the real input-token/$ delta through the LLM gateway from Demos 1–2.

Last of four demos (visibility, management, optimization & control, **MCP savings**).

## Prerequisites

- agentgateway controller + CRDs v1.3.0; Gateway API v1.2.0; Kubernetes 1.29+.
- **Demos 1–2 deployed** (LLM gateway `team-a` with Anthropic + catalog, Prometheus) — used in the optional real-token/$ proof (Step 5). Steps 1–4 stand alone.
- Cluster egress to pull the `mcp/everything` image.
- CLI tools: `kubectl`, `jq`, `curl`.

## How the savings work

agentgateway's MCP gateway evaluates `backend.mcp.authorization` rules against **each item** of a list operation, so disallowed tools are dropped from `tools/list`. Filter the list with CEL on `mcp.tool.name` (and `jwt.*` for per-client views) → smaller toolset → fewer input tokens when an agent passes those tools to the LLM.

---

## Step 1 — Deploy a multi-tool MCP server

The reference "everything" server exposes ~10 tools. Its image defaults to stdio; we run it in **streamable HTTP** mode (POST `/mcp`, port 3001) by overriding the command.

> Pin by digest in production; only the `latest` tag is published for this reference image.

```bash
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: mcp
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: everything
  namespace: mcp
spec:
  replicas: 1
  selector:
    matchLabels: { app: everything }
  template:
    metadata:
      labels: { app: everything }
    spec:
      containers:
      - name: everything
        image: mcp/everything:latest
        command: ["node", "dist/index.js", "streamableHttp"]
        env:
        - name: PORT
          value: "3001"
        ports:
        - containerPort: 3001
---
apiVersion: v1
kind: Service
metadata:
  name: everything
  namespace: mcp
spec:
  selector: { app: everything }
  ports:
  - port: 3001
    targetPort: 3001
EOF
kubectl rollout status deploy/everything -n mcp --timeout=120s
```

## Step 2 — Expose it through agentgateway

An MCP `AgentgatewayBackend` (static StreamableHTTP target) behind its own gateway and route.

```bash
kubectl apply -f - <<'EOF'
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: mcp-gw
  namespace: mcp
spec:
  gatewayClassName: agentgateway
  listeners:
  - name: http
    protocol: HTTP
    port: 8080
    allowedRoutes:
      namespaces:
        from: Same
---
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: mcp-everything
  namespace: mcp
spec:
  mcp:
    targets:
    - name: everything
      static:
        host: everything.mcp.svc.cluster.local
        port: 3001
        protocol: StreamableHTTP
        path: /mcp
EOF

kubectl apply -f - <<'EOF'
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: mcp
  namespace: mcp
spec:
  parentRefs:
  - name: mcp-gw
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /mcp
    backendRefs:
    - group: agentgateway.dev
      kind: AgentgatewayBackend
      name: mcp-everything
EOF

kubectl wait --for=condition=Programmed gateway/mcp-gw -n mcp --timeout=120s
```

## Step 3 — List tools (full set)

Port-forward the MCP gateway and run the MCP handshake. Streamable HTTP returns SSE-framed bodies, so we strip the `data:` prefix to get JSON.

```bash
kubectl -n mcp port-forward svc/mcp-gw 8080:8080 >/tmp/pf-mcp.log 2>&1 &
sleep 2
GW=localhost:8080/mcp
HDRS=(-H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream')

# initialize -> capture the session id from the response header
curl -s -D /tmp/mcp-h.txt "${HDRS[@]}" "$GW" -d '{
  "jsonrpc":"2.0","id":1,"method":"initialize",
  "params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"demo","version":"1"}}
}' >/dev/null
SID=$(awk -F': ' 'tolower($1)=="mcp-session-id"{print $2}' /tmp/mcp-h.txt | tr -d '\r')
echo "session: $SID"

# notify initialized
curl -s "${HDRS[@]}" -H "Mcp-Session-Id: $SID" "$GW" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' >/dev/null

# tools/list -> strip SSE framing -> save tools array
curl -s "${HDRS[@]}" -H "Mcp-Session-Id: $SID" "$GW" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | sed -n 's/^data: //p' | jq '.result.tools' > /tmp/tools-full.json

jq 'length' /tmp/tools-full.json   # N tools
jq -r '.[].name' /tmp/tools-full.json
```

## Step 4 — Virtualize the tool list

Apply MCP authorization that allows only a curated subset. Pick names from the `tools/list` output above (the example below assumes `echo`, `add`, `printEnv` — confirm against your output).

```bash
kubectl apply -f - <<'EOF'
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: mcp-virtualize
  namespace: mcp
spec:
  targetRefs:
  - group: agentgateway.dev
    kind: AgentgatewayBackend
    name: mcp-everything
  backend:
    mcp:
      authorization:
        action: Allow
        rules:
        - matchExpressions:
          - 'mcp.tool.name == "echo"'
          - 'mcp.tool.name == "add"'
          - 'mcp.tool.name == "printEnv"'
EOF
```

Re-run the Step 3 handshake (new session) and save to `/tmp/tools-virt.json`:

```bash
# ...repeat initialize + notifications/initialized + tools/list with a fresh session...
# tools/list -> /tmp/tools-virt.json
jq 'length' /tmp/tools-virt.json          # M tools (M < N)
jq -r '.[].name' /tmp/tools-virt.json
```

## Step 5 — Quantify the reduction

### Raw payload (no LLM needed)

```bash
echo "full:        $(jq 'length' /tmp/tools-full.json) tools, $(wc -c </tmp/tools-full.json) bytes"
echo "virtualized: $(jq 'length' /tmp/tools-virt.json) tools, $(wc -c </tmp/tools-virt.json) bytes"
# rough token estimate (~4 chars/token)
echo "full ~$(( $(wc -c </tmp/tools-full.json) / 4 )) tokens | virt ~$(( $(wc -c </tmp/tools-virt.json) / 4 )) tokens"
```

### Real input-token / dollar delta (through the LLM gateway — needs Demos 1–2)

Convert MCP tools to OpenAI `tools`, send a chat request carrying each toolset through `team-a`, and read the provider-counted tokens + cost from the access log.

```bash
to_openai () { jq -c '[.[] | {type:"function", function:{name:.name, description:.description, parameters:.inputSchema}}]' "$1"; }

kubectl -n team-a port-forward svc/team-a 8081:8080 >/tmp/pf-llm.log 2>&1 &
sleep 2
ask () {
  local tools="$1"
  curl -s localhost:8081/v1/chat/completions -H 'content-type: application/json' -d "$(jq -nc \
    --argjson t "$tools" '{model:"x", messages:[{role:"user",content:"Pick a tool to greet the user."}], tools:$t}')" >/dev/null
}
ask "$(to_openai /tmp/tools-full.json)"   # full toolset
sleep 2
ask "$(to_openai /tmp/tools-virt.json)"   # virtualized toolset

kubectl logs -n team-a deploy/team-a --tail=20 \
  | jq -r 'select(."agw.ai.usage.cost.total"!=null)
           | "input_tokens=\(."gen_ai.usage.input_tokens")  cost=$\(."agw.ai.usage.cost.total")"'
```

The virtualized call shows lower `input_tokens` and `agw.ai.usage.cost.total` — the difference is the per-call saving from not shipping unused tool schemas. In Prometheus: `sum(rate(agentgateway_gen_ai_client_token_usage_sum{gen_ai_token_type="input"}[5m]))`.

## Step 6 (optional) — Per-client virtualization

Add `jwtAuth` to the MCP route and use `Require` rules keyed on JWT claims so different identities see different tool subsets (e.g. `'jwt.team == "ops" && mcp.tool.name == "printEnv"'`). Same MCP endpoint, per-client toolset → per-client token cost.

---

## Teardown

```bash
kubectl delete namespace mcp
# team-a/Demo 1–2 resources are removed by their own teardown.
```

## Notes / scope

- Tool names in the Allow rule must match the live `tools/list` output — list first, then filter.
- The token estimate in Step 5 (chars ÷ 4) is an approximation; the LLM-gateway numbers are the real provider counts.
- Streamable-HTTP responses are SSE-framed; the `sed -n 's/^data: //p'` step extracts the JSON. If your build returns plain JSON, drop that filter.
- MCP→OpenAI tool translation and the Anthropic backend accepting an OpenAI `tools` array are provider/path behaviors — confirm against your deployment.

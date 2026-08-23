# Implementing Progressive Disclosure - Multi-Tool Example

Progressive Disclosure loads the full tool set from an MCP Server, but the client (whatever client you're using to access the MCP Server) only sees a lightweight index upfront and retrieves schema (the contract for a tool) on-demand with the `get_tool()` function.

The goal here is managing the size of a context window. There's no need to put tools into the context without you actually having to use them. By doing this, you're saving thousands of tokens.

Please note: Progressive Disclosure is a pattern, it's not something that is built into the MCP Spec.

## Install Agentgateway

```
kubectl apply --server-side --force-conflicts -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.0/standard-install.yaml
```

```
helm upgrade -i enterprise-agentgateway-crds oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway-crds \
  --create-namespace --namespace agentgateway-system \
  --version v2026.5.0-beta.1
```

```
export AGENTGATEWAY_LICENSE_KEY=
```

```
helm upgrade -i enterprise-agentgateway oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway \
  --namespace agentgateway-system \
  --set-string licensing.licenseKey=${AGENTGATEWAY_LICENSE_KEY} \
  --version v2026.5.0-beta.1
```

## Implementating Agentgateway

```
┌──────────────────────────────────────┐
│ Gateway (mcp-gateway, port 3000)     │                                                                                                                            
└──────────────────────────────────────┘
                    │                                                                                                                                                 
┌─────────────────┴─────────────────┐                                                                                                                             
│ HTTPRoute (mcp-route)             │                                                                                                                               
│   /v1/messages ──► anthropic-llm  │                                                                                                
│   /mcp         ──► github-mcp-... │                                                                                                                               
└───────────────────────────────────┘                                                              
            │                 │                                                                                                                                       
    ┌─────▼─────┐     ┌─────▼──────┐                                                                                                                              
    │ AI backend│     │ EntMCP     │                                             
    │ (Anthropic)│    │ (GitHub MCP)│                                                                                                                               
    └───────────┘     └────────────┘                                                                                                                                
```


1. Create a gateway for the MCP server you deployed
```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: mcp-gateway
  namespace: agentgateway-system
  labels:
    app: github-mcp-server
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
    - name: mcp
      port: 3000
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
EOF
```

2. Create a Kubernetes `Secret` holding your GitHub PAT. The value must be the full `Authorization` header (prefixed with `Bearer `), stored under the key `Authorization` — agentgateway uses this value verbatim as the header on upstream requests.

```
export GITHUB_PAT=

kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: github-pat
  namespace: agentgateway-system
type: Opaque
stringData:
  Authorization: "Bearer ${GITHUB_PAT}"
EOF
```

3. For progressive disclosure, use an `EnterpriseAgentgatewayBackend` with `spec.entMcp.toolMode: Search`. In Search mode, the gateway replaces the upstream tool list with two meta-tools (`get_tool` and `invoke_tool`) so clients see only a lightweight index and fetch each tool's schema on demand. This matters for the GitHub MCP server specifically because it ships dozens of tools (repos, issues, PRs, actions, code scanning, etc.), so the full `tools/list` response is large.

```
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayBackend
metadata:
  name: github-mcp-server
  namespace: agentgateway-system
spec:
  entMcp:
    toolMode: Search
    targets:
      - name: github-copilot
        static:
          host: api.githubcopilot.com
          port: 443
          path: /mcp/
          protocol: StreamableHTTP
          policies:
            tls: {}
            auth:
              secretRef:
                name: github-pat
EOF
```

To see the difference, apply the same backend with `toolMode: Standard` (the default when `toolMode` is omitted). In Standard mode the gateway passes the upstream tool list through as-is `tools/list` will return every tool the GitHub MCP server exposes, each with its full input schema.

```
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayBackend
metadata:
  name: github-mcp-server1
  namespace: agentgateway-system
spec:
  entMcp:
    toolMode: Standard
    targets:
      - name: github-copilot
        static:
          host: api.githubcopilot.com
          port: 443
          path: /mcp/
          protocol: StreamableHTTP
          policies:
            tls: {}
            auth:
              secretRef:
                name: github-pat
EOF
```

Reconnect MCP Inspector and call `tools/list` again — you'll now see the full GitHub tool set (`list_issues`, `create_pull_request`, `get_file_contents`, etc.) with complete schemas. Compare the byte size of the two `tools/list` responses to see the token savings progressive disclosure gives you on a large MCP server.


4. Add a Kubernetes Secret holding your Anthropic API key.

```
export ANTHROPIC_API_KEY=

kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: anthropic-api-key
  namespace: agentgateway-system
type: Opaque
stringData:
  Authorization: "Bearer ${ANTHROPIC_API_KEY}"
EOF
```

5. Create an `EnterpriseAgentgatewayBackend` of type `ai` for Anthropic.

```
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayBackend
metadata:
  labels:
    app: agentgateway-route
  name: anthropic
  namespace: agentgateway-system
spec:
  ai:
    provider:
      anthropic:
        model: "claude-sonnet-4-6"
  policies:
    ai:
      # store model internal state instead of re-tokenzing for a prompt
      promptCaching: {}
    auth:
      secretRef:
        name: anthropic-api-key
EOF
```

6. Update the `HTTPRoute` to route by path.

```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: mcp-route
  namespace: agentgateway-system
  labels:
    app: github-mcp-server
spec:
  parentRefs:
    - name: mcp-gateway
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /anthropic
      filters:
        - type: URLRewrite
          urlRewrite:
            path:
              type: ReplaceFullPath
              replaceFullPath: /v1/chat/completions
      backendRefs:
        - name: anthropic
          namespace: agentgateway-system
          group: enterpriseagentgateway.solo.io
          kind: EnterpriseAgentgatewayBackend
    - matches:
        - path:
            type: PathPrefix
            value: /mcp
      backendRefs:
        - name: github-mcp-server
          namespace: agentgateway-system
          group: enterpriseagentgateway.solo.io
          kind: EnterpriseAgentgatewayBackend
EOF
```

## Test Connectivity

Capture the IP of the gateway
```
export GATEWAY_IP=$(kubectl get svc mcp-gateway -n agentgateway-system -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo $GATEWAY_IP
```

**To test LLM traffic**

Anthropic's Messages API requires `model`, `max_tokens`, and a `messages` array. The system prompt belongs at the top level (not inside `messages`). Do **not** set the `x-api-key` or `Authorization` header here — the gateway injects it from the `anthropic-api-key` Secret.

```
curl "http://$GATEWAY_IP:3000/anthropic" \
  -H "content-type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "system": "You are a skilled cloud-native network engineer.",
    "messages": [
      {
        "role": "user",
        "content": "Write me a paragraph containing the best way to think about Istio Ambient Mesh"
      }
    ]
  }' | jq
```


**To test MCP**, open MCP Inspector
```
npx modelcontextprotocol/inspector#0.18.0
```

Specify, within the **URL** section, the following:
```
http://YOUR_ALB_IP:3000/mcp
```

With progressive disclosure, On `tools/list` you should see only `get_tool` and `invoke_tool` instead of the full GitHub MCP tool set. Call `get_tool` with e.g. `{"name": "list_issues"}` to fetch a specific tool's schema, then `invoke_tool` to execute it.

## Token Usage Testing

Use the provider-reported `usage.prompt_tokens` field as the primary measurement. It is per-request, so it avoids the ambiguity of cumulative gateway metrics.

### One-time setup - capture the gateway IP

```
export GATEWAY_IP=$(kubectl get svc mcp-gateway -n agentgateway-system -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "$GATEWAY_IP"
```

The examples below use:
- `http://$GATEWAY_IP:3000/mcp` for MCP traffic
- `http://$GATEWAY_IP:3000/anthropic` for LLM traffic

### Optional - port-forward the metrics endpoint

If you also want to confirm the result from the gateway, port-forward the metrics endpoint in a separate terminal:

```
POD=$(kubectl get pod -n agentgateway-system -l gateway.networking.k8s.io/gateway-name=mcp-gateway -o jsonpath='{.items[0].metadata.name}')
kubectl port-forward -n agentgateway-system pod/$POD 15020:15020
```

That makes `http://127.0.0.1:15020/metrics` available for the optional gateway-side cross-check.

### Without Progressive Disclosure

1. Switch the GitHub MCP backend to `toolMode: Standard`:

```
kubectl patch enterpriseagentgatewaybackend github-mcp-server \
  -n agentgateway-system \
  --type merge \
  -p '{"spec":{"entMcp":{"toolMode":"Standard"}}}'
```

2. Fetch the tool payload from MCP and save it in OpenAI tool format to `tools.standard.json`:

```
BASE="http://$GATEWAY_IP:3000/mcp"

curl -sD /tmp/h -o /dev/null -X POST "$BASE" \
  -H 'accept: application/json, text/event-stream' -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
SID=$(awk -F': ' 'tolower($1)=="mcp-session-id"{print $2}' /tmp/h | tr -d '\r\n')

curl -s -X POST "$BASE" -H "mcp-session-id: $SID" \
  -H 'accept: application/json, text/event-stream' -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' > /dev/null

curl -s -X POST "$BASE" -H "mcp-session-id: $SID" \
  -H 'accept: application/json, text/event-stream' -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | sed 's/^data: //' | tr -d '\n' \
  | jq '.result.tools | map({type:"function", function:{name:.name, description:.description, parameters:.inputSchema}})' \
  > tools.standard.json

jq 'length' tools.standard.json
wc -c tools.standard.json
```

3. Send the LLM request with that tool payload embedded and capture the provider-reported token usage:

```
jq -n --slurpfile t tools.standard.json '{model:"claude-sonnet-4-6", max_tokens:64, messages:[{"role":"user","content":"List the 3 most recent open issues on the agentgateway/agentgateway repo."}], tools:$t[0]}' \
  | curl -sS -X POST "http://$GATEWAY_IP:3000/anthropic" \
    -H 'content-type: application/json' \
    -H 'anthropic-version: 2023-06-01' \
    -d @- \
  | tee standard-response.json \
  | jq '.usage'
 
jq '.usage.prompt_tokens' standard-response.json
```

Optional gateway-side cross-check:

```
before_standard=$(curl -s localhost:15020/metrics \
  | awk '/agentgateway_gen_ai_client_token_usage_sum\{[^}]*gen_ai_token_type="input"/ {s+=$NF} END {print s+0}')

jq -n --slurpfile t tools.standard.json '{model:"claude-sonnet-4-6", max_tokens:64, messages:[{"role":"user","content":"List the 3 most recent open issues on the agentgateway/agentgateway repo."}], tools:$t[0]}' \
  | curl -sS -X POST "http://$GATEWAY_IP:3000/anthropic" \
    -H 'content-type: application/json' \
    -H 'anthropic-version: 2023-06-01' \
    -d @- > /dev/null

after_standard=$(curl -s localhost:15020/metrics \
  | awk '/agentgateway_gen_ai_client_token_usage_sum\{[^}]*gen_ai_token_type="input"/ {s+=$NF} END {print s+0}')

awk -v a="$after_standard" -v b="$before_standard" 'BEGIN {print a-b}'
```

The first block gives you the main result. The optional second block gives you the gateway `input` token delta for a separate run of the same request.

### With Progressive Disclosure

Repeat the same flow with `toolMode: Search`. Re-fetch the tools payload after switching modes because the MCP tool list is different.

1. Switch the GitHub MCP backend to `toolMode: Search`:

```
kubectl patch enterpriseagentgatewaybackend github-mcp-server \
  -n agentgateway-system \
  --type merge \
  -p '{"spec":{"entMcp":{"toolMode":"Search"}}}'
```

2. Re-fetch the tool payload and save it to `tools.search.json`:

```
BASE="http://$GATEWAY_IP:3000/mcp"

curl -sD /tmp/h -o /dev/null -X POST "$BASE" \
  -H 'accept: application/json, text/event-stream' -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
SID=$(awk -F': ' 'tolower($1)=="mcp-session-id"{print $2}' /tmp/h | tr -d '\r\n')

curl -s -X POST "$BASE" -H "mcp-session-id: $SID" \
  -H 'accept: application/json, text/event-stream' -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' > /dev/null

curl -s -X POST "$BASE" -H "mcp-session-id: $SID" \
  -H 'accept: application/json, text/event-stream' -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | sed 's/^data: //' | tr -d '\n' \
  | jq '.result.tools | map({type:"function", function:{name:.name, description:.description, parameters:.inputSchema}})' \
  > tools.search.json

jq 'length' tools.search.json
wc -c tools.search.json
```

3. Send the same LLM request with `tools.search.json`:

```
jq -n --slurpfile t tools.search.json '{model:"claude-sonnet-4-6", max_tokens:64, messages:[{"role":"user","content":"List the 3 most recent open issues on the agentgateway/agentgateway repo."}], tools:$t[0]}' \
  | curl -sS -X POST "http://$GATEWAY_IP:3000/anthropic" \
    -H 'content-type: application/json' \
    -H 'anthropic-version: 2023-06-01' \
    -d @- \
  | tee search-response.json \
  | jq '.usage'
 
jq '.usage.prompt_tokens' search-response.json
```

Optional gateway-side cross-check:

```
before_search=$(curl -s localhost:15020/metrics \
  | awk '/agentgateway_gen_ai_client_token_usage_sum\{[^}]*gen_ai_token_type="input"/ {s+=$NF} END {print s+0}')

jq -n --slurpfile t tools.search.json '{model:"claude-sonnet-4-6", max_tokens:64, messages:[{"role":"user","content":"List the 3 most recent open issues on the agentgateway/agentgateway repo."}], tools:$t[0]}' \
  | curl -sS -X POST "http://$GATEWAY_IP:3000/anthropic" \
    -H 'content-type: application/json' \
    -H 'anthropic-version: 2023-06-01' \
    -d @- > /dev/null

after_search=$(curl -s localhost:15020/metrics \
  | awk '/agentgateway_gen_ai_client_token_usage_sum\{[^}]*gen_ai_token_type="input"/ {s+=$NF} END {print s+0}')

awk -v a="$after_search" -v b="$before_search" 'BEGIN {print a-b}'
```

4. Compare the results:

```
standard_prompt_tokens=$(jq '.usage.prompt_tokens' standard-response.json)
search_prompt_tokens=$(jq '.usage.prompt_tokens' search-response.json)

echo "standard_prompt_tokens=$standard_prompt_tokens"
echo "search_prompt_tokens=$search_prompt_tokens"
awk -v standard="$standard_prompt_tokens" -v search="$search_prompt_tokens" 'BEGIN {print "prompt_token_savings=" standard-search}'
```

You should see:
- `tools.standard.json` is much larger than `tools.search.json`
- `standard-response.json` reports a much larger `usage.prompt_tokens` value than `search-response.json`
- the gateway `input` token delta also drops when using Search mode

That per-request prompt-token difference is the savings progressive disclosure gives you on every turn where the full MCP tool list would otherwise be embedded in the model request.

### Test Conclusion

The verified token results were:

- With Progressive Disclosure: `usage.prompt_tokens` = 970
- Without Progressive Disclosure: `usage.prompt_tokens` = 10877

## Context Usage Testing

Keep this simple: test the baseline overhead once, then compare turn 1 versus turn 3.

### Quick Tests

#### 1. Upfront context overhead

Compare the tool payload size first:

```bash
jq 'length' tools.standard.json
wc -c tools.standard.json

jq 'length' tools.search.json
wc -c tools.search.json
```

Then run the same request once with each tool payload and compare `usage.prompt_tokens`:

```bash
jq -n --slurpfile t tools.standard.json '{model:"claude-sonnet-4-6",max_tokens:64,messages:[{role:"user",content:"List the 3 most recent open issues on the agentgateway/agentgateway repo."}],tools:$t[0]}' \
  | curl -sS -X POST "http://$GATEWAY_IP:3000/anthropic" \
    -H 'content-type: application/json' \
    -H 'anthropic-version: 2023-06-01' \
    -d @- \
  | tee context-standard-once.json \
  | jq '.usage'

jq -n --slurpfile t tools.search.json '{model:"claude-sonnet-4-6",max_tokens:64,messages:[{role:"user",content:"List the 3 most recent open issues on the agentgateway/agentgateway repo."}],tools:$t[0]}' \
  | curl -sS -X POST "http://$GATEWAY_IP:3000/anthropic" \
    -H 'content-type: application/json' \
    -H 'anthropic-version: 2023-06-01' \
    -d @- \
  | tee context-search-once.json \
  | jq '.usage'
```

#### 2. Turn 1 vs turn 3 growth

Run only turn 1 and turn 3 for each mode:

```bash
jq -n --slurpfile t tools.standard.json '{model:"claude-sonnet-4-6",max_tokens:64,messages:[{role:"user",content:"List the 3 most recent open issues on the agentgateway/agentgateway repo."}],tools:$t[0]}' \
  | curl -sS -X POST "http://$GATEWAY_IP:3000/anthropic" \
    -H 'content-type: application/json' \
    -H 'anthropic-version: 2023-06-01' \
    -d @- \
  | tee context-standard-turn1.json \
  | jq '.usage'

jq -n --slurpfile t tools.standard.json '{model:"claude-sonnet-4-6",max_tokens:64,messages:[{role:"user",content:"List the 3 most recent open issues on the agentgateway/agentgateway repo."},{role:"assistant",content:"The three most recent open issues are issue A, issue B, and issue C."},{role:"user",content:"Which one looks most urgent?"},{role:"assistant",content:"Issue B looks most urgent because it appears to affect core gateway behavior."},{role:"user",content:"Give me a two-sentence recommendation for what to investigate first."}],tools:$t[0]}' \
  | curl -sS -X POST "http://$GATEWAY_IP:3000/anthropic" \
    -H 'content-type: application/json' \
    -H 'anthropic-version: 2023-06-01' \
    -d @- \
  | tee context-standard-turn3.json \
  | jq '.usage'

jq -n --slurpfile t tools.search.json '{model:"claude-sonnet-4-6",max_tokens:64,messages:[{role:"user",content:"List the 3 most recent open issues on the agentgateway/agentgateway repo."}],tools:$t[0]}' \
  | curl -sS -X POST "http://$GATEWAY_IP:3000/anthropic" \
    -H 'content-type: application/json' \
    -H 'anthropic-version: 2023-06-01' \
    -d @- \
  | tee context-search-turn1.json \
  | jq '.usage'

jq -n --slurpfile t tools.search.json '{model:"claude-sonnet-4-6",max_tokens:64,messages:[{role:"user",content:"List the 3 most recent open issues on the agentgateway/agentgateway repo."},{role:"assistant",content:"The three most recent open issues are issue A, issue B, and issue C."},{role:"user",content:"Which one looks most urgent?"},{role:"assistant",content:"Issue B looks most urgent because it appears to affect core gateway behavior."},{role:"user",content:"Give me a two-sentence recommendation for what to investigate first."}],tools:$t[0]}' \
  | curl -sS -X POST "http://$GATEWAY_IP:3000/anthropic" \
    -H 'content-type: application/json' \
    -H 'anthropic-version: 2023-06-01' \
    -d @- \
  | tee context-search-turn3.json \
  | jq '.usage'
```

### Key Results

| Mode | Tool Count | Tool Payload Size | Turn 1 Prompt Tokens | Turn 3 Prompt Tokens |
| --- | --- | ---: | ---: | ---: |
| Without Progressive Disclosure | 44 | 58443 bytes | 10877 | 10939 |
| With Progressive Disclosure | 2 | 1915 bytes | 970 | 1032 |

### Takeaway

Progressive disclosure does not stop conversation history from growing. What it does is remove the large upfront tool-context overhead.

In this test:
- the full MCP tool catalog added about `9910` extra prompt tokens on turn 1
- that overhead remained present on later turns
- the turn-1 to turn-3 growth was similar in both modes, which shows the main savings come from reducing the baseline tool context

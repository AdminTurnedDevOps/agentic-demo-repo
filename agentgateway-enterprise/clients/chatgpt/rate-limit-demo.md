# ChatGPT/Codex App + Agentgateway: Request-Based Rate Limiting (MCP)

This demo rate limits MCP traffic flowing from the **unified ChatGPT desktop app** through **enterprise agentgateway** to a public MCP server (DeepWiki).

> The Codex desktop app and the ChatGPT desktop app are now one unified app. This demo uses its Codex mode, which is the app's local MCP client.

```
ChatGPT app, Codex mode (~/.codex/config.toml) --> agentgateway --> mcp.deepwiki.com
                                                        |
                                          EnterpriseAgentgatewayPolicy (entRateLimit)
                                                        |
                                             rate-limiter extension server
```

Two important mechanics of this demo:
- Codex mode runs locally and configures MCP servers in `~/.codex/config.toml` (`[mcp_servers.*]`), so its MCP traffic reaches the gateway directly — no public exposure needed. Note this is separate from `openai_base_url`, which only redirects LLM/model traffic; MCP connections never flow through the OpenAI base URL.
- Every MCP JSON-RPC call (`initialize`, `tools/list`, `tools/call`) is a separate HTTP POST to `/mcp`, so a requests-per-minute limit is consumed by handshake traffic too. Keep the limit low enough to trip, high enough to connect.

## Prerequisites

- A cluster with enterprise agentgateway installed (see [setup.md](../../setup.md))
- The unified ChatGPT desktop app

## 1. Enable the rate-limiter extension server

The enterprise global rate limiter is an extension server that gets auto-provisioned when enabled via `EnterpriseAgentgatewayParameters`. The default `enterprise-agentgateway` GatewayClass has no `parametersRef`, so create a dedicated GatewayClass that points at the parameters.

```
kubectl apply -f- <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayParameters
metadata:
  name: agw-rl-params
  namespace: agentgateway-system
spec:
  sharedExtensions:
    ratelimiter:
      enabled: true
---
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: enterprise-agentgateway-rl
spec:
  controllerName: solo.io/enterprise-agentgateway
  parametersRef:
    group: enterpriseagentgateway.solo.io
    kind: EnterpriseAgentgatewayParameters
    name: agw-rl-params
    namespace: agentgateway-system
EOF
```

Verify the rate limiter (and its Redis-based extCache dependency, which is auto-provisioned) comes up:

```
kubectl get pods -n agentgateway-system | grep -E 'rate-limiter|ext-cache'
```

## 2. Create the Gateway

```
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: chatgpt-mcp-gateway
  namespace: agentgateway-system
spec:
  gatewayClassName: enterprise-agentgateway-rl
  listeners:
    - name: mcp
      port: 3000
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
EOF
```

## 3. Create the MCP backend (DeepWiki)

DeepWiki is a free, no-auth, public MCP server (tools: `read_wiki_structure`, `read_wiki_contents`, `ask_question` for any public GitHub repo). The gateway originates TLS to it (`policies.tls: {}` uses system CAs).

```
kubectl apply -f- <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: deepwiki-mcp
  namespace: agentgateway-system
spec:
  mcp:
    targets:
      - name: deepwiki
        static:
          host: mcp.deepwiki.com
          port: 443
          path: /mcp
          protocol: StreamableHTTP
          policies:
            tls: {}
EOF
```

## 4. Route `/mcp` to the backend

```
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: deepwiki-mcp-route
  namespace: agentgateway-system
spec:
  parentRefs:
    - name: chatgpt-mcp-gateway
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /mcp
      backendRefs:
        - name: deepwiki-mcp
          group: agentgateway.dev
          kind: AgentgatewayBackend
EOF
```

## 5. Sanity check the MCP path (before rate limiting)

```
export GATEWAY_IP=$(kubectl get svc chatgpt-mcp-gateway -n agentgateway-system -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $GATEWAY_IP
```

```
curl -s "http://$GATEWAY_IP:3000/mcp" \
  -H "content-type: application/json" \
  -H "accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
```

You should get back a `serverInfo` result from DeepWiki via the gateway.

## 6. Create the rate limit

The `RateLimitConfig` uses a `genericKey` action so **all** requests on the route share one counter — no custom headers required (the MCP client doesn't send any). 10 requests per minute leaves room for the MCP handshake but trips quickly during use.

```
kubectl apply -f- <<EOF
apiVersion: ratelimit.solo.io/v1alpha1
kind: RateLimitConfig
metadata:
  name: mcp-request-limit
  namespace: agentgateway-system
spec:
  raw:
    descriptors:
    - key: generic_key
      value: chatgpt-mcp
      rateLimit:
        unit: MINUTE
        requestsPerUnit: 10
    rateLimits:
    - actions:
      - genericKey:
          descriptorValue: chatgpt-mcp
EOF
```

Attach it to the route with an `EnterpriseAgentgatewayPolicy`:

```
kubectl apply -f- <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: mcp-rate-limit
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
      name: deepwiki-mcp-route
  traffic:
    entRateLimit:
      global:
        rateLimitConfigRefs:
          - name: mcp-request-limit
EOF
```

> The policy defaults its `backendRef` to the auto-provisioned rate limiter service (`rate-limiter-<gatewayclass>` in the install namespace). If policy status reports it can't resolve the backend, check the service name with `kubectl get svc -n agentgateway-system | grep rate-limiter` and pin it explicitly:
>
> ```yaml
>   traffic:
>     entRateLimit:
>       global:
>         backendRef:
>           name: rate-limiter-enterprise-agentgateway-rl
>           namespace: agentgateway-system
>           port: 8083
>         rateLimitConfigRefs:
>           - name: mcp-request-limit
> ```

## 7. Verify the limit with curl

Fire 12 requests; the first 10 return `200`, the rest `429`:

```
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" "http://$GATEWAY_IP:3000/mcp" \
    -H "content-type: application/json" \
    -H "accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'
done
```

You can also see the 429s in the gateway pod logs:

```
kubectl logs -n agentgateway-system deploy/chatgpt-mcp-gateway --tail=20 | grep 429
```

Wait a minute for the counter to reset before moving on (the MCP handshake needs a few requests).

## 8. Connect the ChatGPT/Codex app

Codex mode configures MCP servers in `~/.codex/config.toml` and connects to them **locally**, so it can reach the gateway LB directly. Add:

```toml
[mcp_servers.deepwiki]
url = "http://<GATEWAY_IP>:3000/mcp"
```

Replace `<GATEWAY_IP>` with the value from step 5.

> If your app build only supports stdio MCP servers (no `url` key), bridge with `mcp-remote`:
>
> ```toml
> [mcp_servers.deepwiki]
> command = "npx"
> args = ["-y", "mcp-remote", "http://<GATEWAY_IP>:3000/mcp"]
> ```

Restart the ChatGPT app, switch to **Codex mode**, and confirm the `deepwiki` MCP server and its tools (`read_wiki_structure`, `read_wiki_contents`, `ask_question`) are available. The `initialize` + `tools/list` handshake already consumed a couple of requests from the budget — you can see them in the gateway logs.

Then give it a task that forces repeated tool calls:

```
Using the deepwiki MCP server, get the wiki structure for agentgateway/agentgateway,
then read the contents of the first three pages one at a time.
```

> If your cluster LB isn't reachable from your laptop, port-forward instead and point the config at localhost: `kubectl port-forward -n agentgateway-system svc/chatgpt-mcp-gateway 3000:3000`, then use `url = "http://127.0.0.1:3000/mcp"`.

## 9. Watch the rate limit trip

Each MCP call the app makes is a POST through the gateway. After the 10th request in a minute, the rate limiter returns `429` and Codex surfaces the tool calls as failed (and retries them).

Gateway logs show the denials in real time:

```
kubectl logs -n agentgateway-system deploy/chatgpt-mcp-gateway -f | grep -i "429\|rate"
```

Wait a minute and retry — the tools work again once the window resets.

## Cleanup

```
kubectl delete enterpriseagentgatewaypolicy mcp-rate-limit -n agentgateway-system
kubectl delete ratelimitconfig mcp-request-limit -n agentgateway-system
kubectl delete httproute deepwiki-mcp-route -n agentgateway-system
kubectl delete agentgatewaybackend deepwiki-mcp -n agentgateway-system
kubectl delete gateway chatgpt-mcp-gateway -n agentgateway-system
kubectl delete gatewayclass enterprise-agentgateway-rl
kubectl delete enterpriseagentgatewayparameters agw-rl-params -n agentgateway-system
```

Also remove the `[mcp_servers.deepwiki]` block from `~/.codex/config.toml`.

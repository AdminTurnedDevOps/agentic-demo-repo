Agentgateway's LLM proxy overhead is negligible (~0ms processing). The observed 25ms median delta between Agent1 and Agent2 LLM calls is attributable to the AWS ALB hop (~6ms) and measurement variance, not gateway logic.

For MCP, agentgateway adds ~66ms (including MCP server execution) on top of the 67ms cross-region network cost. At 1000 concurrent VUs, MCP through agentgateway maintains 99.99% success rate.

All failures at the stress level (1000 VUs) are caused by Bedrock per-model rate limits, not agentgateway. The gateway itself does not drop, reject, or materially delay requests.

## Overhead Attribution

### LLM Path

Agent1 and Agent2 both traverse the same cross-region hop to Bedrock (us-east-1 → ca-central-1). Agent1 adds a same-region ALB hop to reach the gateway first.

```
Agent2 (baseline):    Pod ─────────────────────────────────→ Bedrock (ca-central-1)
                           20ms TCP + TLS

Agent1 (via gateway): Pod ──→ ALB ──→ agentgateway ──→ Bedrock (ca-central-1)
                          6ms    <1ms    ~0ms processing   20ms TCP + TLS
```

```
  ┌─────────────────────────────────┬─────────┬──────────────────────────────────────────────────────────────────┐
  │           Component             │ Latency │                          Responsible                            │
  ├─────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────┤
  │ Cross-region RTT to Bedrock     │ ~20ms   │ AWS networking (same for both agents, cancels out in delta)     │
  ├─────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────┤
  │ Same-region ALB hop (us-east-1) │ ~6ms    │ AWS ALB infrastructure                                         │
  ├─────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────┤
  │ Agentgateway LLM proxy logic    │ ~0ms    │ Agentgateway (confirmed by agent1_loop_latency_ms p95=0ms)      │
  ├─────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────┤
  │ Bedrock inference               │ ~1-3s   │ Bedrock (same for both agents, excluded from loop latency)      │
  ├─────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────┤
  │ Bedrock throttling (at stress)  │ 90%+    │ Bedrock rate limits (not agentgateway)                          │
  └─────────────────────────────────┴─────────┴──────────────────────────────────────────────────────────────────┘
```

### MCP Path

```
Agent1 MCP: Pod (us-east-1) ──→ ALB (us-west-1) ──→ agentgateway ──→ math-server (us-west-1)
                 67ms TCP             <1ms              processing       <1ms (same cluster)
```

```
  ┌─────────────────────────────────────┬─────────┬──────────────────────────────────────────────────────────────────┐
  │             Component               │ Latency │                          Responsible                            │
  ├─────────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────┤
  │ Cross-region RTT (us-east-1→west-1) │ ~67ms   │ AWS inter-region networking                                     │
  ├─────────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────┤
  │ MCP gateway + math-server           │ ~66ms   │ Agentgateway MCP proxying + MCP server execution                │
  ├─────────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────┤
  │ Load-induced contention             │ ~100ms  │ Connection queuing under 1000 VUs (infrastructure, not gateway)  │
  └─────────────────────────────────────┴─────────┴──────────────────────────────────────────────────────────────────┘
```

  Of the 233ms median MCP latency under load:
  - ~67ms (29%) is AWS cross-region networking
  - ~66ms (28%) is gateway proxying + MCP server execution
  - ~100ms (43%) is load-induced contention

### Summary: Who's responsible for what

```
  ┌────────────────────────────────────┬───────────────┬─────────────┬─────────────────────────────────────────────────────────────┐
  │              Factor                │ LLM overhead  │ MCP overhead│                            Evidence                        │
  ├────────────────────────────────────┼───────────────┼─────────────┼─────────────────────────────────────────────────────────────┤
  │ Agentgateway proxy processing      │ ~0ms          │ ~66ms*      │ loop_latency p95=0ms; MCP baseline TTFB minus TCP connect  │
  ├────────────────────────────────────┼───────────────┼─────────────┼─────────────────────────────────────────────────────────────┤
  │ AWS ALB                            │ ~6ms          │ (in RTT)    │ Baseline A TCP connect time                                │
  ├────────────────────────────────────┼───────────────┼─────────────┼─────────────────────────────────────────────────────────────┤
  │ AWS cross-region networking        │ 0ms (shared)  │ ~67ms       │ Baseline B/C TCP connect times                             │
  ├────────────────────────────────────┼───────────────┼─────────────┼─────────────────────────────────────────────────────────────┤
  │ Bedrock throttling (stress test)   │ 90%+ failures │ N/A         │ Per-model rate limits at 1000 VUs                          │
  ├────────────────────────────────────┼───────────────┼─────────────┼─────────────────────────────────────────────────────────────┤
  │ MCP gateway success rate           │ N/A           │ 99.99%      │ 573,747 successful tool calls out of 573,818               │
  └────────────────────────────────────┴───────────────┴─────────────┴─────────────────────────────────────────────────────────────┘
```

*The 66ms MCP overhead includes both agentgateway proxying AND math-server execution time. To isolate just the gateway, measure math-server latency directly from within us-west-1 (bypassing the gateway) and subtract.


## In-Cluster Network Baselines

To isolate agentgateway's overhead from AWS networking and Bedrock, we measured raw network latencies from inside the us-east-1 EKS cluster. This is where the agents actually run, so these numbers reflect the real network paths.

### How to reproduce the baseline

1. Create a curl pod in the cluster:
```bash
kubectl run net-baseline --image=curlimages/curl --restart=Never -n kagent --command -- sleep 3600
kubectl wait --for=condition=Ready pod/net-baseline -n kagent --timeout=30s
```

2. Run each baseline 10 times. The curl format is `time_connect,time_starttransfer,time_total` in seconds:

**Baseline A — Pod (us-east-1) → LLM Gateway ALB (us-east-1), same region:**
```bash
for i in $(seq 1 10); do
  kubectl exec net-baseline -n kagent -- curl -s -o /dev/null \
    -w "%{time_connect},%{time_starttransfer},%{time_total}" \
    "http://<LLM_GATEWAY_ALB>:8082/anthropic" \
    -X POST -H "Content-Type: application/json" \
    -d '{"model":"global.anthropic.claude-sonnet-4-6","max_tokens":5,"messages":[{"role":"user","content":"hi"}]}'
  echo ""
done
```

**Baseline B — Pod (us-east-1) → Bedrock Runtime (ca-central-1), cross-region:**
```bash
for i in $(seq 1 10); do
  kubectl exec net-baseline -n kagent -- curl -s -o /dev/null \
    -w "%{time_connect},%{time_starttransfer},%{time_total}" \
    "https://bedrock-runtime.ca-central-1.amazonaws.com/"
  echo ""
done
```

**Baseline C — Pod (us-east-1) → MCP Gateway ALB (us-west-1), cross-region:**
```bash
for i in $(seq 1 10); do
  kubectl exec net-baseline -n kagent -- curl -s -o /dev/null \
    -w "%{time_connect},%{time_starttransfer},%{time_total}" \
    "http://<MCP_GATEWAY_ALB>:8080/mcp" \
    -X POST -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","method":"initialize","id":"baseline","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"baseline","version":"1.0"}}}'
  echo ""
done
```

3. Clean up:
```bash
kubectl delete pod net-baseline -n kagent --grace-period=0
```

### Baseline Results (March 19, 2026)

```
  ┌───────────────────────────────────────────┬────────────────────┬──────────────────┬───────────────────────────────────────────┐
  │                    Hop                    │ TCP Connect (med.) │   TTFB (med.)    │              What it measures              │
  ├───────────────────────────────────────────┼────────────────────┼──────────────────┼───────────────────────────────────────────┤
  │ A: Pod → LLM ALB (us-east-1, same region) │ 6ms                │ ~1,100ms*        │ Same-region ALB network cost              │
  ├───────────────────────────────────────────┼────────────────────┼──────────────────┼───────────────────────────────────────────┤
  │ B: Pod → Bedrock (ca-central-1)           │ 20ms               │ ~57ms            │ Cross-region TCP+TLS to Bedrock           │
  ├───────────────────────────────────────────┼────────────────────┼──────────────────┼───────────────────────────────────────────┤
  │ C: Pod → MCP ALB (us-west-1)              │ 67ms               │ ~133ms           │ Cross-region to MCP gateway + server      │
  └───────────────────────────────────────────┴────────────────────┴──────────────────┴───────────────────────────────────────────┘
```

  *Baseline A TTFB includes Bedrock inference time (~1s+); only the TCP connect time is useful for isolating network cost.


## Bedrock Constraints

A big part of testing multi-region scenarios across various providers in this case is understanding what falls under the responsbility of the proxy (agentgateway) and the responsbility of the providers you're using (AWS, Bedrock, etc.). Tldr; if there's latency, that doesn't mean its due to the proxy.

The Bedrock authentication (SigV4) is working. We got 36,776 successful direct Bedrock calls and 44,333 successful gateway LLM calls in the last run. The issue is throttling, not auth.

Bedrock has per-model request rate limits. When we ramp to 1000 VUs all hammering `global.anthropic.claude-sonnet-4-6`, Bedrock returns ThrottlingException for ~98% of requests. The 2-7% that succeed are the ones that slip through the rate limit window.


The auth and the test are working, but Bedrock can't handle 1000 concurrent LLM requests to a single Bedrock model. This is expected behavior and is actually useful benchmark data: it shows where Bedrock saturates.
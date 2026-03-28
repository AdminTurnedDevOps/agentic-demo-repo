## Run Test

```
  K6_PROMETHEUS_RW_SERVER_URL=http://localhost:9090/api/v1/write \
  PAYLOAD_MIN_KB=1 PAYLOAD_MAX_KB=8 \
  AWS_ACCESS_KEY_ID=<key> \
  AWS_SECRET_ACCESS_KEY=<secret> \
  AWS_SESSION_TOKEN=<token> \
  AGENT1_LLM_URL=http://a7f86628aa9c146df83e4f80986e4156-1288186659.us-east-1.elb.amazonaws.com:8082/anthropic \
  AGENT1_MCP_URL=http://a5404a2420706455cbe360275176fe95-229395782.us-west-1.elb.amazonaws.com:8080/mcp \
  k6 run --out experimental-prometheus-rw test.js
```

Test runs with:
  - Output: Prometheus remote write (http://localhost:9090/api/v1/write) — metrics streaming to Prometheus
  - Payloads: 1-8 KB (reduced for local run)


  The test runs ~19 minutes.
  
  You can open Grafana at http://localhost:3000 now and query k6 metrics.

  `kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3001:80`
  
## Test Types

┌─────────────────────────────────────┬─────────┬─────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │               Metric                │  Type   │                                             Description                                             │
  ├─────────────────────────────────────┼─────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ k6_agent1_loop_latency_ms_p99       │ Trend   │ Agent1 loop overhead per iteration, excluding LLM and MCP time. This isolates gateway routing cost. │
  ├─────────────────────────────────────┼─────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ k6_agent2_loop_latency_ms_p99       │ Trend   │ Agent2 loop overhead per iteration, excluding LLM time. Baseline without gateway.                   │
  ├─────────────────────────────────────┼─────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ k6_agent1_llm_wall_ms_p99           │ Trend   │ Agent1 LLM call wall time (via agentgateway → Bedrock)                                              │
  ├─────────────────────────────────────┼─────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ k6_agent2_llm_wall_ms_p99           │ Trend   │ Agent2 LLM call wall time (direct Bedrock)                                                          │
  ├─────────────────────────────────────┼─────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ k6_agent1_mcp_latency_ms_p99        │ Trend   │ Agent1 MCP round-trip time per loop (via agentgateway → math-server)                                │
  ├─────────────────────────────────────┼─────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ k6_agent1_total_mcp_llm_calls_total │ Counter │ Total MCP + LLM calls made by Agent1                                                                │
  ├─────────────────────────────────────┼─────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ k6_agent2_llm_calls_total           │ Counter │ Total LLM calls made by Agent2                                                                      │
  ├─────────────────────────────────────┼─────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ k6_loop_iterations_total_total      │ Counter │ Total agentic loop iterations across both agents                                                    │
  └─────────────────────────────────────┴─────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────┘

  Built-in k6 HTTP Metrics

  ┌─────────────────────────────────┬─────────┬───────────────────────────────────────────────────────────────────────────┐
  │             Metric              │  Type   │                                Description                                │
  ├─────────────────────────────────┼─────────┼───────────────────────────────────────────────────────────────────────────┤
  │ k6_http_req_duration_p99        │ Trend   │ End-to-end HTTP request latency (includes all phases)                     │
  ├─────────────────────────────────┼─────────┼───────────────────────────────────────────────────────────────────────────┤
  │ k6_http_req_failed_rate         │ Rate    │ Percentage of failed HTTP requests (threshold: < 1%)                      │
  ├─────────────────────────────────┼─────────┼───────────────────────────────────────────────────────────────────────────┤
  │ k6_http_req_blocked_p99         │ Trend   │ Time spent blocked before the request (waiting for a free TCP connection) │
  ├─────────────────────────────────┼─────────┼───────────────────────────────────────────────────────────────────────────┤
  │ k6_http_req_connecting_p99      │ Trend   │ TCP connection establishment time                                         │
  ├─────────────────────────────────┼─────────┼───────────────────────────────────────────────────────────────────────────┤
  │ k6_http_req_waiting_p99         │ Trend   │ Time to first byte (TTFB) — server processing time                        │
  ├─────────────────────────────────┼─────────┼───────────────────────────────────────────────────────────────────────────┤
  │ k6_http_req_sending_p99         │ Trend   │ Time spent sending request body                                           │
  ├─────────────────────────────────┼─────────┼───────────────────────────────────────────────────────────────────────────┤
  │ k6_http_req_receiving_p99       │ Trend   │ Time spent receiving response body                                        │
  ├─────────────────────────────────┼─────────┼───────────────────────────────────────────────────────────────────────────┤
  │ k6_http_req_tls_handshaking_p99 │ Trend   │ TLS handshake time (Agent2 Bedrock calls only — Agent1 uses HTTP)         │
  ├─────────────────────────────────┼─────────┼───────────────────────────────────────────────────────────────────────────┤
  │ k6_http_reqs_total              │ Counter │ Total HTTP requests made                                                  │
  ├─────────────────────────────────┼─────────┼───────────────────────────────────────────────────────────────────────────┤
  │ k6_data_sent_total              │ Counter │ Total bytes sent                                                          │
  ├─────────────────────────────────┼─────────┼───────────────────────────────────────────────────────────────────────────┤
  │ k6_data_received_total          │ Counter │ Total bytes received                                                      │
  └─────────────────────────────────┴─────────┴───────────────────────────────────────────────────────────────────────────┘

  Infrastructure Metrics

  ┌───────────────────────────┬─────────┬───────────────────────────────────────────────────────┐
  │          Metric           │  Type   │                      Description                      │
  ├───────────────────────────┼─────────┼───────────────────────────────────────────────────────┤
  │ k6_vus                    │ Gauge   │ Current number of active virtual users                │
  ├───────────────────────────┼─────────┼───────────────────────────────────────────────────────┤
  │ k6_vus_max                │ Gauge   │ Maximum configured VUs                                │
  ├───────────────────────────┼─────────┼───────────────────────────────────────────────────────┤
  │ k6_iterations_total       │ Counter │ Total completed VU iterations (sessions)              │
  ├───────────────────────────┼─────────┼───────────────────────────────────────────────────────┤
  │ k6_iteration_duration_p99 │ Trend   │ Full session duration (all loops in one VU iteration) │
  ├───────────────────────────┼─────────┼───────────────────────────────────────────────────────┤
  │ k6_checks_rate            │ Rate    │ Pass rate of check() assertions (mcp 200, llm 200)    │
  └───────────────────────────┴─────────┴───────────────────────────────────────────────────────┘


All HTTP metrics carry these labels so you can slice by agent and call type:
- agent → "test-math" or "bedrock-direct-test"
- call_type → "llm" or "mcp"
- level → "light", "moderate", or "stress"
- scenario → "agent1_light", "agent2_moderate", etc.


### P95 considerations
Why only `_p99` and not `_p95`? The k6 Prometheus remote write output exports Trend metrics as p99 by default. To get p95 as well, you'd add the env var `K6_PROMETHEUS_RW_TREND_STATS=p(95),p(99),avg,min,max` to the k6 run command. This would give you `_p95`, `_p99`, `_avg`, `_min`, `_max` variants of each Trend metric. Since the benchmark doc asks for both P95 and P99 tail latency, you may want to re-run with that flag set.
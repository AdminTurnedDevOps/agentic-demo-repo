# Observability: Trace fan-out to the AgentRegistry dashboard

## Problem

The AgentRegistry **Dashboard** (Agent Runs / Operations / Token Usage) and **Tracing** page were showing **No Data**, even though agents were running.

Root cause: kagent-managed agents split their telemetry across two backends.

| Signal | Env var on the agent | Destination |
|--------|----------------------|-------------|
| logs / metrics | `OTEL_EXPORTER_OTLP_ENDPOINT` | `agentregistry-enterprise-telemetry-collector` (agentregistry-system) ✅ |
| **traces** | `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | **`solo-enterprise-telemetry-collector` (kagent)** ❌ |

So traces only ever reached the **kagent** ClickHouse (`platformdb.otel_traces_json`),
never the **agentregistry** ClickHouse (`agentregistry.otel_traces_json`) that the
AgentRegistry dashboard reads. The agents' trace endpoint is set by the Helm value
`otel.tracing.exporter.otlp.endpoint` on the `kagent` (kagent-enterprise) release.

## Fix (fan-out, non-destructive)

Rather than repoint the agents (which would take traces away from the kagent UI and
require re-rolling every agent), the **kagent collector** now fans traces out to **both**
backends. We added an OTLP exporter to the kagent collector that forwards the
`traces/genai` pipeline to the agentregistry collector, which already writes to its own
ClickHouse. The existing `clickhouse/telemetry` exporter is untouched, so the kagent UI
keeps working.

ConfigMap `solo-enterprise-telemetry-collector-config` (ns `kagent`):

```yaml
exporters:
  otlp/agentregistry:                     # ADDED
    endpoint: agentregistry-enterprise-telemetry-collector.agentregistry-system.svc.cluster.local:4317
    tls:
      insecure: true
    retry_on_failure: { enabled: true, initial_interval: 5s, max_interval: 30s, max_elapsed_time: 300s }

service:
  pipelines:
    traces/genai:
      exporters:
        - clickhouse/telemetry            # existing — kagent UI
        - otlp/agentregistry              # ADDED — agentregistry dashboard
```

Only `traces/genai` is forwarded (not `traces/istio`) so the agentregistry dashboard
isn't polluted with mesh spans.

### Files here
- `solo-enterprise-telemetry-collector-config.patched.yaml` — the applied ConfigMap.
- `backups/solo-enterprise-telemetry-collector-config.backup.yaml` — original, for rollback.

## Durability caveat

This ConfigMap is **Helm-managed** (release `kagent-mgmt`, chart `management`). Neither the
kagent-mgmt nor the agentregistry chart exposes a value for an extra trace exporter, so
this is a live patch. **`helm upgrade kagent-mgmt` will revert it.** Re-apply after any
upgrade:

```bash
kubectl apply -f observability/solo-enterprise-telemetry-collector-config.patched.yaml
kubectl -n kagent rollout restart statefulset solo-enterprise-telemetry-collector
```

(For a permanent fix, upstream the exporter into the management chart's collector template.)

## Verify

```bash
# Should be > 0 and growing while agents are invoked:
kubectl -n agentregistry-system exec agentregistry-enterprise-clickhouse-shard0-0 -- \
  clickhouse-client -q "SELECT count(), max(Timestamp) FROM agentregistry.otel_traces_json"

# kagent UI backend should still be receiving too:
kubectl -n kagent exec kagent-mgmt-clickhouse-shard0-0 -- \
  clickhouse-client -q "SELECT count(), max(Timestamp) FROM platformdb.otel_traces_json"
```

## Rollback

```bash
kubectl apply -f observability/backups/solo-enterprise-telemetry-collector-config.backup.yaml
kubectl -n kagent rollout restart statefulset solo-enterprise-telemetry-collector
```

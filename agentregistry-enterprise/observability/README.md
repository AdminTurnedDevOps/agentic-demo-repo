# Observability: AgentRegistry UI on the kagent ClickHouse

As of **AgentRegistry Enterprise v2026.9.0**, the Dashboard (Agent Runs,
Operations, Token Usage) and Tracing page read ClickHouse through the server
env vars `CLICKHOUSE_*`. When agents run on kagent, those traces land in
**kagent** ClickHouse (`platformdb.otel_traces_json`), not the bundled
AgentRegistry ClickHouse.

| Signal on kagent agents | Env var | Destination |
|---|---|---|
| logs / metrics | `OTEL_EXPORTER_OTLP_ENDPOINT` | AgentRegistry collector (optional) |
| **traces** | `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | kagent `solo-enterprise-telemetry-collector` → `platformdb.otel_traces_json` |

v2026.8.0 token-usage SQL was a simple `SELECT` and could run through a
ClickHouse `remote()` view. v2026.9.0 rewrote token usage to `WITH RECURSIVE`
CTEs (`#1475`). Tracing uses similar `WITH` CTEs. Those queries fail if
AgentRegistry is pointed at a `remote()` view of kagent ClickHouse.

## Symptoms

- Dashboard **Agent Runs** and **Operations** have data, **Token Usage** says no data.
- **Tracing** shows `Server Error` / `There was an error fetching data from the server.`

A `remote()` view of `platformdb.otel_traces_json` still serves simple
`SELECT`s. Token usage and Tracing push their CTEs to the kagent ClickHouse
using AgentRegistry's database name, which does not exist there:

```text
DB::Exception: Received from kagent-mgmt-clickhouse.kagent.svc.cluster.local:9000.
Database <agentregistry-database> does not exist.
```

The dashboard treats a failed token-usage RPC as an empty chart. Tracing
renders the same failure as a server error.

Separately, if the kagent ClickHouse PVC is full, metric inserts fail with
`Cannot reserve 1.00 MiB, not enough space`. Check `system.query_views_log`
and other `system.*` logs; they may have no TTL.

## Target wiring

Create a **local** view on the kagent ClickHouse instance (same server as
`platformdb`) so CTEs run locally. Point AgentRegistry at that database, not
at `platformdb` itself.

```text
AgentRegistry UI
  -> agentregistry-enterprise-server
       CLICKHOUSE_ADDR = kagent-mgmt-clickhouse.kagent.svc.cluster.local
       CLICKHOUSE_DB   = agentregistry
  -> kagent ClickHouse
       agentregistry.otel_traces_json          VIEW of platformdb.otel_traces_json
       platformdb.otel_traces_json             real table (kagent collector)
```

Do not set `CLICKHOUSE_DB=platformdb`. AgentRegistry embeds its own
ClickHouse migrations (head `3008003` in v2026.9.0). kagent-mgmt owns
`platformdb` at a newer migration head. Pointing AgentRegistry at
`platformdb` makes golang-migrate fail or alter kagent's schema.

### Files here

- `kagent-otel-traces-view.sql` — create the local view on kagent ClickHouse.
- `solo-enterprise-telemetry-collector-config.patched.yaml` — older optional
  fan-out of kagent traces to the AgentRegistry collector. The UI does not
  need that path once it reads kagent ClickHouse directly.
- `backups/solo-enterprise-telemetry-collector-config.backup.yaml` — original
  kagent collector ConfigMap.

Adjust namespace, StatefulSet, and password if the install does not use the
chart defaults below.

## Apply

```bash
kubectl -n kagent exec -i kagent-mgmt-clickhouse-shard0-0 -- \
  clickhouse-client --user default --password password --multiquery \
  < observability/kagent-otel-traces-view.sql

kubectl -n agentregistry-system create secret generic agentregistry-kagent-clickhouse \
  --from-literal=address=kagent-mgmt-clickhouse.kagent.svc.cluster.local \
  --from-literal=port=9000 \
  --from-literal=database=agentregistry \
  --from-literal=username=default \
  --from-literal=password=password \
  --dry-run=client -o yaml | kubectl apply -f -
```

Wire the secret into the AgentRegistry server with Helm `extraEnvVars`
(`CLICKHOUSE_ADDR`, `CLICKHOUSE_PORT`, `CLICKHOUSE_DB`, `CLICKHOUSE_USER`,
`CLICKHOUSE_PASSWORD` from `secretKeyRef` `agentregistry-kagent-clickhouse`),
then restart:

```bash
kubectl -n agentregistry-system rollout restart deploy/agentregistry-enterprise-server
kubectl -n agentregistry-system rollout status deploy/agentregistry-enterprise-server --timeout=180s
```

If ClickHouse disk is exhausted, inspect free space and truncate oversized
`system.*` logs, then set a TTL so they cannot refill the PVC:

```bash
kubectl -n kagent exec kagent-mgmt-clickhouse-shard0-0 -- clickhouse-client \
  --user default --password password -q \
  "SELECT formatReadableSize(free_space) FROM system.disks"
```

## Verify

```bash
kubectl -n agentregistry-system exec deploy/agentregistry-enterprise-server -- \
  sh -c 'echo $CLICKHOUSE_ADDR $CLICKHOUSE_DB'

kubectl -n kagent exec kagent-mgmt-clickhouse-shard0-0 -- clickhouse-client \
  --user default --password password -q \
  "SELECT name, engine FROM system.tables WHERE database='agentregistry' AND name='otel_traces_json'"

kubectl -n kagent exec kagent-mgmt-clickhouse-shard0-0 -- clickhouse-client \
  --user default --password password --database agentregistry -q \
  "SELECT count(), max(Timestamp) FROM otel_traces_json"

kubectl -n kagent exec kagent-mgmt-clickhouse-shard0-0 -- clickhouse-client \
  --user default --password password --database agentregistry -q \
  "SELECT count() FROM otel_traces_json
   WHERE SpanAttributes.gen_ai.usage.input_tokens IS NOT NULL
     AND (SpanName = 'call_llm' OR SpanAttributes.gen_ai.operation.name::String IN ('chat','generate_content'))"
```

`engine` should be `View`. Token Usage should chart models after a real agent
chat. Tracing should list `call_llm` / `invoke_agent` rows instead of a
server error. Card fetches and gateway HTTP spans do not populate those
widgets.

## Rollback

Point AgentRegistry back at its bundled ClickHouse (Tracing / token usage
will fail again on v2026.9.0 if that database is still a `remote()` view):

```bash
kubectl -n agentregistry-system create secret generic agentregistry-kagent-clickhouse \
  --from-literal=address=agentregistry-enterprise-clickhouse.agentregistry-system.svc.cluster.local \
  --from-literal=port=9000 \
  --from-literal=database=agentregistry \
  --from-literal=username=default \
  --from-literal=password=password \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n agentregistry-system rollout restart deploy/agentregistry-enterprise-server
```

To drop the view on kagent ClickHouse and restore a local MergeTree that was
renamed aside:

```bash
kubectl -n kagent exec kagent-mgmt-clickhouse-shard0-0 -- clickhouse-client \
  --user default --password password -q \
  "DROP VIEW IF EXISTS agentregistry.otel_traces_json;
   RENAME TABLE IF EXISTS agentregistry.otel_traces_json_empty_local TO agentregistry.otel_traces_json"
```

## Caveats

- The view is not Helm-managed. Recreating the kagent ClickHouse pod keeps it
  (PVC). Recreating the PVC does not.
- A later AgentRegistry release that applies new ClickHouse migrations
  against database `agentregistry` may `ALTER TABLE otel_traces_json` and
  fail on the view. Re-check after upgrading the chart past v2026.9.0.
- The bundled AgentRegistry collector still writes to the bundled ClickHouse
  by default. The UI does not use that write path once `CLICKHOUSE_*` points
  at kagent ClickHouse.

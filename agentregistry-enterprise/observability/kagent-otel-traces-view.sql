-- As of AgentRegistry Enterprise v2026.9.0, token usage and Tracing use
-- WITH / WITH RECURSIVE CTEs. Those fail against a remote() view of kagent
-- ClickHouse because the outer query is shipped with the caller's database
-- name, which does not exist on the kagent instance.
--
-- Apply on the kagent ClickHouse instance (chart-default names):
--   kubectl -n kagent exec -i kagent-mgmt-clickhouse-shard0-0 -- \
--     clickhouse-client --user default --password password --multiquery \
--     < kagent-otel-traces-view.sql

CREATE DATABASE IF NOT EXISTS agentregistry;

-- Keep any leftover local MergeTree aside so this is reversible.
RENAME TABLE IF EXISTS agentregistry.otel_traces_json TO agentregistry.otel_traces_json_empty_local;

CREATE VIEW IF NOT EXISTS agentregistry.otel_traces_json AS
SELECT
    Timestamp,
    TraceId,
    SpanId,
    ParentSpanId,
    TraceState,
    SpanName,
    SpanKind,
    ServiceName,
    ResourceAttributes,
    ScopeName,
    ScopeVersion,
    SpanAttributes,
    Duration,
    StatusCode,
    StatusMessage
FROM platformdb.otel_traces_json;

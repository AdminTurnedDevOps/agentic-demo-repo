# Agentregistry Enterprise Tracing

Agentregistry Enterprise stores traces in ClickHouse and displays them in the AgentRegistry UI under **Tracing**. Workloads send OTLP data to the AgentRegistry telemetry collector, and the collector writes traces to the `otel_traces_json` ClickHouse table.

This guide documents the setup needed for both in-cluster runtimes, such as kagent, and external runtimes, such as AWS Bedrock AgentCore.

## How Tracing Works

Agentregistry has three tracing pieces:

- ClickHouse stores trace rows in `agentregistry.otel_traces_json`.
- The bundled OpenTelemetry Collector receives OTLP on ports `4317` and `4318`.
- Runtime resources use `spec.telemetryEndpoint` to export `OTEL_EXPORTER_OTLP_ENDPOINT` to deployed workloads.

Use `spec.telemetryEndpoint`, not `spec.runtimeConfig`, to enable trace export for a runtime.

`spec.runtimeConfig` is for runtime-specific deployment parameters such as AWS region, workdir, VPC subnet IDs, and security groups.

## 1. Enable Agentregistry Telemetry

The Helm chart must enable both ClickHouse and telemetry:

```yaml
clickhouse:
  enabled: true

telemetry:
  enabled: true
```

For external runtimes such as AWS AgentCore, expose the collector with a `LoadBalancer`:

```yaml
telemetry:
  enabled: true
  service:
    type: LoadBalancer
```

Apply this to an existing install:

```bash
helm upgrade agentregistry-enterprise \
  oci://us-docker.pkg.dev/solo-public/agentregistry-enterprise/helm/agentregistry-enterprise \
  --version 2026.5.4 \
  -n agentregistry-system \
  --reuse-values \
  --set telemetry.service.type=LoadBalancer \
  --wait --timeout 10m
```

Get the external OTLP endpoint:

```bash
export OTEL_COLLECTOR_HOST=$(kubectl get svc agentregistry-enterprise-telemetry-collector \
  -n agentregistry-system \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}{.status.loadBalancer.ingress[0].hostname}')

export OTEL_HTTP_ENDPOINT="http://${OTEL_COLLECTOR_HOST}:4318"
echo "${OTEL_HTTP_ENDPOINT}"
```

For in-cluster runtimes, use the internal service DNS name instead:

```text
http://agentregistry-enterprise-telemetry-collector.agentregistry-system.svc.cluster.local:4318
```

## 2. Register or Update Runtime Telemetry

### AWS Bedrock AgentCore Runtime

AWS AgentCore runs outside the Kubernetes cluster, so it must use the collector's external `LoadBalancer` address.

```bash
export AWS_ROLE_ARN="<RoleArn from CloudFormation output>"
export AWS_EXTERNAL_ID="<ExternalId from CloudFormation output>"
export AWS_REGION="us-east-1"
export OTEL_HTTP_ENDPOINT="http://${OTEL_COLLECTOR_HOST}:4318"

cat > /tmp/aws-runtime.yaml <<EOF
apiVersion: ar.dev/v1alpha1
kind: Runtime
metadata:
  name: AWS
spec:
  type: BedrockAgentCore
  telemetryEndpoint: "${OTEL_HTTP_ENDPOINT}"
  config:
    region: "${AWS_REGION}"
    roleArn: "${AWS_ROLE_ARN}"
    externalId: "${AWS_EXTERNAL_ID}"
EOF

arctl apply -f /tmp/aws-runtime.yaml
arctl get runtime AWS -o yaml
```

Existing deployments do not automatically restart just because the runtime changed. Re-apply or redeploy the AgentCore deployment so the workload receives the new telemetry endpoint:

```yaml
apiVersion: ar.dev/v1alpha1
kind: Deployment
metadata:
  name: demochatbot
spec:
  targetRef:
    kind: Agent
    name: demochatbot
    tag: "1.0.4"
  runtimeRef:
    kind: Runtime
    name: AWS
  runtimeConfig:
    region: us-east-1
    workdir: agentregistry-enterprise/demochatbot-a2a
```

### kagent Runtime

kagent runs in the same cluster, so it can use the collector service DNS name:

```yaml
apiVersion: ar.dev/v1alpha1
kind: Runtime
metadata:
  name: kagent
spec:
  type: Kagent
  telemetryEndpoint: http://agentregistry-enterprise-telemetry-collector.agentregistry-system.svc.cluster.local:4318
  config:
    kagentUrl: http://kagent-controller.kagent.svc.cluster.local:8083
    namespace: kagent
```

Agentregistry injects the runtime telemetry endpoint into kagent BYO agents as `OTEL_EXPORTER_OTLP_ENDPOINT`.

Note that kagent itself might also inject its own tracing variables, such as `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, pointing to kagent's management collector. If you need traces to appear only in Agentregistry, make sure the deployed agent image and kagent runtime prefer the Agentregistry endpoint or override the kagent-injected values.

## 3. Verify the Pipeline

Check the collector service:

```bash
kubectl get svc agentregistry-enterprise-telemetry-collector -n agentregistry-system
kubectl get pods -n agentregistry-system -l app.kubernetes.io/component=telemetry-collector
```

Check ClickHouse tables:

```bash
kubectl exec -n agentregistry-system statefulset/agentregistry-enterprise-clickhouse-shard0 -- \
  clickhouse-client --user default --password password \
  --query 'SHOW TABLES FROM agentregistry'
```

Check trace count:

```bash
kubectl exec -n agentregistry-system statefulset/agentregistry-enterprise-clickhouse-shard0 -- \
  clickhouse-client --user default --password password \
  --query 'SELECT count() FROM agentregistry.otel_traces_json'
```

After invoking an instrumented agent, the count should increase.

## 4. Open the UI

In AgentRegistry Enterprise, go to:

```text
Tracing
```

Tracing access currently requires a registry admin role.

## Troubleshooting

### `otel_traces_json` exists but has zero rows

The tracing schema exists, but no workload has successfully exported traces yet.

Check:

- The runtime has `spec.telemetryEndpoint` set.
- The deployment was re-applied after setting `spec.telemetryEndpoint`.
- The agent image actually emits OpenTelemetry traces.
- External runtimes can reach the collector endpoint.
- The collector logs do not show exporter or ClickHouse write errors.

### AWS AgentCore cannot reach the collector

AWS AgentCore cannot use Kubernetes service DNS names. Use the collector `LoadBalancer` endpoint:

```text
http://<collector-external-ip-or-hostname>:4318
```

### kagent traces go to kagent instead of Agentregistry

kagent may inject its own tracing endpoint into agent workloads. Check the generated Deployment:

```bash
kubectl get deploy <agent-name> -n kagent -o yaml | grep -i OTEL
```

If `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` points to kagent's collector, traces might appear in kagent observability instead of Agentregistry.

### Collector is internal only

If the service type is `ClusterIP`, external runtimes cannot reach it:

```bash
kubectl get svc agentregistry-enterprise-telemetry-collector -n agentregistry-system
```

Set `telemetry.service.type=LoadBalancer` for external runtime tracing.

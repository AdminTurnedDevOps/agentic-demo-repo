# Tracing Setup for Agentgateway with Tempo and OpenTelemetry

This guide sets up distributed tracing for agentgateway on Kubernetes using Grafana Tempo and OpenTelemetry Collectors.

## Architecture

```
agentgateway proxy --> OTel Collector (traces) --> Tempo --> Grafana
     (agentgateway-system)        (monitoring)      (monitoring)   (monitoring)
```

## Prerequisites

- Kubernetes cluster with agentgateway deployed
- kube-prometheus stack installed in `monitoring` namespace
- Gateway API CRDs installed

## Step 1: Install Grafana Tempo

Deploy Tempo in the `monitoring` namespace with OTLP gRPC receiver enabled.

```bash
helm upgrade --install tempo tempo \
  --repo https://grafana.github.io/helm-charts \
  --namespace monitoring \
  --values - <<EOF
persistence:
  enabled: false
tempo:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
EOF
```

## Step 2: Deploy OTel Collector for Traces

Deploy a dedicated OpenTelemetry Collector that receives OTLP and exports to Tempo.

```bash
helm upgrade --install opentelemetry-collector-traces opentelemetry-collector \
  --repo https://open-telemetry.github.io/opentelemetry-helm-charts \
  --version 0.127.2 \
  --set mode=deployment \
  --set image.repository="otel/opentelemetry-collector-contrib" \
  --set command.name="otelcol-contrib" \
  --namespace monitoring \
  -f -<<EOF
config:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
        http:
          endpoint: 0.0.0.0:4318
  exporters:
    otlp/tempo:
      endpoint: http://tempo.monitoring.svc.cluster.local:4317
      tls:
        insecure: true
    debug:
      verbosity: detailed
  service:
    pipelines:
      traces:
        receivers: [otlp]
        processors: [batch]
        exporters: [debug, otlp/tempo]
EOF
```

## Step 3: Configure Grafana Datasource for Tempo

Add Tempo as a datasource in your existing kube-prometheus Grafana:

```bash
helm upgrade kube-prometheus-stack -n monitoring prometheus-community/kube-prometheus-stack \
  --reuse-values \
  --set 'grafana.additionalDataSources[0].name=Tempo' \
  --set 'grafana.additionalDataSources[0].type=tempo' \
  --set 'grafana.additionalDataSources[0].access=proxy' \
  --set 'grafana.additionalDataSources[0].url=http://tempo.monitoring.svc.cluster.local:3200' \
  --set 'grafana.additionalDataSources[0].uid=tempo'
```

## Step 4: Create ReferenceGrant for Cross-Namespace Access

Allow the AgentgatewayPolicy in `agentgateway-system` to reference the OTel collector service in `monitoring`.

```bash
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-otel-collector-traces-access
  namespace: monitoring
spec:
  from:
  - group: agentgateway.dev
    kind: AgentgatewayPolicy
    namespace: agentgateway-system
  to:
  - group: ""
    kind: Service
    name: opentelemetry-collector-traces
EOF
```

## Step 5: Create AgentgatewayPolicy for Tracing

Configure tracing on agentgateway using the native `AgentgatewayPolicy` CRD.

```bash
kubectl apply -f - <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: tracing-policy
  namespace: agentgateway-system
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: agentgateway-route
  frontend:
    tracing:
      backendRef:
        name: opentelemetry-collector-traces
        namespace: monitoring
        port: 4317
      protocol: GRPC
      clientSampling: "true"
      randomSampling: "true"
      resources:
        - name: deployment.environment
          expression: '"development"'
        - name: service.name
          expression: '"agentgateway"'
      attributes:
        add:
        - name: request.host
          expression: 'request.host'
EOF
```

## Verification

1. Verify Tempo is running:
```bash
kubectl get pods -n monitoring -l app.kubernetes.io/name=tempo
```

2. Verify OTel Collector is running:
```bash
kubectl get pods -n monitoring -l app.kubernetes.io/instance=opentelemetry-collector-traces
```

3. Check AgentgatewayPolicy status:
```bash
kubectl get agentgatewaypolicies -n agentgateway-system
```

4. Check OTel Collector logs for trace reception:
```bash
kubectl logs -n monitoring -l app.kubernetes.io/instance=opentelemetry-collector-traces
```

5. View traces in Grafana:
```bash
kubectl port-forward svc/kube-prometheus-grafana -n monitoring 3000:80
```
- Navigate to Explore > Tempo datasource
- Search for traces by service name "agentgateway"

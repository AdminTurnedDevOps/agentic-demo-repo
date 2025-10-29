## Installation

```
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml
```

```
helm upgrade -i --create-namespace --namespace kgateway-system --version v2.1.1 \
kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds \
--set controller.image.pullPolicy=Always
```

3. You'll notice the `controller.extraEnv.KGW_GLOBAL_POLICY_NAMESPACE`, which is for Global Policy Attachments
```
helm upgrade -i -n kgateway-system kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway \
     --set gateway.aiExtension.enabled=true \
     --set agentgateway.enabled=true \
     --set controller.extraEnv.KGW_GLOBAL_POLICY_NAMESPACE=kgateway-system \
     --version v2.1.1
```

```
kubectl get pods -n kgateway-system
```

## Gateway Setup

1. Create env variable for Anthropic key

```
export ANTHROPIC_API_KEY=
```

2. Create a secret to store the Claude API key
```
kubectl apply -f- <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: anthropic-secret
  namespace: kgateway-system
  labels:
    app: agentgateway
type: Opaque
stringData:
  Authorization: $ANTHROPIC_API_KEY
EOF
```

3. Create a Gateway for Anthropic

A `Gateway` resource is used to trigger kgateway to deploy agentgateway data plane Pods

The Agentgateway data plane Pod is the Pod that gets created when a Gateway object is created in a Kubernetes environment where Agentgateway is deployed as the Gateway API implementation.
```
kubectl apply -f- <<EOF
kind: Gateway
apiVersion: gateway.networking.k8s.io/v1
metadata:
  name: agentgateway
  namespace: kgateway-system
  labels:
    app: agentgateway
spec:
  gatewayClassName: agentgateway
  listeners:
  - protocol: HTTP
    port: 8080
    name: http
    allowedRoutes:
      namespaces:
        from: All
EOF
```

4. Create a `Backend` object 

A Backend resource to define a backing destination that you want kgateway to route to. In this case, it's Claude.
```
kubectl apply -f- <<EOF
apiVersion: gateway.kgateway.dev/v1alpha1
kind: Backend
metadata:
  labels:
    app: agentgateway
  name: anthropic
  namespace: kgateway-system
spec:
  type: AI
  ai:
    llm:
        anthropic:
          authToken:
            kind: SecretRef
            secretRef:
              name: anthropic-secret
          model: "claude-3-5-haiku-latest"
EOF
```

5. Ensure everything is running as expected
```
kubectl get backend -n kgateway-system
```

6. Apply the Route so you can reach the LLM
```
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: claude
  namespace: kgateway-system
  labels:
    app: agentgateway
spec:
  parentRefs:
    - name: agentgateway
      namespace: kgateway-system
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
      namespace: kgateway-system
      group: gateway.kgateway.dev
      kind: Backend
EOF
```

7. Capture the LB IP of the service. This will be used to send a request to the LLM.
```
export INGRESS_GW_ADDRESS=$(kubectl get svc -n kgateway-system agentgateway -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESS
```

8. Test the LLM connectivity
```
curl "$INGRESS_GW_ADDRESS:8080/anthropic" -v \ -H content-type:application/json -H x-api-key:$ANTHROPIC_API_KEY -H "anthropic-version: 2023-06-01" -d '{
  "model": "claude-sonnet-4-5",
  "messages": [
    {
      "role": "system",
      "content": "You are a skilled cloud-native network engineer."
    },
    {
      "role": "user",
      "content": "Write me a paragraph containing the best way to think about Istio Ambient Mesh"
    }
  ]
}' | jq
```

## Global Policy Attachment
In a standard configuration, you must attach policies to resources that are in the same namespace. However, you might have policies that you want to reuse across teams.

1. Update the `HTTPRoute` with the global policy configuration
```
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: claude
  namespace: default
  labels:
    global-policy: rateLimit
  labels:
    app: agentgateway
spec:
  parentRefs:
    - name: agentgateway
      namespace: kgateway-system
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
      namespace: kgateway-system
      group: gateway.kgateway.dev
      kind: Backend
EOF
```

2. Update the traffic policy to use the targetSelectors block to specify the `global-policy` label, which will match the `global-policy` label in your `HTTPRoute`, which means your `HTTPRoute` will use this global policy.
```
kubectl apply -f- <<EOF
apiVersion: gateway.kgateway.dev/v1alpha1
kind: TrafficPolicy
metadata:
  name: anthropic-ratelimitglobal
  namespace: kgateway-system
spec:
  targetSelectors:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    matchLabels:
      global-policy: rateLimit
  rateLimit:
    local:
      tokenBucket:
        maxTokens: 1
        tokensPerFill: 1
        fillInterval: 100s
EOF
```

2. Capture the LB IP of the service. This will be used later to send a request to the LLM.
```
export INGRESS_GW_ADDRESS=$(kubectl get svc -n kgateway-system agentgateway -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESS
```

3. Test the LLM connectivity
```
curl "$INGRESS_GW_ADDRESS:8080/anthropic" -v \ -H content-type:application/json -H x-api-key:$ANTHROPIC_API_KEY -H "anthropic-version: 2023-06-01" -d '{
  "model": "claude-sonnet-4-5",
  "messages": [
    {
      "role": "system",
      "content": "You are a skilled cloud-native network engineer."
    },
    {
      "role": "user",
      "content": "Write me a paragraph containing the best way to think about Istio Ambient Mesh"
    }
  ]
}' | jq
```

4. Run the `curl` again and you'll see some Rate Limiting errors

5. If you check the agentgateway Pod logs, you'll see the rate limit error there as well.

```
kubectl logs -n kgateway-system agentgateway-pod-name --tail=50 | grep -i "request\|error\|anthropic"
```

```
2025-10-20T16:08:59.886579Z     info    request gateway=kgateway-system/agentgateway listener=http route=kgateway-system/claude src.addr=10.142.0.25:42187 http.method=POST http.host=34.148.15.158 http.path=/anthropic http.version=HTTP/1.1 http.status=429 error="rate limit exceeded" duration=0ms
```

6. Delete the traffic policy for cleanup
```
kubectl delete -f- <<EOF
apiVersion: gateway.kgateway.dev/v1alpha1
kind: TrafficPolicy
metadata:
  name: anthropic-ratelimit
  namespace: kgateway-system
spec:
  targetSelectors:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
      matchLabels:
        global-policy: transformation
  rateLimit:
    local:
      tokenBucket:
        maxTokens: 1
        tokensPerFill: 1
        fillInterval: 100s
EOF
```

## HPA

1. Install the Metrics Server
```
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl -n kube-system patch deployment metrics-server \
 --type=json \
 -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
```

2. Configure autoscaling for the agentgateway data plane Pod
```
kubectl apply -f- <<EOF
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: hpa
  namespace: kgateway-system
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: agentgateway
  minReplicas: 1
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: memory
        target:
          type: AverageValue
          averageValue: 10Mi
EOF
```

## Monitoring & Observability

1. Install Loki and Tempo (Logging and Tracing)
```
helm upgrade --install loki loki \
--repo https://grafana.github.io/helm-charts \
--namespace telemetry \
--create-namespace \
--values - <<EOF
loki:
  commonConfig:
    replication_factor: 1
  schemaConfig:
    configs:
      - from: 2024-04-01
        store: tsdb
        object_store: s3
        schema: v13
        index:
          prefix: loki_index_
          period: 24h
  auth_enabled: false
singleBinary:
  replicas: 1
minio:
  enabled: true
gateway:
  enabled: false
test:
  enabled: false
monitoring:
  selfMonitoring:
    enabled: false
    grafanaAgent:
      installOperator: false
lokiCanary:
  enabled: false
limits_config:
  allow_structured_metadata: true
memberlist:
  service:
    publishNotReadyAddresses: true
deploymentMode: SingleBinary
backend:
  replicas: 0
read:
  replicas: 0
write:
  replicas: 0
ingester:
  replicas: 0
querier:
  replicas: 0
queryFrontend:
  replicas: 0
queryScheduler:
  replicas: 0
distributor:
  replicas: 0
compactor:
  replicas: 0
indexGateway:
  replicas: 0
bloomCompactor:
  replicas: 0
bloomGateway:
  replicas: 0
EOF
```

```
helm upgrade --install tempo tempo \
--repo https://grafana.github.io/helm-charts \
--namespace telemetry \
--create-namespace \
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

2. Deploy the OTel Collectors for Metrics, Traces, and Logs (you'll see in the configs below that these Collectors point to kube-prometheus)

```
helm upgrade --install opentelemetry-collector-metrics opentelemetry-collector \
--repo https://open-telemetry.github.io/opentelemetry-helm-charts \
--version 0.127.2 \
--set mode=deployment \
--set image.repository="otel/opentelemetry-collector-contrib" \
--set command.name="otelcol-contrib" \
--namespace=telemetry \
--create-namespace \
-f -<<EOF
clusterRole:
  create: true
  rules:
  - apiGroups:
    - ''
    resources:
    - 'pods'
    - 'nodes'
    verbs:
    - 'get'
    - 'list'
    - 'watch'
ports:
  promexporter:
    enabled: true
    containerPort: 9099
    servicePort: 9099
    protocol: TCP

command:
  extraArgs:
    - "--feature-gates=receiver.prometheusreceiver.EnableNativeHistograms"

config:
  receivers:
    prometheus/kgateway-dataplane:
      config:
        global:
          scrape_protocols: [ PrometheusProto, OpenMetricsText1.0.0, OpenMetricsText0.0.1, PrometheusText0.0.4 ]
        scrape_configs:
        # Scrape the kgateway proxy pods
        - job_name: kgateway-gateways
          honor_labels: true
          kubernetes_sd_configs:
          - role: pod
          relabel_configs:
            - action: keep
              regex: kube-gateway
              source_labels:
              - __meta_kubernetes_pod_label_kgateway
            - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
              action: keep
              regex: true
            - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
              action: replace
              target_label: __metrics_path__
              regex: (.+)
            - action: replace
              source_labels:
              - __meta_kubernetes_pod_ip
              - __meta_kubernetes_pod_annotation_prometheus_io_port
              separator: ':'
              target_label: __address__
            - action: labelmap
              regex: __meta_kubernetes_pod_label_(.+)
            - source_labels: [__meta_kubernetes_namespace]
              action: replace
              target_label: kube_namespace
            - source_labels: [__meta_kubernetes_pod_name]
              action: replace
              target_label: pod
    prometheus/kgateway-controlplane:
      config:
        global:
          scrape_protocols: [ PrometheusProto, OpenMetricsText1.0.0, OpenMetricsText0.0.1, PrometheusText0.0.4 ]
        scrape_configs:
        # Scrape the kgateway controlplane pods
        - job_name: kgateway-controlplane
          honor_labels: true
          kubernetes_sd_configs:
          - role: pod
          relabel_configs:
            - action: keep
              regex: kgateway
              source_labels:
              - __meta_kubernetes_pod_label_kgateway
            - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
              action: keep
              regex: true
            - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
              action: replace
              target_label: __metrics_path__
              regex: (.+)
            - action: replace
              source_labels:
              - __meta_kubernetes_pod_ip
              - __meta_kubernetes_pod_annotation_prometheus_io_port
              separator: ':'
              target_label: __address__
            - action: labelmap
              regex: __meta_kubernetes_pod_label_(.+)
            - source_labels: [__meta_kubernetes_namespace]
              action: replace
              target_label: kube_namespace
            - source_labels: [__meta_kubernetes_pod_name]
              action: replace
              target_label: pod
  exporters:
    prometheus:
      endpoint: 0.0.0.0:9099
    prometheusremotewrite/kube-prometheus-stack:
      endpoint: http://kube-prometheus-stack-prometheus.telemetry.svc:9090/api/v1/write
    debug:
      verbosity: detailed
  service:
    pipelines:
      metrics:
        receivers: [prometheus/kgateway-dataplane, prometheus/kgateway-controlplane]
        processors: [batch]
        exporters: [debug, prometheusremotewrite/kube-prometheus-stack]
EOF
```

```
helm upgrade --install opentelemetry-collector-logs opentelemetry-collector \
--repo https://open-telemetry.github.io/opentelemetry-helm-charts \
--version 0.127.2 \
--set mode=deployment \
--set image.repository="otel/opentelemetry-collector-contrib" \
--set command.name="otelcol-contrib" \
--namespace=telemetry \
--create-namespace \
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
    otlphttp/loki:
      endpoint: http://loki.telemetry.svc.cluster.local:3100/otlp
      tls:
        insecure: true
    debug:
      verbosity: detailed
  service:
    pipelines:
      logs:
        receivers: [otlp]
        processors: [batch]
        exporters: [debug, otlphttp/loki]
EOF
```

```
helm upgrade --install opentelemetry-collector-traces opentelemetry-collector \
--repo https://open-telemetry.github.io/opentelemetry-helm-charts \
--version 0.127.2 \
--set mode=deployment \
--set image.repository="otel/opentelemetry-collector-contrib" \
--set command.name="otelcol-contrib" \
--namespace=telemetry \
--create-namespace \
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
      endpoint: http://tempo.telemetry.svc.cluster.local:4317
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

3. Install kube-prometheus with the correct pointers to Loki and Tempo
```
helm upgrade --install kube-prometheus-stack kube-prometheus-stack \
--repo https://prometheus-community.github.io/helm-charts \
--version 75.6.1 \
--namespace telemetry \
--create-namespace \
--values - <<EOF
alertmanager:
  enabled: false
prometheus:
  prometheusSpec:
    ruleSelectorNilUsesHelmValues: false
    serviceMonitorSelectorNilUsesHelmValues: false
    podMonitorSelectorNilUsesHelmValues: false
    enableFeatures:
      - native-histograms
    enableRemoteWriteReceiver: true
grafana:
  enabled: true
  defaultDashboardsEnabled: true
  datasources:
   datasources.yaml:
     apiVersion: 1
     datasources:
      - name: Prometheus
        type: prometheus
        uid: prometheus
        access: proxy
        orgId: 1
        url: http://kube-prometheus-stack-prometheus.telemetry:9090
        basicAuth: false
        editable: true
        jsonData:
          httpMethod: GET
          exemplarTraceIdDestinations:
          - name: trace_id
            datasourceUid: tempo
      - name: Tempo
        type: tempo
        access: browser
        basicAuth: false
        orgId: 1
        uid: tempo
        url: http://tempo.telemetry.svc.cluster.local:3100
        isDefault: false
        editable: true
      - orgId: 1
        name: Loki
        type: loki
        typeName: Loki
        access: browser
        url: http://loki.telemetry.svc.cluster.local:3100
        basicAuth: false
        isDefault: false
        editable: true
EOF
```

4. Deploy a Listener to collect and store logs and a ReferenceGrant to so that the `HTTPListenerPolicy` can apply to the OTel logs collector service.
```
kubectl apply -f- <<EOF
apiVersion: gateway.kgateway.dev/v1alpha1
kind: HTTPListenerPolicy
metadata:
  name: logging-policy
  namespace: kgateway-system
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: agentgateway
  accessLog:
  - openTelemetry:
      grpcService:
        backendRef:
          name: opentelemetry-collector-logs
          namespace: telemetry
          port: 4317
        logName: "http-gateway-access-logs"
      body: >-
        "%REQ(:METHOD)% %REQ(X-ENVOY-ORIGINAL-PATH?:PATH)% %RESPONSE_CODE% "%REQ(:AUTHORITY)%" "%UPSTREAM_CLUSTER%"'        
EOF
```

```
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-otel-collector-logs-access
  namespace: telemetry
spec:
  from:
  - group: gateway.kgateway.dev
    kind: HTTPListenerPolicy
    namespace: kgateway-system
  to:
  - group: ""
    kind: Service
    name: opentelemetry-collector-logs
EOF
```

5. Create another listener and grant for traces
```
kubectl apply -f- <<EOF
apiVersion: gateway.kgateway.dev/v1alpha1
kind: HTTPListenerPolicy
metadata:
  name: tracing-policy
  namespace: kgateway-system
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: agentgateway
  tracing:
    provider:
      openTelemetry:
        serviceName: http
        grpcService:
          backendRef:
            name: opentelemetry-collector-traces
            namespace: telemetry
            port: 4317
    spawnUpstreamSpan: true
EOF
```

```
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-otel-collector-traces-access
  namespace: telemetry
spec:
  from:
  - group: gateway.kgateway.dev
    kind: HTTPListenerPolicy
    namespace: kgateway-system
  to:
  - group: ""
    kind: Service
    name: opentelemetry-collector-traces
EOF
```

6. To build a dashboard with the metrics
```
kubectl --namespace monitoring port-forward svc/kube-prometheus-grafana 3000:80
```

To log into the Grafana UI:

1. Username: admin
2. Password: prom-operator

5. Add in the kgateway operations dashboard
```
https://kgateway.dev/docs/latest/observability/kgateway.json
```

6. Perform a `curl` to produce some observability data
```
curl "$INGRESS_GW_ADDRESS:8080/anthropic" -v \ -H content-type:application/json -H x-api-key:$ANTHROPIC_API_KEY -H "anthropic-version: 2023-06-01" -d '{
  "model": "claude-sonnet-4-5",
  "messages": [
    {
      "role": "system",
      "content": "You are a skilled cloud-native network engineer."
    },
    {
      "role": "user",
      "content": "Write me a paragraph containing the best way to think about Istio Ambient Mesh"
    }
  ]
}' | jq
```
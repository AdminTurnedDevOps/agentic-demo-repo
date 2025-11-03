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

```
git clone https://github.com/digitalocean/kubernetes-sample-apps.git
```

```
kubectl create ns emojivoto
```

```
kubectl -n emojivoto apply -k kubernetes-sample-apps/emojivoto-example/kustomize/
```

```
kubectl get pods -n emojivoto
```

```
kubectl apply --context=$CLUSTER1 -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: websvc-gateway
  namespace: emojivoto
spec:
  gatewayClassName: kgateway
  listeners:
  - name: web-svc
    port: 80
    protocol: HTTP
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: websvc
  namespace: emojivoto
spec:
  parentRefs:
  - name: websvc-gateway
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
      - name: web-svc
        port: 80
EOF
```

Test with `curl`
```
export INGRESS_GW_ADDRESS=$(kubectl get svc -n emojivoto websvc-gateway -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESS
```

```
curl -I $INGRESS_GW_ADDRESS
```

## Global Policy Attachment
In a standard configuration, you must attach policies to resources that are in the same namespace. However, you might have policies that you want to reuse across teams.

1. Update the `HTTPRoute` with the global policy configuration
```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: websvc
  namespace: emojivoto
  labels:
    global-policy: testing
spec:
  parentRefs:
  - name: websvc-gateway
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
      - name: web-svc
        port: 80
EOF
```

2. Create a traffic policy to use the targetSelectors block to specify the `global-policy` label, which will match the `global-policy` label in your `HTTPRoute`, which means your `HTTPRoute` will use this global policy.

```
kubectl apply -f- <<EOF  
apiVersion: gateway.kgateway.dev/v1alpha1
kind: TrafficPolicy
metadata:
  name: emojitesting
  namespace: kgateway-system
spec:
  targetSelectors:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    matchLabels:
      global-policy: testing
  transformation:
    response:
      set:
      - name: "x-emojivoto-test"
        value: "global-policy-applied"
      - name: "x-kgateway-version"
        value: "2.1"
EOF
```

3. Test with `curl`
```
export INGRESS_GW_ADDRESS=$(kubectl get svc -n emojivoto websvc-gateway -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESS
```

```
curl -I $INGRESS_GW_ADDRESS
```

4. Delete the traffic policy for cleanup
```
kubectl delete trafficpolicy emojitesting -n kgateway-system
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
  namespace: emojivoto
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: websvc-gateway
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

3. You should now see able to see the HPA
```
kubectl get hpa -n emojivoto
NAME   REFERENCE                   TARGETS                  MINPODS   MAXPODS   REPLICAS   AGE
hpa    Deployment/websvc-gateway   memory: <unknown>/10Mi   1         10        0          7s
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
kubectl --namespace telemetry port-forward svc/kube-prometheus-stack-grafana 3000:80
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
curl -I $INGRESS_GW_ADDRESS
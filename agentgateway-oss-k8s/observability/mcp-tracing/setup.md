## Gateway/MCP Setup

1. Create a gateway for the MCP server you deployed
```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: mcp-gateway
  namespace: agentgateway-system
  labels:
    app: github-mcp-server
spec:
  gatewayClassName: agentgateway
  listeners:
    - name: mcp
      port: 3000
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
EOF
```

2. Create a Kubernetes `Secret` holding your GitHub PAT. The value must be the full `Authorization` header (prefixed with `Bearer `), stored under the key `Authorization` — agentgateway uses this value verbatim as the header on upstream requests.

```
export GITHUB_PAT=

kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: github-pat
  namespace: agentgateway-system
type: Opaque
stringData:
  Authorization: "Bearer ${GITHUB_PAT}"
EOF
```

3. Create the MCP backend

```
kubectl apply -f - <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: github-mcp-server
  namespace: agentgateway-system
spec:
  mcp:
    targets:
      - name: github-copilot
        static:
          host: api.githubcopilot.com
          port: 443
          path: /mcp/
          protocol: StreamableHTTP
          policies:
            tls: {}
            auth:
              secretRef:
                name: github-pat
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: mcp-route
  namespace: agentgateway-system
  labels:
    app: github-mcp-server
spec:
  parentRefs:
    - name: mcp-gateway
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /mcp
      backendRefs:
        - name: github-mcp-server
          namespace: agentgateway-system
          group: agentgateway.dev
          kind: AgentgatewayBackend
EOF
```

```
export GATEWAY_IP=$(kubectl get svc mcp-gateway -n agentgateway-system -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo $GATEWAY_IP
```

```
npx modelcontextprotocol/inspector#0.18.0
```

```
http://YOUR_ALB_IP:3000/mcp
```

## Trace View

This section configures agentgateway to emit OpenTelemetry traces for MCP calls and sends them to Tempo through an OpenTelemetry Collector.

Trace path:

```text
mcp-gateway pod -> opentelemetry-collector-traces -> tempo -> grafana
```

The MCP tool call appears as a `call_tool` trace operation. The literal tool name, such as `get_me`, is available as a span attribute, not necessarily as the trace operation name.

1. Install Tempo

```
helm upgrade --install tempo tempo \
  --repo https://grafana.github.io/helm-charts \
  --version 1.16.0 \
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

2. Install the OpenTelemetry traces collector

```
helm upgrade --install opentelemetry-collector-traces opentelemetry-collector \
  --repo https://open-telemetry.github.io/opentelemetry-helm-charts \
  --version 0.127.2 \
  --set mode=deployment \
  --set image.repository="otel/opentelemetry-collector-contrib" \
  --set command.name="otelcol-contrib" \
  --namespace telemetry \
  --create-namespace \
  -f - <<EOF
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

3. Install Grafana with a Tempo datasource

```
helm upgrade --install kube-prometheus-stack kube-prometheus-stack \
  --repo https://prometheus-community.github.io/helm-charts \
  --namespace telemetry \
  --create-namespace \
  --values - <<EOF
alertmanager:
  enabled: false
prometheus:
  prometheusSpec:
    enableRemoteWriteReceiver: true
grafana:
  enabled: true
  datasources:
    datasources.yaml:
      apiVersion: 1
      datasources:
      - name: Prometheus
        type: prometheus
        uid: prometheus
        access: proxy
        url: http://kube-prometheus-stack-prometheus.telemetry:9090
      - name: Tempo
        type: tempo
        uid: tempo
        access: proxy
        url: http://tempo.telemetry.svc.cluster.local:3100
EOF
```

4. Allow the cross-namespace policy reference

`AgentgatewayPolicy` runs in `agentgateway-system`, but the collector service is in `telemetry`, so Gateway API requires a `ReferenceGrant`.

```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-otel-collector-traces-access
  namespace: telemetry
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

5. Enable tracing on the MCP Gateway

```
kubectl apply -f - <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: mcp-tracing
  namespace: agentgateway-system
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: mcp-gateway
  frontend:
    tracing:
      backendRef:
        name: opentelemetry-collector-traces
        namespace: telemetry
        port: 4317
      protocol: GRPC
      clientSampling: "true"
      randomSampling: "true"
      resources:
      - name: service.name
        expression: '"agentgateway-mcp"'
      - name: deployment.environment.name
        expression: '"development"'
      attributes:
        add:
        - name: mcp.method_name
          expression: 'default(mcp.methodName, "")'
        - name: mcp.session_id
          expression: 'default(mcp.sessionId, "")'
        - name: mcp.tool_name
          expression: 'default(mcp.tool.name, "")'
        - name: mcp.tool_target
          expression: 'default(mcp.tool.target, "")'
        - name: backend.name
          expression: 'default(backend.name, "")'
        - name: backend.type
          expression: 'default(backend.type, "")'
    accessLog:
      attributes:
        add:
        - name: mcp.tool_name
          expression: 'default(mcp.tool.name, "")'
        - name: mcp.tool_target
          expression: 'default(mcp.tool.target, "")'
        - name: mcp.method_name
          expression: 'default(mcp.methodName, "")'
EOF
```

Do not add `mcp.tool.arguments`, `mcp.tool.result`, or `mcp.tool.error` unless you intentionally want payloads in traces or logs. Those fields can expose repository names, user data, or tool output.

6. Verify the telemetry stack

```
kubectl get pods -n telemetry
kubectl get agentgatewaypolicy -n agentgateway-system
kubectl logs -n telemetry -l app.kubernetes.io/instance=opentelemetry-collector-traces --tail=100
```

After running `get_me`, the collector debug logs should show trace spans with attributes like:

```text
mcp.method_name: tools/call
mcp.tool_name: get_me
mcp.tool_target: github-copilot
service.name: agentgateway-mcp
```

7. View the trace in Grafana

```
kubectl --namespace telemetry port-forward svc/kube-prometheus-stack-grafana 3000:80
```

Open:

```text
http://localhost:3000
```

Log in:

```text
username: admin
password: `kubectl get secret kube-prometheus-stack-grafana -n telemetry -o jsonpath='{.data.admin-password}' | base64 --decode`
```

Then:

1. Go to Explore.
2. Select `Tempo`.
3. Query by service name `agentgateway-mcp`.
4. Select operation `call_tool`.
5. Open a recent trace.
6. Inspect span attributes for `mcp.tool_name=get_me`.

8. Debug useful failure points

```
kubectl logs -n agentgateway-system deploy/mcp-gateway --since=10m
kubectl logs -n telemetry -l app.kubernetes.io/instance=opentelemetry-collector-traces --since=10m
kubectl get referencegrant -n telemetry
kubectl describe agentgatewaypolicy mcp-tracing -n agentgateway-system
```

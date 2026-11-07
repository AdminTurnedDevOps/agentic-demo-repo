---
title: "Agent Substrate Observability Lab"
description: >
  Deploy a self-hosted Prometheus and Grafana stack, scrape Agent Substrate's
  built-in Prometheus endpoints, generate actor wake traffic, and observe
  routing latency, lifecycle activity, snapshots, and worker occupancy.
tags: [agent-substrate, kubernetes, observability, prometheus, grafana, opentelemetry]
author: Michael Levan
---

# Agent Substrate Observability Lab

This lab turns the latency measurements from the cost comparison benchmark into
live operational views, using a fully self-hosted **Prometheus + Grafana**
stack. Nothing in this lab depends on GKE, Cloud Monitoring, or any managed
telemetry service — it works on any Kubernetes cluster running Agent Substrate.

You will:

- Deploy Prometheus and Grafana (kube-prometheus-stack).
- Scrape Substrate's built-in Prometheus metrics endpoints with `PodMonitor`s.
- Provision a Grafana dashboard for routing, lifecycle, and snapshot signals.
- Reuse the cost benchmark's in-cluster curl client pattern.
- Generate repeated actor wake, request, and suspend cycles.
- Watch routing and restore latency percentiles live.
- Count lifecycle RPCs and inspect snapshot activity.
- Watch worker assignment and resource usage while load is running.
- Compare the dashboard p95 with the client-measured p95.

Run all commands from the root of the `substrate` repository, checked out at the
`v1.0.0` tag.

## What The Current Source Supports

Substrate's services **dual-export** their metrics
(`internal/serverboot/serverboot.go` registers both readers on one meter
provider). With `OTEL_METRICS_EXPORTER` unset, the default is
`otlp,prometheus`:

1. **OTLP push** — to the `OTEL_EXPORTER_OTLP_ENDPOINT` in the shared
   `ate-otel-config` ConfigMap in `ate-system`. The stock value is
   `http://opentelemetry-collector.gke-managed-otel.svc.cluster.local:4317`
   (the GKE-managed path). On **kind**, the install replaces that ConfigMap and
   points every component at `opentelemetry-collector.otel-system.svc:4317`.
   This lab ignores the OTLP path. A missing collector does not affect the
   Prometheus path, but the exporter logs recurring export errors and keeps
   retrying over the network. If your collector forwards OTLP metrics into the
   same Prometheus, set `OTEL_METRICS_EXPORTER=prometheus` on the components so
   each series arrives once.
2. **A Prometheus `/metrics` endpoint on port `9090`** of `ate-api-server`,
   `atelet`, and `atenet-router` — each pod even carries
   `prometheus.io/scrape: "true"` annotations. `9090` serves only `/metrics`;
   health probes moved to `9091`. This is what this lab scrapes.

Envoy (the data plane of the `atenet-router` pod) is the exception: it serves
Prometheus metrics on port `9902` (container port `envoy-metrics`) at
`/stats/prometheus`. The admin port `9901` is loopback-only on v1.0.0 and can no
longer be scraped.

Worker pods (`ateworker`) serve no `/metrics`. They push OTLP through the atelet
relay, so their series (including their own `rpc_server_call_duration`) do not
appear in this lab's Prometheus.

Because the Prometheus exporter names differ from the OTLP names (dots become
underscores, a unit suffix is appended), the table below lists the names **as
scraped**. The names and labels were checked against the v1.0.0 metric registry
(`docs/metrics/registry/metrics.yaml`), not yet against a live v1.0.0 cluster:

| Goal | Metric (Prometheus name) | Important interpretation |
|---|---|---|
| Wake-path p95 | `atenet_router_route_duration_seconds` (labels `ate_template_atespace`, `ate_template_name`, `ate_router_outcome`, `ate_router_resume`) | Router duration runs from Envoy receiving the request to Envoy forwarding it to the resolved worker. It excludes actor execution and the response. Seconds. `ate_router_resume` is `triggered` when this request did the cold activation, `joined` when it waited on another request's resume, `none` when the actor was already running. |
| Full request p95 | `envoy_http_downstream_rq_time` (label `envoy_http_conn_manager_prefix=~"ingress_https\|main_internal"`) | Includes routing, actor execution, and the response. **Milliseconds.** Direct HTTPS clients land on `ingress_https`; `kubectl ate proxy` (CONNECT) traffic lands on `main_internal`. Always filter — the `admin_metrics` conn manager's own stats (the Prometheus scrapes) dominate otherwise. |
| Resume/suspend activity | `rpc_server_call_duration_seconds_count` (labels `rpc_method`, `rpc_response_status_code`) | `rpc_method` carries the full path, e.g. `substrate.ateapi.v1.Control/ResumeActor`, `atelet.Atelet/Restore`. Counts completed RPC attempts, not guaranteed state transitions. `ate_actor_lifecycle_operation_duration_seconds` (ateapi) records actual activations instead. |
| Restore latency | `rpc_server_call_duration_seconds` for `atelet.Atelet/Restore`, or `ate_actor_restore_duration_seconds{ate_snapshot_phase="total"}` | The restore histogram is new in v1.0.0 and breaks a restore into phases on the node. Its phases overlap, so use `total` as the denominator. `ate_actor_checkpoint_duration_seconds` is the same for checkpoints. |
| Snapshot activity | `atelet_snapshot_size_bytes` and atelet `Checkpoint` RPCs | `atelet_snapshot_size_bytes` is recorded **once per snapshot image file** written during checkpoint (label `file_name`) — so its `_count` is "snapshot files observed", not completed snapshots. Use successful `atelet.Atelet/Checkpoint` RPCs for operations/sec, and group the size histogram by `file_name`. A default (async) suspend uploads the snapshot to object storage later; `atelet_snapshot_upload_duration_seconds` times that upload. |
| Worker utilization | `ate_workerpool_workers` (labels `ate_workerpool_namespace`, `ate_workerpool_name`, `ate_worker_state`, `ate_sandbox_class`), plus `kubectl ate get workers` and `kubectl top` | New in v1.0.0: live workers per pool by state (`idle`, `partial`, `at_capacity`, `unschedulable`). Every `ate-api-server` replica (two by default) reports the whole fleet, so take `avg` by pool namespace, pool, state, and sandbox class first, then `sum`. |

Because the `rpc_method` values fully disambiguate the sender
(`substrate.ateapi.v1.Control/*` vs `atelet.Atelet/*`), none of the queries in
this lab need `job` filters.

Two related things in the repo that this lab does **not** use:

- `benchmarking/monitoring.yaml` provisions a small Prometheus/Grafana stack,
  but it only scrapes **Locust client metrics** in the `benchmarking`
  namespace — not the Substrate service metrics above. Don't confuse it with
  this lab's stack.
- The **Google Cloud Monitoring** dashboard JSON for the GKE-managed path
  (formerly `tools/setup-gcp/dashboards/`) moved out of the substrate repo with
  the GKE provisioning tooling, to
  [ai-on-gke/substrate-gke](https://github.com/ai-on-gke/substrate-gke). Those
  files cannot be imported into Grafana; this lab provisions its own Grafana
  dashboard instead.

## Prerequisites

You need:

- A Kubernetes cluster with Agent Substrate v1.0.0 and the counter demo
  installed (see the [setup lab](../../install-and-setup/setup-gke.md)).
- `kubectl`, `kubectl-ate`, `helm` (≥ 3.15), Go, `curl`, and `jq` installed.
- `KO_DOCKER_REPO` set to a registry your cluster can pull from, if you still
  need to deploy the counter demo (no demo images are published).
- Cluster capacity for the monitoring stack (roughly 1 CPU / 1.5 GiB across
  Prometheus, Grafana, operator, and exporters).
- `metrics-server` if you want the optional `kubectl top` view.

If the counter demo is not yet deployed (no `ate-demo-counter` namespace on
the cluster), deploy it and install the CLI from the substrate repo root —
this is the same flow as the main [setup lab](../../install-and-setup/setup-gke.md):

```bash
go run ./cmd/ate-setup deploy demo counter
go install ./cmd/kubectl-ate
```

On a **kind** cluster, keep `export ATE_INSTALL_KIND=true` set in the shell so
`ate-setup` targets the local cluster and registry.

Confirm the demo resources exist. The WorkerPool is a Kubernetes object; the
`counter` ActorTemplate lives in the `ate-demo-counter` **atespace** in the
Substrate control plane, so `kubectl get actortemplate` returns nothing:

```bash
kubectl get workerpool -n ate-demo-counter
kubectl ate get actor-templates -a ate-demo-counter
```

The `counter` template's golden snapshot must be ready before continuing:
`GOLDEN TAG` is set and `ERROR` is empty. `deploy demo counter` waits for this
itself.

## Step 1: Deploy Prometheus And Grafana

Install kube-prometheus-stack into a dedicated `monitoring` namespace.
Alertmanager is disabled (unused by this lab), and the two
`*SelectorNilUsesHelmValues=false` settings make Prometheus pick up **any**
`PodMonitor`/`ServiceMonitor` in the cluster rather than only ones labeled
with the Helm release — that's what lets Step 2's plain PodMonitors work:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update prometheus-community

helm upgrade --install monitoring \
  prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --set alertmanager.enabled=false \
  --set prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false
```

Verify the stack is healthy:

```bash
kubectl get pods -n monitoring
```

Expect the operator, `prometheus-monitoring-kube-prometheus-prometheus-0`,
Grafana, kube-state-metrics, and a node-exporter per node, all `Running`.

## Step 2: Scrape Substrate And Envoy

Two `PodMonitor`s cover everything. The first targets the declared port
`9090` on all three Substrate services; the second targets Envoy's metrics port
`9902` at `/stats/prometheus`. (`portNumber` requires the port to be declared
on the container — all four are.)

```bash
kubectl apply -f - <<'EOF'
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: substrate-services
  namespace: monitoring
spec:
  namespaceSelector:
    matchNames: [ate-system]
  selector:
    matchExpressions:
    - key: app
      operator: In
      values: [ate-api-server, atelet, atenet-router]
  podMetricsEndpoints:
  - portNumber: 9090
    path: /metrics
    interval: 15s
---
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: substrate-envoy
  namespace: monitoring
spec:
  namespaceSelector:
    matchNames: [ate-system]
  selector:
    matchLabels:
      app: atenet-router
  podMetricsEndpoints:
  - portNumber: 9902
    path: /stats/prometheus
    interval: 15s
EOF
```

Port-forward Prometheus and confirm the targets are up:

```bash
kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090
```

Open [http://localhost:9090/targets](http://localhost:9090/targets).

Paste the following and you will see calls to Substrate:

```bash
rpc_server_call_duration_seconds_count 
```

## Step 3: Provision The Grafana Dashboard

Grafana's dashboard sidecar (enabled by default in the chart) loads any
ConfigMap labeled `grafana_dashboard: "1"`. Provision the lab dashboard:

```bash
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: substrate-observability-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  substrate-observability.json: |
    {
      "title": "Agent Substrate Observability",
      "uid": "substrate-obs",
      "timezone": "utc",
      "refresh": "30s",
      "time": { "from": "now-30m", "to": "now" },
      "panels": [
        { "type": "row", "title": "Routing", "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0} },
        {
          "type": "timeseries", "title": "Routing latency (wake path) p50 / p95 / p99",
          "gridPos": {"h": 8, "w": 12, "x": 0, "y": 1},
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "fieldConfig": { "defaults": { "unit": "s" }, "overrides": [] },
          "targets": [
            { "refId": "A", "datasource": { "type": "prometheus", "uid": "prometheus" }, "expr": "histogram_quantile(0.50, sum by (le) (rate(atenet_router_route_duration_seconds_bucket{ate_template_atespace=\"ate-demo-counter\", ate_template_name=\"counter\", ate_router_outcome=\"ok\"}[5m])))", "legendFormat": "p50" },
            { "refId": "B", "datasource": { "type": "prometheus", "uid": "prometheus" }, "expr": "histogram_quantile(0.95, sum by (le) (rate(atenet_router_route_duration_seconds_bucket{ate_template_atespace=\"ate-demo-counter\", ate_template_name=\"counter\", ate_router_outcome=\"ok\"}[5m])))", "legendFormat": "p95" },
            { "refId": "C", "datasource": { "type": "prometheus", "uid": "prometheus" }, "expr": "histogram_quantile(0.99, sum by (le) (rate(atenet_router_route_duration_seconds_bucket{ate_template_atespace=\"ate-demo-counter\", ate_template_name=\"counter\", ate_router_outcome=\"ok\"}[5m])))", "legendFormat": "p99" }
          ]
        },
        {
          "type": "timeseries", "title": "Routing outcomes (platform-wide, req/s)",
          "gridPos": {"h": 8, "w": 6, "x": 12, "y": 1},
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "fieldConfig": { "defaults": { "unit": "reqps" }, "overrides": [] },
          "targets": [
            { "refId": "A", "datasource": { "type": "prometheus", "uid": "prometheus" }, "expr": "sum by (ate_router_outcome) (rate(atenet_router_route_duration_seconds_count[5m]))", "legendFormat": "{{ate_router_outcome}}" }
          ]
        },
        {
          "type": "timeseries", "title": "Envoy full request p95 (includes actor time)",
          "gridPos": {"h": 8, "w": 6, "x": 18, "y": 1},
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "fieldConfig": { "defaults": { "unit": "ms" }, "overrides": [] },
          "targets": [
            { "refId": "A", "datasource": { "type": "prometheus", "uid": "prometheus" }, "expr": "histogram_quantile(0.95, sum by (le) (rate(envoy_http_downstream_rq_time_bucket{envoy_http_conn_manager_prefix=~\"ingress_https|main_internal\"}[5m])))", "legendFormat": "p95" }
          ]
        },
        { "type": "row", "title": "Actor Lifecycle", "gridPos": {"h": 1, "w": 24, "x": 0, "y": 9} },
        {
          "type": "timeseries", "title": "Control-plane lifecycle RPCs (ok, ops/s)",
          "gridPos": {"h": 8, "w": 8, "x": 0, "y": 10},
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "fieldConfig": { "defaults": { "unit": "ops" }, "overrides": [] },
          "targets": [
            { "refId": "A", "datasource": { "type": "prometheus", "uid": "prometheus" }, "expr": "sum by (rpc_method) (rate(rpc_server_call_duration_seconds_count{rpc_method=~\"substrate.ateapi.v1.Control/(Create|Resume|Suspend|Delete)Actor\", rpc_response_status_code=\"OK\"}[5m]))", "legendFormat": "{{rpc_method}}" }
          ]
        },
        {
          "type": "timeseries", "title": "Worker restore / checkpoint (ok, ops/s)",
          "gridPos": {"h": 8, "w": 8, "x": 8, "y": 10},
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "fieldConfig": { "defaults": { "unit": "ops" }, "overrides": [] },
          "targets": [
            { "refId": "A", "datasource": { "type": "prometheus", "uid": "prometheus" }, "expr": "sum by (rpc_method) (rate(rpc_server_call_duration_seconds_count{rpc_method=~\"atelet.Atelet/(Restore|Checkpoint)\", rpc_response_status_code=\"OK\"}[5m]))", "legendFormat": "{{rpc_method}}" }
          ]
        },
        {
          "type": "timeseries", "title": "Restore latency p95",
          "gridPos": {"h": 8, "w": 8, "x": 16, "y": 10},
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "fieldConfig": { "defaults": { "unit": "s" }, "overrides": [] },
          "targets": [
            { "refId": "A", "datasource": { "type": "prometheus", "uid": "prometheus" }, "expr": "histogram_quantile(0.95, sum by (le) (rate(rpc_server_call_duration_seconds_bucket{rpc_method=\"atelet.Atelet/Restore\", rpc_response_status_code=\"OK\"}[5m])))", "legendFormat": "p95" }
          ]
        },
        {
          "type": "timeseries", "title": "gRPC non-OK responses (ops/s)",
          "gridPos": {"h": 8, "w": 8, "x": 0, "y": 18},
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "fieldConfig": { "defaults": { "unit": "ops" }, "overrides": [] },
          "targets": [
            { "refId": "A", "datasource": { "type": "prometheus", "uid": "prometheus" }, "expr": "sum by (rpc_method, rpc_response_status_code) (rate(rpc_server_call_duration_seconds_count{rpc_response_status_code!=\"OK\"}[5m]))", "legendFormat": "{{rpc_method}} {{rpc_response_status_code}}" }
          ]
        },
        { "type": "row", "title": "Snapshots", "gridPos": {"h": 1, "w": 24, "x": 0, "y": 26} },
        {
          "type": "timeseries", "title": "Snapshot file size p95 (by file)",
          "gridPos": {"h": 8, "w": 12, "x": 0, "y": 27},
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "fieldConfig": { "defaults": { "unit": "bytes" }, "overrides": [] },
          "targets": [
            { "refId": "A", "datasource": { "type": "prometheus", "uid": "prometheus" }, "expr": "histogram_quantile(0.95, sum by (le, file_name) (rate(atelet_snapshot_size_bytes_bucket{ate_template_atespace=\"ate-demo-counter\", ate_template_name=\"counter\"}[5m])))", "legendFormat": "{{file_name}} p95" }
          ]
        },
        {
          "type": "timeseries", "title": "Checkpoints completed vs snapshot files observed (platform-wide, ops/s)",
          "gridPos": {"h": 8, "w": 12, "x": 12, "y": 27},
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "fieldConfig": { "defaults": { "unit": "ops" }, "overrides": [] },
          "targets": [
            { "refId": "A", "datasource": { "type": "prometheus", "uid": "prometheus" }, "expr": "sum(rate(rpc_server_call_duration_seconds_count{rpc_method=\"atelet.Atelet/Checkpoint\", rpc_response_status_code=\"OK\"}[5m]))", "legendFormat": "checkpoints/s" },
            { "refId": "B", "datasource": { "type": "prometheus", "uid": "prometheus" }, "expr": "sum(rate(atelet_snapshot_size_bytes_count[5m]))", "legendFormat": "snapshot files/s" }
          ]
        },
        { "type": "row", "title": "Workers", "gridPos": {"h": 1, "w": 24, "x": 0, "y": 35} },
        {
          "type": "timeseries", "title": "Counter workers by state",
          "gridPos": {"h": 8, "w": 12, "x": 0, "y": 36},
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "fieldConfig": { "defaults": { "unit": "short" }, "overrides": [] },
          "targets": [
            { "refId": "A", "datasource": { "type": "prometheus", "uid": "prometheus" }, "expr": "sum by (ate_worker_state) (avg by (ate_workerpool_namespace, ate_workerpool_name, ate_worker_state, ate_sandbox_class) (ate_workerpool_workers{ate_workerpool_namespace=\"ate-demo-counter\", ate_workerpool_name=\"counter\"}))", "legendFormat": "{{ate_worker_state}}" }
          ]
        }
      ],
      "schemaVersion": 39
    }
EOF
```

Port-forward Grafana

```bash
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80
```

Open the Grafana dashboard: [http://localhost:3000](http://localhost:3000)

login is (`admin` / the chart-managed password):

```bash
kubectl get secret monitoring-grafana -n monitoring \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

You'll find the **Agent Substrate Observability** dashboard under Grafanas dashboards.

Sidenote: Most panels stay empty until traffic flows, which is Step 5 (the
*Counter workers by state* panel is the exception: it shows the idle pool). In
particular, the percentile panels (routing latency, Envoy p95, restore p95)
show **no line at all** at zero traffic: `histogram_quantile` over a zero
rate returns `NaN`, which Grafana renders as empty. Only the counter-rate
panels draw a flat zero line while idle. Use the dashboard's 30-minute time
range during the run — a 24-hour window compresses the ten-minute load run
into a sliver.

Scoping note — the panels deliberately mix two scopes:

- **Template-scoped to `ate-demo-counter/counter`**: routing latency and
  snapshot file size, so they aggregate the same population as Step 6's
  focused queries and Step 7's client comparison. *Counter workers by state*
  is scoped to the `counter` pool the same way.
- **Platform-wide, on purpose**: *Routing outcomes* — the template labels hold
  `unknown` whenever the router has no template to name, so failures that
  happen before a template is known carry `unknown` instead of
  `ate-demo-counter`/`counter`; scoping this panel would hide exactly the
  failures it exists to show. The *checkpoints vs snapshot files* panel is also fully platform-wide:
  the checkpoint RPC metric carries no template identity, so its files-side
  series is left unscoped too — otherwise unrelated checkpoints would distort
  the apparent files-per-checkpoint ratio. The gRPC panels are platform-wide
  by the same necessity.

## Step 4: Prepare The Observable Workload

This uses the same temporary curl client design as the cost comparison
benchmark, but gives the observability run its own Kubernetes namespace and
atespace.

```bash
export ACTOR_COUNT=20
export OBS_NAMESPACE=observability
export OBS_ATESPACE=observability
export OBS_ACTOR_PREFIX=obs-counter
export TEMPLATE_REF=ate-demo-counter/counter
export WORKER_NAMESPACE=ate-demo-counter
export SUBSTRATE_ROUTER_URL=https://atenet-router.ate-system.svc
export OBS_CLIENT_MANIFEST=observability-benchmark-client.yaml
export OBS_DURATION_SECONDS=600
export OBS_RESULTS_FILE=observability-wake-results.tsv
```

Create the namespace and the client's ServiceAccount:

```bash
kubectl create namespace "$OBS_NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create serviceaccount benchmark-client -n "$OBS_NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f -
```

On v1.0.0, `atenet-router` serves only TLS, requires a client certificate, and
routes on the `ate-target-actor: <atespace>/<actor>` header. The pre-1.0
plain-HTTP port 80 and `Host`-header routing are gone. The client gets a
certificate from a `podCertificate` projected volume, which carries its
ServiceAccount's SPIFFE ID:
`spiffe://cluster.local/ns/observability/sa/benchmark-client`. Add that ID to
the router's allowlist: redeploy atenet from the install record the
[setup lab](../../install-and-setup/setup-gke.md) wrote, with the full list. Each deploy replaces the
allowlist, so keep `atenet-client` in it:

```bash
go run ./cmd/ate-setup deploy atenet \
  --config ~/Library/Caches/ate-setup/installs/<context>.yaml \
  --ingress-allowed-spiffe-ids=spiffe://cluster.local/ns/ate-system/sa/atenet-client,spiffe://cluster.local/ns/${OBS_NAMESPACE}/sa/benchmark-client

kubectl rollout status deployment/atenet-router -n ate-system --timeout=5m
```

Write the client Pod manifest (Step 5 reuses it) and create the Pod:

```bash
cat > "$OBS_CLIENT_MANIFEST" <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: benchmark-client
  namespace: ${OBS_NAMESPACE}
spec:
  serviceAccountName: benchmark-client
  restartPolicy: Never
  containers:
  - name: benchmark-client
    image: curlimages/curl:8.10.1
    command: ["sleep", "86400"]
    volumeMounts:
    - name: router-client
      mountPath: /run/router-client
      readOnly: true
  volumes:
  - name: router-client
    projected:
      sources:
      - podCertificate:
          signerName: podidentity.podcert.ate.dev/identity
          keyType: ECDSAP256
          credentialBundlePath: credential-bundle.pem
      - clusterTrustBundle:
          signerName: servicedns.podcert.ate.dev/identity
          labelSelector:
            matchLabels:
              podcert.ate.dev/canarying: live
          path: router-ca.pem
EOF

kubectl delete pod benchmark-client \
  -n "$OBS_NAMESPACE" \
  --ignore-not-found

kubectl apply -f "$OBS_CLIENT_MANIFEST"

kubectl wait --for=condition=Ready pod/benchmark-client \
  -n "$OBS_NAMESPACE" \
  --timeout=2m
```

> **TODO (v1.0.0):** Not yet run live. `credential-bundle.pem` holds both the
> private key and the certificate chain, so the load script passes it to both
> `--cert` and `--key`. Confirm curl in `curlimages/curl:8.10.1` accepts it
> that way.

Create the atespace if it does not already exist:

```bash
if ! kubectl ate get atespace "$OBS_ATESPACE" >/dev/null 2>&1; then
  kubectl ate create atespace "$OBS_ATESPACE"
fi
```

Create the actors:

```bash
for i in $(seq 1 "$ACTOR_COUNT"); do
  actor=$(printf '%s-%03d' "$OBS_ACTOR_PREFIX" "$i")

  if ! kubectl ate get actor "$actor" \
    --atespace "$OBS_ATESPACE" >/dev/null 2>&1; then
    kubectl ate create actor "$actor" \
      --template "$TEMPLATE_REF" \
      --atespace "$OBS_ATESPACE"
  fi
done
```

Confirm that the actors begin suspended:

```bash
kubectl ate get actors --atespace "$OBS_ATESPACE"
kubectl ate get workers -n "$WORKER_NAMESPACE"
```

Actors show `ACTOR_STATE_SUSPENDED` in the `STATE` column.

## Step 5: Generate Traffic And Watch The Live Views

Keep the **Agent Substrate Observability** Grafana dashboard open with
30-second auto-refresh and a 30-minute window. The panels to narrate during the
run are:

- `Routing latency (wake path) p50 / p95 / p99`
- `Envoy full request p95` — the number a client actually feels
- `Control-plane lifecycle RPCs` and `Worker restore / checkpoint`
- `Checkpoints completed vs snapshot files observed`
- `Counter workers by state`

The load generator below is what populates those panels. Run it from the same
shell where you ran the Step 4 export block so the Bash child inherits the lab
variables.

The client pod runs a finite `sleep`. Recreate it if it is no longer `Running`:

```bash
if [ "$(kubectl get pod benchmark-client -n "$OBS_NAMESPACE" \
    -o jsonpath='{.status.phase}' 2>/dev/null)" != "Running" ]; then
  kubectl delete pod benchmark-client -n "$OBS_NAMESPACE" --ignore-not-found
  kubectl apply -f "$OBS_CLIENT_MANIFEST"
  kubectl wait --for=condition=Ready pod/benchmark-client \
    -n "$OBS_NAMESPACE" --timeout=2m
fi
```

Before starting the load, **optionally** open another shell and run the watcher
below. This shell does not inherit the Step 4 variables, so set the worker
namespace explicitly. Leave the watcher running, then return to the Step 4
shell to start the load generator.

This is occupancy, meaning workers currently hosting at least one actor. It is
distinct from CPU utilization. The `ACTORS` column of `kubectl ate get workers`
is `<allocated>/<capacity>`; the watcher counts workers whose allocated count is
above zero. The *Counter workers by state* panel shows the same thing from
`ate_workerpool_workers` (`idle` vs `partial`/`at_capacity`). Stop the watcher
with `Ctrl-C` after the load run.

```bash
export WORKER_NAMESPACE=ate-demo-counter

while true; do
  clear
  date -u

  workers=$(kubectl ate get workers -n "$WORKER_NAMESPACE")
  printf '%s\n' "$workers"
  printf '%s\n' "$workers" | awk '
    NR > 1 {
      total++
      split($4, a, "/")
      if (a[1] > 0) assigned++
    }
    END {
      if (total > 0) {
        printf "\nworker_occupancy=%d/%d (%.1f%%)\n",
          assigned, total, (assigned / total) * 100
      }
    }'

  printf '\nWorker pod resources:\n'
  kubectl top pods -n "$WORKER_NAMESPACE" 2>/dev/null || true
  sleep 2
done
```

Run the load as one Bash heredoc. Each actor is verified as suspended before
and after its request, so every numeric sample represents a suspended wake. A
failed request is recorded as `FAILED`; because the router's resume runs
detached from the caller (it keeps retrying for up to `--parked-request-budget`,
5 seconds by default, or 15 seconds with request parking off, and an attempt
already in flight runs to completion), the script waits out that detached
operation before suspending the actor.

```bash
bash <<'BASH'
# Do not enable `set -e`: expected command failures are handled explicitly.
set -u

: "${OBS_RESULTS_FILE:?run the Step 4 export block first}"
: "${OBS_DURATION_SECONDS:?run the Step 4 export block first}"
: "${ACTOR_COUNT:?run the Step 4 export block first}"
: "${OBS_ACTOR_PREFIX:?run the Step 4 export block first}"
: "${OBS_ATESPACE:?run the Step 4 export block first}"
: "${OBS_NAMESPACE:?run the Step 4 export block first}"
: "${SUBSTRATE_ROUTER_URL:?run the Step 4 export block first}"

get_actor_status() {
  kubectl ate get actor "$1" --atespace "$OBS_ATESPACE" 2>/dev/null |
    awk 'NR == 2 { print $4 }'
}

ensure_suspended() {
  local actor=$1
  local actor_status
  local attempt

  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    actor_status=$(get_actor_status "$actor")
    if [ "$actor_status" = "ACTOR_STATE_SUSPENDED" ]; then
      return 0
    fi
    if [ "$actor_status" = "ACTOR_STATE_CRASHED" ]; then
      printf 'ERROR: %s is CRASHED and cannot be measured\n' "$actor" >&2
      return 1
    fi

    kubectl ate suspend actor "$actor" \
      --atespace "$OBS_ATESPACE" >/dev/null 2>&1 || true
    sleep 3
  done

  actor_status=$(get_actor_status "$actor")
  printf 'ERROR: %s did not reach ACTOR_STATE_SUSPENDED (status=%s)\n' \
    "$actor" "${actor_status:-unknown}" >&2
  return 1
}

printf 'round\tactor\twake_seconds\n' > "$OBS_RESULTS_FILE"

deadline=$((SECONDS + OBS_DURATION_SECONDS))
round=0
successful_wakes=0
failed_wakes=0

while (( SECONDS < deadline )); do
  round=$((round + 1))

  for i in $(seq 1 "$ACTOR_COUNT"); do
    if (( SECONDS >= deadline )); then
      break
    fi

    actor=$(printf '%s-%03d' "$OBS_ACTOR_PREFIX" "$i")
    target="${OBS_ATESPACE}/${actor}"

    if ! ensure_suspended "$actor"; then
      exit 1
    fi

    if wake_seconds=$(kubectl exec \
      -n "$OBS_NAMESPACE" benchmark-client -- \
      curl -sS --fail-with-body --max-time 60 -o /dev/null -w '%{time_total}' \
      --cacert /run/router-client/router-ca.pem \
      --cert /run/router-client/credential-bundle.pem \
      --key /run/router-client/credential-bundle.pem \
      -X POST \
      -H "ate-target-actor: ${target}" \
      "$SUBSTRATE_ROUTER_URL"); then
      printf '%s\t%s\t%s\n' \
        "$round" "$actor" "$wake_seconds" | tee -a "$OBS_RESULTS_FILE"
      successful_wakes=$((successful_wakes + 1))
    else
      printf '%s\t%s\tFAILED\n' \
        "$round" "$actor" | tee -a "$OBS_RESULTS_FILE"
      failed_wakes=$((failed_wakes + 1))
      sleep 16
    fi

    if ! ensure_suspended "$actor"; then
      printf 'Aborting to prevent a warm request from entering the wake results.\n' >&2
      exit 1
    fi
  done
done

printf 'successful_wakes=%d\nfailed_wakes=%d\n' \
  "$successful_wakes" "$failed_wakes"
BASH
```

Each successful cycle should produce:

- One routed request and one `ResumeActor` RPC.
- One atelet `Restore` when the actor was actually suspended.
- One explicit `SuspendActor` RPC.
- One atelet `Checkpoint` when suspension writes a snapshot.

The exact RPC counts can differ because the metrics count RPC attempts and the
control plane may retry or handle an operation idempotently. If every worker is
busy, the router parks the request and retries the resume instead of failing
it, so a saturated pool shows up as longer wake times before it shows up as
`no_capacity` outcomes.

## Step 6: Query The Same Signals Directly

Grafana is the presentation layer; PromQL is the source of truth. Right after
the load run finishes, query the Prometheus port-forward from Step 2
(`localhost:9090`) once over the whole run. These are the numbers for the
[results template](#results-template).

Every query here is scoped to the `ate-demo-counter/counter` template, like the
dashboard's routing panels. The `ate_template_*` labels name the
**template's** atespace, so they match this lab's actors even though the
actors live in the `observability` atespace. Any other traffic to counter
actors during the window, such as the counter demo's own actors, is counted
too.

Set the window to cover the run, and a small helper that prints each series'
labels and value:

```bash
export OBS_WINDOW="$(( OBS_DURATION_SECONDS / 60 + 2 ))m"

prom() {
  curl -sG http://localhost:9090/api/v1/query --data-urlencode "query=$1" \
    | jq -r '.data.result[] | "\(.metric | to_entries | map(.value) | join(" "))\t\(.value[1])"'
}
```

Router wake-path p95, in seconds. Only `ate_router_resume="triggered"`
requests are cold activations. The dashboard panel mixes them with warm
(`none`) routes, which the metric registry warns against, so this figure is
the cleaner one:

```bash
prom "histogram_quantile(0.95, sum by (le) (increase(atenet_router_route_duration_seconds_bucket{ate_template_atespace=\"ate-demo-counter\", ate_template_name=\"counter\", ate_router_outcome=\"ok\", ate_router_resume=\"triggered\"}[${OBS_WINDOW}])))"
```

How the routed requests split. Expect almost all of them under `ok triggered`.
`joined` means a request waited on another request's resume, and anything
other than `ok` is a failure the load script recorded as `FAILED`:

```bash
prom "round(sum by (ate_router_outcome, ate_router_resume) (increase(atenet_router_route_duration_seconds_count{ate_template_atespace=\"ate-demo-counter\", ate_template_name=\"counter\"}[${OBS_WINDOW}])))"
```

Restore p95 on the node, in seconds. This is the template-scoped counterpart
of the dashboard's platform-wide *Restore latency* panel. Use the `total`
phase; the other phases overlap and don't add up to it:

```bash
prom "histogram_quantile(0.95, sum by (le) (increase(ate_actor_restore_duration_seconds_bucket{ate_template_atespace=\"ate-demo-counter\", ate_template_name=\"counter\", ate_snapshot_phase=\"total\"}[${OBS_WINDOW}])))"
```

Envoy full-request p95, in **milliseconds**. This metric has no template label,
so it's platform-wide:

```bash
prom "histogram_quantile(0.95, sum by (le) (increase(envoy_http_downstream_rq_time_bucket{envoy_http_conn_manager_prefix=~\"ingress_https|main_internal\"}[${OBS_WINDOW}])))"
```

Successful lifecycle RPCs during the run. `increase` extrapolates to the
window edges, so the counts are rounded and can be off by one or two:

```bash
prom "round(sum by (rpc_method) (increase(rpc_server_call_duration_seconds_count{rpc_method=~\"substrate.ateapi.v1.Control/(Resume|Suspend)Actor|atelet.Atelet/(Restore|Checkpoint)\", rpc_response_status_code=\"OK\"}[${OBS_WINDOW}])))"
```

Expect `ResumeActor`, `Restore`, `SuspendActor` and `Checkpoint` to be close to
the script's `successful_wakes`. Step 5 explains why they don't have to match
exactly.

Peak busy workers against the pool size. Busy means `partial` or
`at_capacity`; `avg` removes the duplicate from the second `ate-api-server`
replica:

```bash
prom "max_over_time(sum(avg by (ate_workerpool_namespace, ate_workerpool_name, ate_worker_state, ate_sandbox_class) (ate_workerpool_workers{ate_workerpool_namespace=\"ate-demo-counter\", ate_workerpool_name=\"counter\", ate_worker_state=~\"partial|at_capacity\"}))[${OBS_WINDOW}:30s])"
prom "max_over_time(sum(avg by (ate_workerpool_namespace, ate_workerpool_name, ate_worker_state, ate_sandbox_class) (ate_workerpool_workers{ate_workerpool_namespace=\"ate-demo-counter\", ate_workerpool_name=\"counter\"}))[${OBS_WINDOW}:30s])"
```

The load script wakes one actor at a time, so expect a peak of 1 busy worker
unless other traffic shared the pool. For peak worker CPU and memory, use what
the Step 5 watcher showed from `kubectl top`.

## Step 7: Compare The Client With The Dashboard

`OBS_RESULTS_FILE` holds the wake time `curl` measured inside the client pod
for every successful request. Compute the same percentiles from it:

```bash
awk -F'\t' 'NR > 1 && $3 != "FAILED" { print $3 }' "$OBS_RESULTS_FILE" \
  | sort -n \
  | awk '
    { v[NR] = $1 }
    function pct(p,   i) { i = int(p * NR); if (i < p * NR) i++; return v[i] }
    END {
      if (NR == 0) { print "no successful wakes"; exit 1 }
      printf "samples=%d client_p50=%.3fs client_p95=%.3fs client_max=%.3fs\n",
        NR, pct(0.50), pct(0.95), v[NR]
    }'
```

Each number measures a shorter piece of the same request, so expect them to
nest:

```text
client wake p95  >  Envoy full-request p95  >  router wake-path p95  >  restore p95
```

- **Client wake** is `curl`'s `time_total`. It includes a fresh TCP and mTLS
  handshake to the router on every request, then everything below.
- **Envoy full request** starts when Envoy has the request and ends when the
  response is sent, so it skips the client's handshake but includes the
  actor's work and the response.
- **Router wake path** stops once the router has a worker endpoint, so it
  covers `ResumeActor`, which includes the restore, but not the actor's
  work.
- **Restore** is only atelet's part of the resume on the node.

The gaps tell you where the time goes. A large gap between client and Envoy
points at connection setup; one between Envoy and the router points at the
actor's own handling time; one between the router and restore is control-plane
scheduling and assignment.

Don't expect the client and Prometheus to match to the millisecond.
Prometheus estimates a quantile by interpolating inside the histogram bucket
it falls in, and the router's buckets are wide at the top (`2.5`, `5`, `10`,
`15`, `30` seconds). A client p95 of 3.2s and a router p95 of 3.6s can both
be correct. A real disagreement looks like a router p95 *above* the client p95
by more than a bucket, which usually means the window also caught traffic
other than this run.

## Optional: Actor-Emitted Telemetry And Traces

Everything above observes the Substrate **platform**. Two extensions are out
of scope for this lab but worth knowing:

- **Application metrics/traces emitted inside actors.** Deploy an
  OpenTelemetry Collector as a stable Service, and configure actor workloads
  (via their ActorTemplate) to export OTLP to it. Actors have no network path
  by default: the actor needs an `EgressPolicy` with an `http` rule for the
  collector's hostname and port, or its DNS lookups for the collector return
  `NXDOMAIN`. One critical caveat: actor identity must come from files, not
  the environment. On v1.0.0 the template declares a `systemInfo` volume with
  an `actorMetadata` data source, which projects
  `ACTOR_METADATA_FIELD_NAME`, `ACTOR_METADATA_FIELD_ATESPACE`, and
  `ACTOR_METADATA_FIELD_UID` to files (for example `/run/ate/actor-name`) on a
  read-only per-actor bind mount. That gives the `(atespace, name)` pair that
  globally useful telemetry identity needs, plus the uid. This replaces the
  pre-1.0 `/run/ate/actor-id` file, which held only the name. Never take identity from an
  environment variable like
  `OTEL_RESOURCE_ATTRIBUTES=actor.id=...`. Env vars are resolved before the
  golden snapshot and frozen into checkpointed memory, so every restored actor
  would report the *golden* actor's identity. Note that this cuts against
  standard OTel usage: SDKs normally initialize resource attributes **once at
  startup**, which is exactly the state a snapshot freezes. A correct
  implementation needs migration-aware enrichment **inside the sandbox** —
  re-read the file per emission, or rebuild the tracer/meter providers after
  each resume. Collector-side stamping is not a shortcut: a centralized
  collector cannot see the actor's metadata files, and the actor's connection
  reaches it from the egress gateway pod, not the worker, so it can only attach identity the
  workload already sent, or resolve the sending worker's IP to an actor via
  the control plane at ingest time — a lookup that is racy across
  suspend/resume precisely because workers are reused by different actors.
- **Platform traces.** Substrate's own traces are OTLP-push only (there is no
  Prometheus equivalent for traces). Capturing them self-hosted requires an
  OTel Collector plus a trace backend (Jaeger or Tempo) — and the senders are
  configured in **three different places**:
  - the Go services (`ate-api-server`, `atelet`, `ate-controller`,
    `atenet-router`, `atenet-egress`) read `OTEL_EXPORTER_OTLP_ENDPOINT` from
    the shared `ate-otel-config` ConfigMap in `ate-system` (restart them after
    editing it);
  - **Envoy's** spans are configured separately through the router's
    `--otlp-collector-address` flag, which defaults to
    `$OTEL_EXPORTER_OTLP_ENDPOINT`
    (`manifests/ate-install/atenet-router.yaml`) — the router provisions
    Envoy's tracer via xDS;
  - **ateworker pods** do not read the ConfigMap. They export logs, traces,
    and metrics over a unix socket to the **atelet OTLP relay**, which
    forwards them to atelet's own endpoint. If the relay socket is missing at
    startup, they fall back to the endpoint `ate-controller` copied into the
    worker pod.

  The `kubectl ate ... --trace` flag emits the trace ID to correlate against
  whichever backend receives the spans.

Worker occupancy now has a gauge (`ate_workerpool_workers`, used in the
*Counter workers by state* panel). Still not on metrics in v1.0.0: actor-state
counts and per-actor labels. Both are kept off metrics by design, because actor
identity is barred from metric labels. Actor state and identity travel on logs
instead (`Actor state changed` and `Actor usage sampled` records from ateapi
and the ateworkers) and on traces.

## Results Template

Fill this in from Step 6 and Step 7, and from the Step 5 watcher for worker
CPU and memory.

| Observation | Value |
|---|---:|
| Client wake p95 | `<seconds>` |
| Router wake-path p95 | `<seconds>` |
| Atelet Restore p95 | `<seconds>` |
| Envoy full-request p95 | `<milliseconds>` |
| Successful ResumeActor RPCs | `<count>` |
| Successful Restore RPCs | `<count>` |
| Successful SuspendActor RPCs | `<count>` |
| Successful Checkpoint RPCs | `<count>` |
| Peak assigned workers | `<assigned>/<total>` |
| Peak worker CPU/memory | `<kubectl top observation>` |

The useful demo-day story is the correlation across views: request traffic
rises, suspended actors restore, workers become assigned, full-request latency
shows the cold-start cost, checkpoints appear after suspension, and workers
return to `idle` (`0/<capacity>` in the `ACTORS` column) without deleting the
logical actors.

## Cleanup

> **Ownership warning.** Cleanup deletes the lab's resources
> **unconditionally**: the `obs-counter-*` actors, the `observability`
> atespace and namespace, and (optionally) the `monitoring` Helm release and
> namespace. These names are treated as lab-owned — do not point the lab at
> pre-existing resources under the same names on a shared cluster, or cleanup
> will remove them.

Delete the actors created by this lab. `delete actor` terminates a running
actor's workloads, so no suspend is needed first. The loop tolerates per-actor
failure so one bad actor doesn't block cleanup of the rest:

```bash
for i in $(seq 1 "$ACTOR_COUNT"); do
  actor=$(printf '%s-%03d' "$OBS_ACTOR_PREFIX" "$i")
  kubectl ate delete actor "$actor" \
    --atespace "$OBS_ATESPACE" || true
done

kubectl ate get actors --atespace "$OBS_ATESPACE"
kubectl ate delete atespace "$OBS_ATESPACE"
kubectl delete namespace "$OBS_NAMESPACE"
rm -f "$OBS_RESULTS_FILE" "$OBS_CLIENT_MANIFEST"
```

Optionally drop `spiffe://cluster.local/ns/observability/sa/benchmark-client`
from `--ingress-allowed-spiffe-ids` by re-running the same `deploy atenet --config ...` command
without it.

Remove the monitoring stack if you are done with it (the PodMonitors and
dashboard ConfigMap live in the `monitoring` namespace, so they go with it):

```bash
helm uninstall monitoring -n monitoring
kubectl delete namespace monitoring
```

## Troubleshooting

- **PodMonitor targets missing from Status > Targets**: confirm the two
  `*SelectorNilUsesHelmValues=false` Helm values from Step 1 — without them
  Prometheus only selects release-labeled monitors. Then check
  `kubectl get podmonitor -n monitoring`.
- **Targets shown but DOWN**: the Substrate pods must be Running in
  `ate-system`; `portNumber` only works for ports declared on the container
  (9090 and 9902 are declared by the stock manifests — a fork that removed
  them would need `targetPort`-era manifests updated). A PodMonitor still on
  the pre-1.0 Envoy port `9901` shows DOWN: that admin port is loopback-only on
  v1.0.0.
- **PodMonitor rejected with an unknown-field error for `portNumber`**: the
  cluster carries prometheus-operator CRDs older than this chart — `helm
  upgrade` does **not** upgrade pre-existing CRDs. Update them from the
  chart's `charts/crds/` (or a matching prometheus-operator release) before
  re-applying.
- **`atenet_router_route_duration_seconds` returns no series**: no request
  has passed through the router since it started. OTel instruments export
  only after first use — send one actor request and re-query.
- **Envoy p95 looks absurdly low or flat**: you forgot the
  `envoy_http_conn_manager_prefix=~"ingress_https|main_internal"` filter and
  are measuring the `admin_metrics` listener serving Prometheus scrapes. A
  pre-1.0 query on `ingress_http` (no `s`) returns nothing on v1.0.0.
- **Every load request fails with a TLS or handshake error**: the client's
  SPIFFE ID (`spiffe://cluster.local/ns/observability/sa/benchmark-client`)
  is not on `--ingress-allowed-spiffe-ids`, or the router has not rolled out
  since you added it. With an empty allowlist the router serves no listener
  at all.
- **Workers-by-state counts look doubled**: a plain `sum` over
  `ate_workerpool_workers` counts each worker once per `ate-api-server`
  replica. Take `avg` by pool namespace, pool, state, and sandbox class first,
  as the dashboard does.
- **Dashboard missing in Grafana**: the sidecar needs the
  `grafana_dashboard: "1"` label on the ConfigMap and up to a minute to sync;
  check `kubectl logs -n monitoring deploy/monitoring-grafana -c grafana-sc-dashboard`.
- **Lifecycle counts do not equal curl samples**: RPC metrics count attempts.
  Retries, idempotent resume calls, failures, and scrape timing can all create
  differences. Compare `Restore` with actual wakes and group by
  `rpc_response_status_code` when investigating.
- **Worker occupancy is always zero**: sequential counter requests can complete
  between two-second samples. Reduce the watcher sleep interval for a more
  granular view.
- **`kubectl top` fails**: `metrics-server` is missing or not ready. Worker
  assignment, Prometheus metrics, and dashboard steps still work.

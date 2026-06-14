# Installing vLLM Semantic Router on AKS

This guide captures the exact steps that produced a working deployment on a working cluster to get vLLM Semantic Routing up and running.

## Prerequisites

- A node pool with sufficient headroom. Default dev nodes (`Standard_A2_v2`, ~2 vCPU / 4 Gi) are too small. The chart defaults request 1–2 CPU and 3–7 Gi (CPU-based BERT/ModernBERT + mmbert classifiers + embedding models). Use at least `Standard_D8as_v5` (8 vCPU / 32 Gi) or equivalent.
- Your v0.3 runtime configuration (example: `.vllm-sr/runtime-config.yaml` from a local `vllm-sr` run). It must start with `version: v0.3`, `listeners:`, `providers:`, `routing:`, `global:`, etc.

## Step 1: Add a Capable Node Pool (if you only have tiny nodes)

```bash
az aks nodepool add \
  --resource-group devrelasaservice \
  --cluster-name aksenvironment01 \
  --name srpool \
  --node-vm-size Standard_D8as_v5 \
  --node-count 1 \
  --min-count 1 \
  --max-count 2 \
  --enable-cluster-autoscaler \
  --labels purpose=semantic-router
```

Wait for the node to be Ready:

```bash
kubectl get nodes -l purpose=semantic-router -w
```

## Step 2: Create the "standard" StorageClass (AKS often lacks it)

The chart creates a `semantic-router-models` PVC requesting `storageClassName: standard` (10 Gi, RWO) for classifier/embedding models.

Create an alias if it does not exist:

```bash
cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: standard
provisioner: disk.csi.azure.com
parameters:
  skuName: StandardSSD_LRS
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
EOF
```

## Step 3: Install with the official OCI chart (inline with --set flags)

The published chart expects a `config:` key (as a map) that it renders into the `ConfigMap` as `config.yaml`. Older chart examples used a pre-v0.3 structure that the current `extproc` image rejects with:

> "config file must use canonical v0.3 version/listeners/providers/routing/global"

Instead of creating a separate values file, pass the overrides directly on the command line using `--set` (for scalar settings like service type and resources) and `--set-file` (to inject the entire contents of your v0.3 `runtime-config.yaml` as the `config` value).

```bash
helm upgrade --install semantic-router \
  oci://ghcr.io/vllm-project/charts/semantic-router \
  --version v0.0.0-latest \
  --namespace vllm-semantic-router-system \
  --create-namespace \
  --set service.type=LoadBalancer \
  --set resources.requests.cpu=500m \
  --set resources.requests.memory=1.5Gi \
  --set resources.limits.cpu=2 \
  --set resources.limits.memory=7Gi \
  --set-file config=.vllm-sr/runtime-config.yaml \
  --wait --timeout=10m
```

(The `--set-file config=...` supplies your full runtime config (listeners, providers for Anthropic/Claude, routing decisions, mmbert classifiers, semantic cache settings, etc.) directly. The chart renders it into the mounted `config.yaml` inside the pod.)

If your version of the chart's templates strictly require a parsed map for `config` and `--set-file` produces a string (causing a "wrong type" error during template rendering), you can fall back to a one-liner with process substitution instead of a persistent file:

```bash
helm upgrade --install semantic-router \
  oci://ghcr.io/vllm-project/charts/semantic-router \
  --version v0.0.0-latest \
  --namespace vllm-semantic-router-system \
  --create-namespace \
  --set service.type=LoadBalancer \
  --set resources.requests.cpu=500m \
  --set resources.requests.memory=1.5Gi \
  --set resources.limits.cpu=2 \
  --set resources.limits.memory=7Gi \
  -f <(cat <<'EOV'
config:
EOV
sed 's/^/  /' .vllm-sr/runtime-config.yaml) \
  --wait --timeout=10m
```

This deploys:
- `semantic-router` Deployment (the `extproc` / classification router)
- `semantic-router-models` PVC (models are downloaded on first start)
- `semantic-router-config` ConfigMap (your v0.3 config)
- LoadBalancer Services for the classify API (8080), gRPC/ext_proc (50051), and metrics (9190)
- RBAC (ClusterRole + Binding) for the controller bits

## Step 5: Verify

```bash
kubectl get nodes -o wide
kubectl get all,pvc -n vllm-semantic-router-system -o wide
```

The pod must be on a large node (not the default tiny pool) and `1/1 Running`.

Wait for the LoadBalancer external IP (can take 1–2 minutes):

```bash
kubectl get svc -n vllm-semantic-router-system -w
export SR_IP=$(kubectl get svc -n vllm-semantic-router-system semantic-router \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "Main endpoint: http://$SR_IP:8080"
```

Test:

```bash
curl -s http://$SR_IP:8080/health

curl -X POST http://$SR_IP:8080/api/v1/classify/intent \
  -H "Content-Type: application/json" \
  -d '{"text":"Explain quantum computing"}'
```

## Running the vLLM Semantic Router Dashboard Locally Against the Cluster

The Helm chart ships only the router (gRPC `50051`, classify-api `8080`, metrics `9190`). The Web UI ("dashboard") is a separate Go backend + React frontend that lives in the upstream repo at `dashboard/`. To use it against the in-cluster router, port-forward the router APIs and run the dashboard binary locally pointed at them.

Verified on `aksenvironment01` against the `semantic-router` Helm release in `vllm-semantic-router-system`.

### Prerequisites

- The upstream repo cloned at `agentic-demo-repo/vllm/semantic-router`
- `node` (v18+) and `go` (1.22+) on the local machine
- `kubectl` context pointing at the cluster where `semantic-router` is installed

### 1. Port-forward the in-cluster router

```bash
kubectl port-forward -n vllm-semantic-router-system svc/semantic-router 8080:8080 &
kubectl port-forward -n vllm-semantic-router-system svc/semantic-router-metrics 9190:9190 &

# Sanity check
curl -s -o /dev/null -w "router api => %{http_code}\n" http://localhost:8080/health
curl -s -o /dev/null -w "router metrics => %{http_code}\n" http://localhost:9190/metrics
```

Both should return `200`.

### 2. Build the dashboard frontend

```bash
cd agentic-demo-repo/vllm/semantic-router/dashboard/frontend
npm install
npx vite build
```

Note: `npm run build` runs `tsc && vite build`. The upstream tree currently has one TypeScript type error in `src/components/chatStreamingFrameSync.ts` (`Timeout` vs `number`) that breaks the `tsc` step. Calling `vite build` directly skips type-checking and produces a working `dist/`.

### 3. Build the dashboard backend

```bash
cd ../backend
go build -o vsr-dashboard .
```

### 4. Run the dashboard pointed at the port-forwards

```bash
cd agentic-demo-repo/vllm/semantic-router/dashboard/backend

DASHBOARD_PORT=8700 \
TARGET_ROUTER_API_URL=http://localhost:8080 \
TARGET_ROUTER_METRICS_URL=http://localhost:9190/metrics \
DASHBOARD_STATIC_DIR=../frontend/dist \
./vsr-dashboard
```

Expected log lines on startup:

```
Semantic Router Dashboard listening on :8700
Router API: http://localhost:8080 → /api/router/*
Router Metrics: http://localhost:9190/metrics → /metrics/router
```

Open `http://localhost:8700/` in a browser. The Landing, Config, and Topology tabs render against the in-cluster router immediately.

### Optional targets

The dashboard supports additional reverse-proxy targets. Leave them unset and those tabs are just inert:

- `TARGET_GRAFANA_URL` — Grafana for the Monitoring iframe (`http://localhost:3000` if you port-forward a Grafana service)
- `TARGET_PROMETHEUS_URL` — Prometheus for link-outs and metric queries
- `TARGET_ENVOY_URL` — Envoy proxy for the Playground chat tab (Helm chart does not deploy Envoy)

### Caveats specific to the in-cluster install

- **No Grafana/Prometheus is deployed** by the `semantic-router` Helm chart. The Monitoring tab will be blank unless you install kube-prometheus-stack (or any Prometheus + Grafana) and port-forward Grafana to `:3000`.
- **No Envoy front-proxy** is deployed. The Playground chat tab will not produce completions until Envoy is added in front of the router.
- **Config writes won't persist.** The router config is mounted from the `semantic-router-config` ConfigMap and is read-only inside the pod. `POST /api/router/config/update` calls from the dashboard will fail. Read-only views (Config, Topology) work fine.
- `/api/router/config/all` returns `401` until you sign in to the dashboard — that is the expected protected-endpoint behavior, not a wiring issue.

### Teardown

```bash
# Stop the dashboard
pkill -f vsr-dashboard

# Stop the port-forwards
pkill -f "port-forward.*semantic-router"

## References

- Official chart: `oci://ghcr.io/vllm-project/charts/semantic-router`
- Upstream docs & CLI: https://vllm-semantic-router.com
- GitHub: https://github.com/vllm-project/semantic-router
- Example runtime config source: the `.vllm-sr/` directory produced by a local `vllm-sr serve` run.
```
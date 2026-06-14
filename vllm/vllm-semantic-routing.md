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


## References

- Official chart: `oci://ghcr.io/vllm-project/charts/semantic-router`
- Upstream docs & CLI: https://vllm-semantic-router.com
- GitHub: https://github.com/vllm-project/semantic-router
- Example runtime config source: the `.vllm-sr/` directory produced by a local `vllm-sr serve` run.
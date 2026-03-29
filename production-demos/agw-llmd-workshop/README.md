# agentgateway + llm-d Workshop: Intelligent Inference Routing on Kubernetes

This workshop deploys the full Kubernetes-native inference routing stack: a kagent AI agent sends requests through agentgateway, which routes them via an InferencePool to the llm-d Endpoint Picker (EPP), which makes intelligent, KV-cache-aware routing decisions to select the optimal vLLM pod.

## What You Will Learn

- How agentgateway implements the Gateway API for AI inference workloads
- How the Gateway API Inference Extension (InferencePool + InferenceObjective) provides model-aware routing
- How llm-d's Endpoint Picker makes cache-aware, queue-depth-aware scheduling decisions
- How kagent agents route LLM calls through infrastructure-level gateways
- How to observe and debug inference routing decisions in real-time

## Architecture

```
┌──────────────────────────┐
│  kagent Agent            │  Agent CRD + ModelConfig
│  (kagent namespace)      │  provider: OpenAI, baseUrl → gateway service
└────────────┬─────────────┘
             │ HTTP (OpenAI-compatible /v1/chat/completions)
             ▼
┌──────────────────────────┐
│  agentgateway            │  Gateway resource (gatewayClassName: agentgateway)
│  (llmd-workshop ns)      │  Listener port 80
└────────────┬─────────────┘
             │ HTTPRoute: path prefix "/"
             ▼
┌──────────────────────────┐
│  InferenceObjective      │  Maps workload to llmd-pool with priority
│  InferencePool           │  Selects pods: app=llmd-model-server
│  "llmd-pool"             │
└────────────┬─────────────┘
             │ ext-proc (gRPC) — Envoy external processing
             ▼
┌──────────────────────────┐
│  llm-d EPP               │  Endpoint Picker — the routing brain
│  (Endpoint Picker)       │  Scores endpoints by:
│                          │    • Prefix-cache hits (KV cache affinity)
│                          │    • Queue depth per pod
│                          │    • Request criticality
└───────┬──────────┬───────┘
        │          │
        ▼          ▼
┌──────────┐ ┌──────────┐
│  vllm-0  │ │  vllm-1  │   2 replicas of vLLM CPU
│  :8000   │ │  :8000   │   Qwen/Qwen2.5-0.5B-Instruct
└──────────┘ └──────────┘
```

### How the Layers Connect

| Layer | Component | Role |
|-------|-----------|------|
| **Agent** | kagent Agent + ModelConfig | Sends LLM requests using OpenAI-compatible API |
| **Gateway** | agentgateway (Gateway resource) | External entry point, TLS termination, routing |
| **Route** | HTTPRoute | Matches request paths and forwards to InferencePool |
| **Pool** | InferencePool + InferenceObjective | Abstracts model servers, delegates to EPP for scheduling |
| **Scheduler** | llm-d EPP (Endpoint Picker) | Intelligent endpoint selection via Envoy ext-proc |
| **Inference** | vLLM pods | Run the actual model, serve OpenAI-compatible API |

### Why Not Just Use a Regular Service Instead Of LLM-D?

A Kubernetes Service does round-robin load balancing — it has no awareness of:
- Which pod already has the KV cache for a given prompt prefix
- How many requests are queued at each pod
- Whether a request is interactive (latency-sensitive) or batch (throughput-optimized)

The llm-d EPP solves all of these by acting as an intelligent scheduler between the gateway and the model servers.

## Prerequisites

- **Kubernetes cluster**: v1.33+ with at least 10 vCPUs and 18Gi memory available (for 2 vLLM CPU replicas at 4 CPU / 8Gi each)
- **kubectl**: Configured with cluster access
- **Helm**: v3.x
- **jq**: For parsing JSON responses in test scripts
- **No GPU required**: This workshop uses CPU-optimized vLLM images

> **Cluster sizing tip**: If you see `Insufficient cpu` or `Insufficient memory` events on the vLLM pods, your nodes don't have enough resources. Each vLLM replica needs 4 CPU and 8Gi memory.

## Step 1: Install Gateway API CRDs

The Gateway API is the Kubernetes standard for traffic routing. agentgateway implements this specification.

```bash
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.0/experimental-install.yaml

# For `HTTPRoute`
kubectl apply --server-side -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.0/standard-install.yaml
```

## Step 2: Install Inference Extension CRDs

The Gateway API Inference Extension adds `InferencePool` and `InferenceObjective` CRDs that enable model-aware routing through any Gateway API implementation.

```bash
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v1.1.0/manifests.yaml
```

## Step 3: Install agentgateway

Install the agentgateway CRDs and controller with Inference Extension support enabled.

```bash
helm upgrade -i --create-namespace \
  --namespace agentgateway-system \
  --version v1.0.1 agentgateway-crds oci://cr.agentgateway.dev/charts/agentgateway-crds
```

```bash
helm upgrade -i -n agentgateway-system agentgateway oci://cr.agentgateway.dev/charts/agentgateway \
--version v1.0.1 \
--set inferenceExtension.enabled=true
```

Verify the controller is running:

```bash
kubectl get pods -n agentgateway-system
```

> The `--set inferenceExtension.enabled=true` flag is critical — it tells the agentgateway controller to handle InferencePool backends in HTTPRoutes by integrating with the EPP via Envoy ext-proc.

## Step 4: Install kagent

kagent is the agent framework that will act as the top-of-stack client in this demo. Even though we're running the Qwen model locally, we still need to set `providers.anthropic.apiKey`, so you can just use `dummykey` as the value.

```bash
export ANTHROPIC_API_KEY=dummykey
```

```bash
helm upgrade --install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
    --version 0.8.0-beta9 \
    --namespace kagent \
    --create-namespace
```

```bash
helm upgrade --install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
    --namespace kagent \
    --version 0.8.0-beta9 \
    --set providers.default=anthropic \
    --set providers.anthropic.apiKey=$ANTHROPIC_API_KEY \
    --set ui.service.type=LoadBalancer
```

Verify kagent is running:

```bash
kubectl get pods -n kagent
```

Get the kagent UI address (you'll use this later):

```bash
kubectl get svc -n kagent
```

## Step 5: Create the Workshop Namespace

```
cd production-demos/agw-llmd-workshop
```

```bash
kubectl apply -f manifests/00-namespace.yaml
```

## Step 6: Deploy vLLM Model Servers

Deploy the vLLM Deployment with 2 replicas.

vLLM is what loads the model into an InferencePool. If a vLLM wasn't used, the model wouldn't be able to be loaded into the InferencePool, even if the model was running as a deployment on the cluster. Without it, there would be no "pool of models/resources" available for your Agent, metrics, or API endpoint to receive and handle the inference requests, which would mean the request wouldn't be routed to the pool of Models in the InferencePool.

```bash
kubectl apply -f manifests/01-model-server.yaml
```

Wait for the pods to be ready (this takes 2-3 minutes as the model downloads):

```bash
kubectl get pods -n llmd-workshop -w
```

> Both pods should reach `Running` with `1/1` ready containers. If they stay in `Pending`, check node resources with `kubectl describe pod -n llmd-workshop`.

## Step 7: Deploy InferencePool + EPP

The InferencePool is deployed as a **Helm chart**, not a standalone YAML manifest. This is because the chart bundles two tightly coupled resources:

1. **An InferencePool CRD instance** — the resource that selects model server pods by label and defines the extension reference to the EPP
2. **An EPP (Endpoint Picker) Deployment + Service** — the pod that runs the intelligent routing logic (prefix-cache scoring, queue-depth awareness, endpoint selection)

Both are created together because the InferencePool resource needs to reference the EPP service via its `extensionRef` field, and the chart wires that up automatically. The Helm release name (`llmd-pool`) becomes the InferencePool resource name — this is what the InferenceObjective and HTTPRoute reference.

```bash
export IGW_CHART_VERSION=v1.1.0

# This is none because this param is for if you want to install a gateway as part of the helm install
export GATEWAY_PROVIDER=none

helm install llmd-pool \
  --namespace llmd-workshop \
  --set inferencePool.modelServers.matchLabels.app=llmd-model-server \
  --set provider.name=$GATEWAY_PROVIDER \
  --version $IGW_CHART_VERSION \
  oci://registry.k8s.io/gateway-api-inference-extension/charts/inferencepool
```

Verify:

```bash
# Check the InferencePool resource
kubectl get inferencepool -n llmd-workshop

# Check the EPP pod
kubectl get pods -n llmd-workshop
```

> The `provider.name=none` setting means we're providing our own gateway (agentgateway) rather than letting the chart install one.

## Step 8: Create InferenceObjective

The InferenceObjective maps a workload to the InferencePool backend with a scheduling priority.

```bash
kubectl apply -f manifests/02-inference-objective.yaml
```

Verify:

```bash
kubectl get inferenceobjective -n llmd-workshop
```

## Step 9: Deploy Gateway and HTTPRoute

Create the agentgateway Gateway (entry point) and the HTTPRoute (wiring to InferencePool).

```bash
kubectl apply -f manifests/04-gatewayhttproute.yaml
```

Wait for the gateway to get an address:

```bash
kubectl get gateway llmd-inference-gateway -n llmd-workshop -w
```

## Step 10: Connect kagent

Now wire kagent to send LLM requests through the full inference stack.

First, update the ModelConfig with the actual gateway service name:

```bash
kubectl apply -f manifests/05-kagent-config.yaml
```

Verify:

```bash
kubectl get modelconfig -n kagent
kubectl get agent -n kagent
```

## Step 11: Test via kagent UI

1. Open the kagent UI in your browser (use the LoadBalancer address from Step 4)
2. Find the **llmd-inference-agent** in the agent list
3. Send a message — the request flows through the full stack:
   - kagent → agentgateway → HTTPRoute → InferencePool → EPP → vLLM

You can seee that the route was successful through agentgateway.
```
kubectl logs llmd-inference-gateway-995885bcc-t5vwn -n llmd-workshop

2026-03-29T13:58:14.52476Z      info    request gateway=llmd-workshop/llmd-inference-gateway listener=http route=llmd-workshop/llmd-inference-route endpoint=10.224.0.101:8000 src.addr=10.224.0.120:18308 http.method=POST http.host=20.66.113.50 http.path=/v1/chat/completions http.version=HTTP/1.1 http.status=200 protocol=http inferencepool.selected_endpoint=10.224.0.101:8000 duration=10459ms
```

Watch the routing happen in real-time by running the observe script in a separate terminal:


```bash
bash scripts/observe-epp.sh
```

## Observing llm-d Routing Decisions

The power of this architecture is the intelligent routing. Here's how to see it in action.

### EPP Logs

The EPP pod logs every routing decision. Watch them in real-time:

```bash
bash scripts/observe-epp.sh
```

Key log fields to watch:
- `selected_endpoint` — Which vLLM pod was chosen
- `prefix_cache_hit` — Whether KV cache was reused (true = faster inference)
- `queue_depth` — Pending requests at each endpoint
- `score` — EPP scoring for each candidate pod

### Load Distribution Test

Send 20 requests and see how they're distributed across pods:

```bash
bash scripts/test-inference.sh
```

### Cache-Aware Routing Test

Demonstrate that the EPP routes identical prompts to the same pod (prefix-cache affinity):

```bash
bash scripts/test-cache-routing.sh
```

### vLLM Metrics

Each vLLM pod exposes Prometheus metrics:

```bash
# Port-forward to a vLLM pod
POD=$(kubectl get pods -n llmd-workshop -l app=llmd-model-server -o name | head -1)
kubectl port-forward -n llmd-workshop $POD 8000:8000

# In another terminal, fetch metrics
curl http://localhost:8000/metrics | grep -E "vllm:(num_requests|cache)"
```

Key metrics:
- `vllm:num_requests_running` — Currently processing
- `vllm:num_requests_waiting` — Queued requests
- `vllm:cpu_cache_usage_perc` — KV cache utilization

## Cleanup

Remove all workshop resources:

```bash
bash scripts/cleanup.sh
```

This removes workshop resources in reverse dependency order. It will prompt before removing agentgateway and kagent infrastructure.

## Troubleshooting

### vLLM pods stuck in Pending
Check node resources: `kubectl describe pod -n llmd-workshop <pod-name>`. Each replica needs 4 CPU and 4Gi memory.

### Gateway has no address
Check agentgateway controller logs: `kubectl logs -n agentgateway-system -l app.kubernetes.io/name=agentgateway`

### curl returns connection refused
The gateway Service may still be provisioning. Check: `kubectl get svc -n llmd-workshop`

### EPP pod not found
The EPP is created by the InferencePool Helm chart. Verify: `helm list -n llmd-workshop`

### kagent agent not responding
Check the ModelConfig baseUrl matches the actual gateway service DNS name: `kubectl get svc -n llmd-workshop`

### Requests timing out
CPU inference is slow. The HTTPRoute has a 300s timeout. For faster responses, reduce `max_tokens` in your requests.

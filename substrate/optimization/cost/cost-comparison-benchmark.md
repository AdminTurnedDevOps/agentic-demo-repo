---
title: "Agent Substrate Cost Comparison Benchmark"
date: 2026-06-25
description: >
  A benchmark lab comparing many always-on Kubernetes counter agents with the
  same logical workload running as Agent Substrate actors on a smaller WorkerPool.
tags: [agent-substrate, kubernetes, benchmarking, optimization, cost]
author: Michael Levan
---

# Agent Substrate Cost Comparison Benchmark

This lab compares two real deployment models for the same counter workload:

| Model | What Runs |
|---|---|
| Always-on Kubernetes | One `Deployment` and one running Pod per logical counter agent |
| Agent Substrate | One logical actor per counter agent, multiplexed onto a smaller `WorkerPool` |

The goal is to prove the cost optimization with measured infrastructure, not only
with a model estimate.

You will deploy 50 always-on Kubernetes counter agents, create 50 Substrate
counter actors, run equivalent HTTP requests, and compare Pod count, resource
usage, and latency.

## What You Measure

- Running Pods for the Kubernetes baseline.
- Running worker Pods for the Substrate workload.
- Kubernetes baseline first-request and warm-request latency.
- Substrate wake-request and warm-request latency.
- CPU/memory usage if `metrics-server` is installed.
- Pod-hour reduction between always-on agents and Substrate workers.

## Prerequisites

Run this lab from the root of the `substrate` repo. Clone it down from [here](https://github.com/agent-substrate/substrate)

You need:

- Agent Substrate installed and working.
- The counter demo installed.
- `kubectl-ate` installed.
- A Kubernetes cluster that can run the extra baseline Pods.

If the cluster cannot schedule 50 extra baseline Pods, reduce `ACTOR_COUNT` to a
smaller value such as `10` or `20`. The comparison is still valid as long as the
same `ACTOR_COUNT` is used for both models.

Install the counter demo and CLI:

```bash
cp hack/ate-dev-env.sh.example .ate-dev-env.sh
```

Edit `.ate-dev-env.sh` for your GCP project, cluster, snapshot bucket, and image
registry before sourcing it. At minimum, check these values:

Do not source the unedited example file. The stock example defaults
`PROJECT_ID` to `${USER}-gke-dev` and derives `PROJECT_NUMBER` with `gcloud
projects describe`, which will fail if that placeholder project does not exist
or you do not have access to it.

```bash
PROJECT_ID=<your-project-id>
PROJECT_NUMBER=<your-project-number>
GCE_REGION=<bucket-region>
CLUSTER_LOCATION=<cluster-zone-or-region>
CLUSTER_NAME=<your-gke-cluster>
BUCKET_NAME=<your-snapshot-bucket>
KO_DOCKER_REPO=gcr.io/<your-project-id>/ate-images
KUBECTL_CONTEXT=<your-kube-context>
```

Then source it and install the demo:

```bash
source .ate-dev-env.sh
./hack/install-ate.sh --deploy-demo-counter
go install ./cmd/kubectl-ate
```

Wait for the Substrate counter template:

```bash
kubectl wait --for=condition=Ready actortemplates.ate.dev/counter \
  -n ate-demo-counter \
  --timeout=5m
```

Verify Substrate state:

```bash
kubectl get workerpools.ate.dev counter -n ate-demo-counter
kubectl get pods -n ate-demo-counter
kubectl ate get workers
```

## Step 1: Configure The Benchmark

```bash
export ACTOR_COUNT=50
export BENCHMARK_NAMESPACE=cost-comparison
export BASELINE_PREFIX=k8s-counter
export SUBSTRATE_PREFIX=substrate-counter
export TEMPLATE_REF=ate-demo-counter/counter
export SUBSTRATE_ROUTER_URL=http://atenet-router.ate-system.svc:80

export BASELINE_CPU_REQUEST=50m
export BASELINE_MEMORY_REQUEST=64Mi

export BASELINE_RESULTS_FILE=baseline-kubernetes-results.tsv
export SUBSTRATE_RESULTS_FILE=substrate-results.tsv
export SUMMARY_FILE=cost-comparison-summary.txt
```

Get the counter image from the live `ActorTemplate`. This keeps the Kubernetes
baseline on the same counter server image used by the Substrate demo.

```bash
export COUNTER_IMAGE=$(kubectl get actortemplates.ate.dev counter \
  -n ate-demo-counter \
  -o jsonpath='{.spec.containers[0].image}')

printf "Counter image: %s\n" "$COUNTER_IMAGE"
```

If the image starts with `ko://`, the demo manifest was not resolved into a real
image. Re-run `./hack/install-ate.sh --deploy-demo-counter` from the `substrate`
repo with your registry environment configured.

```bash
case "$COUNTER_IMAGE" in
  ko://*)
    printf "Counter image was not resolved: %s\n" "$COUNTER_IMAGE"
    exit 1
    ;;
esac
```

Capture the Substrate worker count:

```bash
export WORKER_REPLICAS=$(kubectl get workerpools.ate.dev counter \
  -n ate-demo-counter \
  -o jsonpath='{.spec.replicas}')

printf "Logical agents: %s\nSubstrate workers: %s\n" \
  "$ACTOR_COUNT" "$WORKER_REPLICAS"
```

## Step 2: Deploy The Always-On Kubernetes Baseline

Create a namespace for the baseline workloads and benchmark client:

```bash
kubectl create namespace "$BENCHMARK_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
```

Deploy one Kubernetes `Deployment` and one `Service` per logical counter agent:

```bash
for i in $(seq 1 "$ACTOR_COUNT"); do
  name=$(printf "%s-%03d" "$BASELINE_PREFIX" "$i")

  kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${name}
  namespace: ${BENCHMARK_NAMESPACE}
  labels:
    app.kubernetes.io/name: counter
    app.kubernetes.io/part-of: cost-comparison
    cost-comparison/model: always-on-kubernetes
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: counter
      app.kubernetes.io/instance: ${name}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: counter
        app.kubernetes.io/instance: ${name}
        app.kubernetes.io/part-of: cost-comparison
        cost-comparison/model: always-on-kubernetes
    spec:
      containers:
      - name: counter
        image: ${COUNTER_IMAGE}
        command:
        - /ko-app/counter
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: ${BASELINE_CPU_REQUEST}
            memory: ${BASELINE_MEMORY_REQUEST}
---
apiVersion: v1
kind: Service
metadata:
  name: ${name}
  namespace: ${BENCHMARK_NAMESPACE}
  labels:
    app.kubernetes.io/name: counter
    app.kubernetes.io/part-of: cost-comparison
    cost-comparison/model: always-on-kubernetes
spec:
  selector:
    app.kubernetes.io/name: counter
    app.kubernetes.io/instance: ${name}
  ports:
  - name: http
    port: 80
    targetPort: 80
EOF
done
```

Wait for all baseline Deployments:

```bash
kubectl wait --for=condition=Available deployment \
  -n "$BENCHMARK_NAMESPACE" \
  -l cost-comparison/model=always-on-kubernetes \
  --timeout=10m
```

Confirm the baseline really created one running Pod per logical agent:

```bash
kubectl get deployments -n "$BENCHMARK_NAMESPACE" \
  -l cost-comparison/model=always-on-kubernetes

kubectl get pods -n "$BENCHMARK_NAMESPACE" \
  -l cost-comparison/model=always-on-kubernetes
```

## Step 3: Create A Benchmark Client Pod

The benchmark client runs inside the cluster so both paths avoid local
port-forward overhead.

```bash
kubectl delete pod benchmark-client \
  -n "$BENCHMARK_NAMESPACE" \
  --ignore-not-found

kubectl run benchmark-client \
  -n "$BENCHMARK_NAMESPACE" \
  --image=curlimages/curl:8.10.1 \
  --restart=Never \
  --command -- sleep 3600

kubectl wait --for=condition=Ready pod/benchmark-client \
  -n "$BENCHMARK_NAMESPACE" \
  --timeout=2m
```

## Step 4: Run The Kubernetes Baseline Benchmark

Each baseline agent receives two requests:

- First measured request.
- Second warm request.

Because these are always-on Pods, both requests should be served by already
running Kubernetes workloads.

```bash
kubectl exec -n "$BENCHMARK_NAMESPACE" benchmark-client -- sh -c '
set -eu
actor_count="$1"
prefix="$2"
namespace="$3"

printf "agent\tfirst_seconds\twarm_seconds\n"

for i in $(seq 1 "$actor_count"); do
  name=$(printf "%s-%03d" "$prefix" "$i")
  url="http://${name}.${namespace}.svc.cluster.local"

  first_seconds=$(curl -sS -o /dev/null -w "%{time_total}" -X POST "$url")
  warm_seconds=$(curl -sS -o /dev/null -w "%{time_total}" -X POST "$url")

  printf "%s\t%s\t%s\n" "$name" "$first_seconds" "$warm_seconds"
done
' sh "$ACTOR_COUNT" "$BASELINE_PREFIX" "$BENCHMARK_NAMESPACE" > "$BASELINE_RESULTS_FILE"
```

Inspect the baseline results:

```bash
column -t -s $'\t' "$BASELINE_RESULTS_FILE"
```

## Step 5: Create Substrate Actors

Create one Substrate actor per logical counter agent:

```bash
for i in $(seq 1 "$ACTOR_COUNT"); do
  actor=$(printf "%s-%03d" "$SUBSTRATE_PREFIX" "$i")
  kubectl ate create actor "$actor" --template "$TEMPLATE_REF" || true
done
```

Confirm actor and worker state:

```bash
kubectl ate get actors
kubectl ate get workers
```

The key difference from the Kubernetes baseline: the number of actors can be much
larger than the number of running worker Pods.

## Step 6: Run The Substrate Benchmark

Each Substrate actor receives two requests:

- Wake request, which resumes a suspended actor and serves the request.
- Warm request, which hits the already-running actor.

After each actor is measured, the actor is suspended so the worker can serve the
next actor.

```bash
printf "actor\twake_seconds\twarm_seconds\n" > "$SUBSTRATE_RESULTS_FILE"

for i in $(seq 1 "$ACTOR_COUNT"); do
  actor=$(printf "%s-%03d" "$SUBSTRATE_PREFIX" "$i")
  actor_host="${actor}.actors.resources.substrate.ate.dev"

  result=$(kubectl exec -n "$BENCHMARK_NAMESPACE" benchmark-client -- sh -c '
set -eu
router_url="$1"
actor_host="$2"

wake_seconds=$(curl -sS -o /dev/null -w "%{time_total}" \
  -X POST \
  -H "Host: ${actor_host}" \
  "$router_url")

warm_seconds=$(curl -sS -o /dev/null -w "%{time_total}" \
  -X POST \
  -H "Host: ${actor_host}" \
  "$router_url")

printf "%s\t%s" "$wake_seconds" "$warm_seconds"
' sh "$SUBSTRATE_ROUTER_URL" "$actor_host")

  printf "%s\t%s\n" "$actor" "$result" >> "$SUBSTRATE_RESULTS_FILE"
  kubectl ate suspend actor "$actor" >/dev/null
done
```

Watch worker assignment in another terminal while the benchmark runs:

```bash
while true; do
  clear
  date
  kubectl ate get workers
  sleep 2
done
```

Inspect Substrate results:

```bash
column -t -s $'\t' "$SUBSTRATE_RESULTS_FILE"
```

## Step 7: Measure Pod Count And Resource Usage

Capture the running Pod count for each model:

```bash
export BASELINE_RUNNING_PODS=$(kubectl get pods \
  -n "$BENCHMARK_NAMESPACE" \
  -l cost-comparison/model=always-on-kubernetes \
  --field-selector=status.phase=Running \
  --no-headers | wc -l | tr -d ' ')

export SUBSTRATE_WORKLOAD_PODS=$(kubectl get pods \
  -n ate-demo-counter \
  --field-selector=status.phase=Running \
  --no-headers | wc -l | tr -d ' ')

printf "baseline_running_pods=%s\n" "$BASELINE_RUNNING_PODS"
printf "substrate_workload_pods=%s\n" "$SUBSTRATE_WORKLOAD_PODS"
printf "substrate_workerpool_replicas=%s\n" "$WORKER_REPLICAS"
```

Capture resource requests for the Kubernetes baseline:

```bash
printf "baseline_cpu_request_per_pod=%s\n" "$BASELINE_CPU_REQUEST"
printf "baseline_memory_request_per_pod=%s\n" "$BASELINE_MEMORY_REQUEST"
```

Capture Substrate worker container requests from the live worker Pods if present:

```bash
kubectl get pods -n ate-demo-counter \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .spec.containers[*]}{.name}{":"}{.resources.requests.cpu}{"/"}{.resources.requests.memory}{" "}{end}{"\n"}{end}'
```

Capture actual CPU and memory usage if `metrics-server` is installed:

```bash
kubectl top pods -n "$BENCHMARK_NAMESPACE" \
  -l cost-comparison/model=always-on-kubernetes || true

kubectl top pods -n ate-demo-counter || true
```

For a workload-only comparison, use the baseline counter Pods versus the
Substrate counter worker Pods. For a platform-inclusive comparison, also include
the Agent Substrate control plane Pods in `ate-system`:

```bash
kubectl top pods -n ate-system || true
kubectl get pods -n ate-system
```

## Step 8: Summarize Latency

Generate p50/p95 summaries for both models:

```bash
{
  printf "actor_count=%s\n" "$ACTOR_COUNT"
  printf "baseline_running_pods=%s\n" "$BASELINE_RUNNING_PODS"
  printf "substrate_workload_pods=%s\n" "$SUBSTRATE_WORKLOAD_PODS"
  printf "substrate_workerpool_replicas=%s\n" "$WORKER_REPLICAS"

  awk 'NR > 1 { print $2 }' "$BASELINE_RESULTS_FILE" | sort -n | awk '
    { values[NR] = $1; sum += $1 }
    END {
      p50 = int((NR + 1) * 0.50); p95 = int((NR + 1) * 0.95)
      if (p50 < 1) { p50 = 1 }; if (p95 < 1) { p95 = 1 }
      if (p50 > NR) { p50 = NR }; if (p95 > NR) { p95 = NR }
      printf "baseline_first_avg_seconds=%.3f\n", sum / NR
      printf "baseline_first_p50_seconds=%.3f\n", values[p50]
      printf "baseline_first_p95_seconds=%.3f\n", values[p95]
    }'

  awk 'NR > 1 { print $3 }' "$BASELINE_RESULTS_FILE" | sort -n | awk '
    { values[NR] = $1; sum += $1 }
    END {
      p50 = int((NR + 1) * 0.50); p95 = int((NR + 1) * 0.95)
      if (p50 < 1) { p50 = 1 }; if (p95 < 1) { p95 = 1 }
      if (p50 > NR) { p50 = NR }; if (p95 > NR) { p95 = NR }
      printf "baseline_warm_avg_seconds=%.3f\n", sum / NR
      printf "baseline_warm_p50_seconds=%.3f\n", values[p50]
      printf "baseline_warm_p95_seconds=%.3f\n", values[p95]
    }'

  awk 'NR > 1 { print $2 }' "$SUBSTRATE_RESULTS_FILE" | sort -n | awk '
    { values[NR] = $1; sum += $1 }
    END {
      p50 = int((NR + 1) * 0.50); p95 = int((NR + 1) * 0.95)
      if (p50 < 1) { p50 = 1 }; if (p95 < 1) { p95 = 1 }
      if (p50 > NR) { p50 = NR }; if (p95 > NR) { p95 = NR }
      printf "substrate_wake_avg_seconds=%.3f\n", sum / NR
      printf "substrate_wake_p50_seconds=%.3f\n", values[p50]
      printf "substrate_wake_p95_seconds=%.3f\n", values[p95]
    }'

  awk 'NR > 1 { print $3 }' "$SUBSTRATE_RESULTS_FILE" | sort -n | awk '
    { values[NR] = $1; sum += $1 }
    END {
      p50 = int((NR + 1) * 0.50); p95 = int((NR + 1) * 0.95)
      if (p50 < 1) { p50 = 1 }; if (p95 < 1) { p95 = 1 }
      if (p50 > NR) { p50 = NR }; if (p95 > NR) { p95 = NR }
      printf "substrate_warm_avg_seconds=%.3f\n", sum / NR
      printf "substrate_warm_p50_seconds=%.3f\n", values[p50]
      printf "substrate_warm_p95_seconds=%.3f\n", values[p95]
    }'
} | tee "$SUMMARY_FILE"
```

## Step 9: Calculate Pod-Hour Reduction

This calculation uses measured running workload Pods.

```bash
awk \
  -v baseline="$BASELINE_RUNNING_PODS" \
  -v substrate="$SUBSTRATE_WORKLOAD_PODS" \
  'BEGIN {
    saved = baseline - substrate
    savings_pct = (saved / baseline) * 100

    printf "baseline_workload_pod_hours_per_hour=%d\n", baseline
    printf "substrate_workload_pod_hours_per_hour=%d\n", substrate
    printf "pod_hours_saved_per_hour=%d\n", saved
    printf "workload_pod_hour_reduction_pct=%.1f%%\n", savings_pct
    printf "actor_to_worker_pod_ratio=%.1f:1\n", baseline / substrate
  }'
```

Example shape for 50 baseline Pods and 5 Substrate worker Pods:

```text
baseline_workload_pod_hours_per_hour=50
substrate_workload_pod_hours_per_hour=5
pod_hours_saved_per_hour=45
workload_pod_hour_reduction_pct=90.0%
actor_to_worker_pod_ratio=10.0:1
```

Optional dollar projection using your own Pod-hour cost:

```bash
export POD_HOURLY_COST=0.05

awk \
  -v baseline="$BASELINE_RUNNING_PODS" \
  -v substrate="$SUBSTRATE_WORKLOAD_PODS" \
  -v pod_cost="$POD_HOURLY_COST" \
  'BEGIN {
    baseline_hourly = baseline * pod_cost
    substrate_hourly = substrate * pod_cost
    hourly_saved = baseline_hourly - substrate_hourly

    printf "pod_hourly_cost=%.4f\n", pod_cost
    printf "baseline_hourly_cost=%.2f\n", baseline_hourly
    printf "substrate_hourly_cost=%.2f\n", substrate_hourly
    printf "estimated_hourly_savings=%.2f\n", hourly_saved
    printf "estimated_30_day_savings=%.2f\n", hourly_saved * 24 * 30
  }'
```

Use actual cloud pricing, requested CPU/memory, node packing, and storage costs
for a finance-grade estimate. The lab gives you the measured workload shape and
latency tradeoff.

## Results Template

| Metric | Value |
|---|---:|
| Logical agents | `<ACTOR_COUNT>` |
| Baseline running Pods | `<BASELINE_RUNNING_PODS>` |
| Substrate worker Pods | `<SUBSTRATE_WORKLOAD_PODS>` |
| Pod-hour reduction | `<percent>` |
| Baseline first p95 | `<baseline_first_p95_seconds>` |
| Baseline warm p95 | `<baseline_warm_p95_seconds>` |
| Substrate wake p95 | `<substrate_wake_p95_seconds>` |
| Substrate warm p95 | `<substrate_warm_p95_seconds>` |
| Baseline CPU/memory usage | `kubectl top pods` |
| Substrate CPU/memory usage | `kubectl top pods` |

## Cleanup

Delete Substrate actors:

```bash
for i in $(seq 1 "$ACTOR_COUNT"); do
  actor=$(printf "%s-%03d" "$SUBSTRATE_PREFIX" "$i")
  kubectl ate delete actor "$actor" || true
done
```

Delete the Kubernetes baseline namespace:

```bash
kubectl delete namespace "$BENCHMARK_NAMESPACE"
```

Remove local result files:

```bash
rm -f "$BASELINE_RESULTS_FILE" "$SUBSTRATE_RESULTS_FILE" "$SUMMARY_FILE"
```

Optionally remove the Substrate counter demo:

```bash
./hack/install-ate.sh --delete-demo-counter
```

## Troubleshooting

If the baseline Pods do not become ready:

```bash
kubectl get pods -n "$BENCHMARK_NAMESPACE"
kubectl describe pod -n "$BENCHMARK_NAMESPACE" \
  -l cost-comparison/model=always-on-kubernetes
kubectl get events -n "$BENCHMARK_NAMESPACE" --sort-by='.lastTimestamp'
```

If the benchmark client cannot resolve baseline Services:

```bash
kubectl exec -n "$BENCHMARK_NAMESPACE" benchmark-client -- curl -v \
  "http://${BASELINE_PREFIX}-001.${BENCHMARK_NAMESPACE}.svc.cluster.local"
```

If Substrate requests fail, verify the router and actor state:

```bash
kubectl get svc -n ate-system atenet-router
kubectl ate get actors
kubectl ate get workers
```

If `kubectl top pods` fails, `metrics-server` is not installed or not ready. The
latency and Pod-count portions of the benchmark still work.

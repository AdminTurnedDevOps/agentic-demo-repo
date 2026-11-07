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

> The sample outputs, latency numbers, and Pod counts in this lab were measured on
> a pre-1.0 build of Agent Substrate (5 counter workers, router reached over plain
> HTTP). The commands are updated for v1.0.0. Re-run the lab to get v1.0.0 numbers.

This lab compares two real deployment models for the same counter workload:

| Model | What Runs |
|---|---|
| Always-on Kubernetes | One `Deployment` and one running Pod per logical agent |
| Agent Substrate | One logical actor per agent, multiplexed onto a smaller `WorkerPool` |

The goal is to prove the cost optimization with measured infrastructure, not only with a model estimate.

You will deploy 50 always-on Kubernetes counter agents, create 50 Substrate counter actors, run equivalent HTTP requests, and compare Pod count, resource usage, and latency.

Whats used here isn't Agents, but an HTTP workload instead. This comes from the Agent Substrate Counter Demo.

### Quick Definition Help

Actor == Where the Agent runs
Worker == k8s Pod

## What You Measure

- Running Pods for the Kubernetes baseline.
- Running worker Pods for the Substrate workload.
- Kubernetes baseline first-request and warm-request latency.
- Substrate wake-request and warm-request latency.
- CPU/memory usage if `metrics-server` is installed.
- Pod-hour reduction between always-on agents and Substrate workers.

## Prerequisites

Run this lab from the root of the `substrate` repo, checked out at the `v1.0.0` tag:

```bash
git clone --branch v1.0.0 https://github.com/agent-substrate/substrate.git
cd substrate
```

You need:

- Agent Substrate v1.0.0 installed and working (see the [setup lab](../../install-and-setup/setup-gke.md)).
- `kubectl-ate` installed.
- `jq`.
- A Kubernetes cluster that can run the extra baseline Pods.
- `KO_DOCKER_REPO` set to a registry your cluster can pull from. No demo images
  are published, so `ate-setup` builds the counter image with `ko`.

If the cluster cannot schedule 50 extra baseline Pods, reduce `ACTOR_COUNT` to a
smaller value such as `10` or `20`. The comparison is still valid as long as the
same `ACTOR_COUNT` is used for both models.

Install the counter demo and CLI:

```bash
export KO_DOCKER_REPO=<your-registry>

go run ./cmd/ate-setup deploy demo counter
go install ./cmd/kubectl-ate

export PATH="$(go env GOPATH)/bin:$PATH"
```

`deploy demo counter` creates the `counter` WorkerPool in the `ate-demo-counter`
namespace, the `ate-demo-counter` atespace, and the `counter` actor template in
that atespace, then waits for the template's golden snapshot. The template is not
a Kubernetes object. Check it through the Substrate API:

```bash
kubectl ate get actor-templates -a ate-demo-counter
```

`GOLDEN TAG` is set and `ERROR` is empty.

Verify Substrate state:

```bash
kubectl get workerpools.ate.dev counter -n ate-demo-counter
kubectl get pods -n ate-demo-counter
kubectl ate get workers -n ate-demo-counter
```

The v1.0.0 counter demo ships `replicas: 3`. The recorded run in this lab used 5
workers. To match it, scale the pool:

```bash
kubectl patch workerpools.ate.dev counter \
  -n ate-demo-counter \
  --type=merge \
  -p '{"spec":{"replicas":5}}'
```

If your GKE cluster is regional or has workers spread across zones, pin the demo
`WorkerPool` to one zone before creating benchmark actors. Substrate uses
checkpoint/restore, and gVisor restores can fail if a snapshot created on one
underlying CPU platform is restored on a node with a different CPU feature set.

Choose the zone where you want the counter workers to run, and the CPU/memory
request for each worker Pod:

```bash
export SUBSTRATE_WORKER_ZONE=us-east1-d
export SUBSTRATE_WORKER_CPU_REQUEST=50m
export SUBSTRATE_WORKER_MEMORY_REQUEST=64Mi
```

Patch the counter `WorkerPool` to schedule workers in that zone and apply
explicit worker CPU/memory requests:

```bash
kubectl patch workerpools.ate.dev counter \
  -n ate-demo-counter \
  --type=merge \
  -p "{\"spec\":{\"template\":{\"nodeSelector\":{\"topology.kubernetes.io/zone\":\"${SUBSTRATE_WORKER_ZONE}\"},\"resources\":{\"requests\":{\"cpu\":\"${SUBSTRATE_WORKER_CPU_REQUEST}\",\"memory\":\"${SUBSTRATE_WORKER_MEMORY_REQUEST}\"}}}}}"
```

Wait for the worker Deployment to settle:

```bash
kubectl rollout status deployment/counter \
  -n ate-demo-counter \
  --timeout=5m
```

If you patch the `WorkerPool` after actors already exist, delete and recreate the
benchmark actors so they use snapshots from the current worker placement.

## Step 1: Configure The Benchmark

```bash
export ACTOR_COUNT=50
export BENCHMARK_NAMESPACE=cost-comparison
export BASELINE_PREFIX=k8s-counter
export SUBSTRATE_PREFIX=substrate-counter
export SUBSTRATE_ATESPACE=cost-comparison
export TEMPLATE_REF=ate-demo-counter/counter
export SUBSTRATE_ROUTER_URL=https://atenet-router.ate-system.svc

export BASELINE_CPU_REQUEST=50m
export BASELINE_MEMORY_REQUEST=64Mi

export BASELINE_RESULTS_FILE=baseline-kubernetes-results.tsv
export SUBSTRATE_RESULTS_FILE=substrate-results.tsv
export SUMMARY_FILE=cost-comparison-summary.txt
```

Variable reference:

| Variable | Purpose |
|---|---|
| `ACTOR_COUNT` | Number of logical counter agents to test in both models. The lab creates this many Kubernetes baseline Deployments and this many Substrate actors. |
| `BENCHMARK_NAMESPACE` | Namespace for the always-on Kubernetes baseline workloads and the in-cluster benchmark client Pod. |
| `BASELINE_PREFIX` | Name prefix for Kubernetes baseline Deployments and Services. |
| `SUBSTRATE_PREFIX` | Name prefix for Substrate actors created by the benchmark. |
| `SUBSTRATE_ATESPACE` | Atespace the benchmark actors are created in. |
| `TEMPLATE_REF` | Substrate actor template reference in `<atespace>/<name>` format. The counter demo creates template `counter` in atespace `ate-demo-counter`. |
| `SUBSTRATE_ROUTER_URL` | In-cluster HTTPS URL for `atenet-router`; benchmark client sends Substrate actor traffic through this service over mTLS. |
| `BASELINE_CPU_REQUEST` | CPU request assigned to each always-on Kubernetes baseline Pod. Used to make baseline resource consumption explicit. |
| `BASELINE_MEMORY_REQUEST` | Memory request assigned to each always-on Kubernetes baseline Pod. Used to make baseline resource consumption explicit. |
| `SUBSTRATE_WORKER_CPU_REQUEST` | CPU request assigned to each Substrate worker Pod, exported with the `WorkerPool` patch above. Used to compare requested capacity against the always-on baseline. |
| `SUBSTRATE_WORKER_MEMORY_REQUEST` | Memory request assigned to each Substrate worker Pod, exported with the `WorkerPool` patch above. Used to compare requested capacity against the always-on baseline. |
| `BASELINE_RESULTS_FILE` | Local TSV file for Kubernetes baseline latency results. |
| `SUBSTRATE_RESULTS_FILE` | Local TSV file for Substrate wake/warm latency results. |
| `SUMMARY_FILE` | Local summary file containing combined Pod-count and latency metrics. |

Get the counter image from the live `ActorTemplate`. This keeps the Kubernetes baseline on the same counter server image used by the Substrate demo.

```bash
export COUNTER_IMAGE=$(kubectl ate get actor-template counter \
  -a ate-demo-counter \
  -o json | jq -r '.containers[0].image')

printf "Counter image: %s\n" "$COUNTER_IMAGE"
```

If the image starts with `ko://`, the demo manifest was not resolved into a real image. Re-run `go run ./cmd/ate-setup deploy demo counter` from the `substrate` repo with `KO_DOCKER_REPO` set.

If the output from the following is blank, that means the container image is valid.

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
kubectl create namespace "$BENCHMARK_NAMESPACE"
```

Deploy one Kubernetes `Deployment` and one `Service` per logical counter agent:

**Sidenote: Despite the name "Actor" in Substrate, the $ACTOR_COUNT variable is used as the shared logical workload count, not only as a Substrate actor count.

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

You should see an output like `deployment.apps/k8s-counter-001 condition met` up to `050`

Confirm the baseline really created one running Pod per logical agent:

```bash
kubectl get deployments -n "$BENCHMARK_NAMESPACE" \
  -l cost-comparison/model=always-on-kubernetes

kubectl get pods -n "$BENCHMARK_NAMESPACE" \
  -l cost-comparison/model=always-on-kubernetes
```

## Step 3: Create A Benchmark Client Pod

The benchmark client runs inside the cluster so both paths avoid local port-forward overhead.

benchmark-client = temporary in-cluster curl Pod.

Why it exists:
- Sends requests to the Kubernetes baseline Services.
- Sends requests to Substrate through atenet-router.
- Avoids local kubectl port-forward latency.
- Keeps both benchmark paths inside the cluster network for a fairer comparison.

On v1.0.0, `atenet-router` serves only TLS and requires a client certificate.
The client gets one from a `podCertificate` projected volume, which carries the
SPIFFE ID of its ServiceAccount:
`spiffe://cluster.local/ns/<namespace>/sa/benchmark-client`. The router only
accepts IDs on its `--ingress-allowed-spiffe-ids` allowlist.

Create the ServiceAccount:

```bash
kubectl create serviceaccount benchmark-client -n "$BENCHMARK_NAMESPACE"
```

Add the client's ID to the allowlist. Redeploy atenet from the install record the
[setup lab](../../install-and-setup/setup-gke.md) wrote, with the full list. Each deploy replaces the
allowlist, so keep `atenet-client` in it:

```bash
go run ./cmd/ate-setup deploy atenet \
  --config ~/Library/Caches/ate-setup/installs/<context>.yaml \
  --ingress-allowed-spiffe-ids=spiffe://cluster.local/ns/ate-system/sa/atenet-client,spiffe://cluster.local/ns/${BENCHMARK_NAMESPACE}/sa/benchmark-client

kubectl rollout status deployment/atenet-router -n ate-system --timeout=5m
```

Create the client Pod with its certificate and the router's serving CA:

```bash
kubectl delete pod benchmark-client \
  -n "$BENCHMARK_NAMESPACE" \
  --ignore-not-found

kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: benchmark-client
  namespace: ${BENCHMARK_NAMESPACE}
spec:
  serviceAccountName: benchmark-client
  restartPolicy: Never
  containers:
  - name: benchmark-client
    image: curlimages/curl:8.10.1
    command: ["sleep", "3600"]
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

kubectl wait --for=condition=Ready pod/benchmark-client \
  -n "$BENCHMARK_NAMESPACE" \
  --timeout=2m
```

## Step 4: Run The Kubernetes Baseline Benchmark

Each baseline agent receives two requests:

- First measured request.
- Second warm request.

Because these are always-on Pods, both requests should be served by already running Kubernetes workloads.

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

You'll see an output similar to the below for 50 counters.

```
agent            first_seconds  warm_seconds
k8s-counter-001  0.023404       0.003911
k8s-counter-002  0.023275       0.005233
k8s-counter-003  0.015850       0.003773
k8s-counter-004  0.017657       0.005033
k8s-counter-005  0.014946       0.004443
k8s-counter-006  0.015616       0.004212
k8s-counter-007  0.016875       0.004261
k8s-counter-008  0.014731       0.004317
k8s-counter-009  0.017053       0.004707
k8s-counter-010  0.013013       0.003273
k8s-counter-011  0.014281       0.004552
k8s-counter-012  0.018644       0.003734
xxxxx
xxxxx
```

## Step 5: Create Substrate Actors

Create an atespace for the benchmark actors, then one Substrate actor per logical counter agent:

```bash
kubectl ate create atespace "$SUBSTRATE_ATESPACE"

for i in $(seq 1 "$ACTOR_COUNT"); do
  actor=$(printf "%s-%03d" "$SUBSTRATE_PREFIX" "$i")
  kubectl ate create actor "$actor" -a "$SUBSTRATE_ATESPACE" --template "$TEMPLATE_REF" || true
done
```

Confirm actor and worker state:

```bash
kubectl ate get actors -a "$SUBSTRATE_ATESPACE"
kubectl ate get workers -n ate-demo-counter
```

**What's Happening**: You’ll see 50 Agent Substrate Actors and a smaller set of Workers (Pods). The Actors are logical workloads, but they are not actively running while they are `ACTOR_STATE_SUSPENDED`. By default, Actors are in a "suspended" state until they are used, which is why Actors are so great from an efficiency perspective. When traffic arrives for an Actor, Agent Substrate assigns that actor to an available Worker, resumes it, serves the request, and can suspend it again afterward. This is the efficiency model: many idle actors can exist without each requiring its own always-on Kubernetes Pod.

The key difference from the Kubernetes baseline: the number of actors can be much larger than the number of running worker Pods.

## Step 6: Run The Substrate Benchmark

Each Substrate actor receives two requests:

- Wake request, which resumes a suspended actor and serves the request.
- Warm request, which hits the already-running actor.

After each actor is measured, the actor is suspended so the worker can serve the
next actor.

The router picks the actor from the `ate-target-actor: <atespace>/<actor>`
header. The pre-1.0 `Host: <actor>.actors.resources.substrate.ate.dev` routing
and the plain-HTTP port 80 are gone.

Check one actor first:

```bash
kubectl exec -n "$BENCHMARK_NAMESPACE" benchmark-client -- curl -sS \
  --cacert /run/router-client/router-ca.pem \
  --cert /run/router-client/credential-bundle.pem \
  --key /run/router-client/credential-bundle.pem \
  -X POST \
  -H "ate-target-actor: ${SUBSTRATE_ATESPACE}/${SUBSTRATE_PREFIX}-001" \
  "$SUBSTRATE_ROUTER_URL"
```

> **TODO (v1.0.0):** Not yet run live. `credential-bundle.pem` holds both the
> private key and the certificate chain, so it is passed to both `--cert` and
> `--key`. Confirm curl in `curlimages/curl:8.10.1` accepts it that way.

Then run the benchmark:

```bash
printf "actor\twake_seconds\twarm_seconds\n" > "$SUBSTRATE_RESULTS_FILE"

for i in $(seq 1 "$ACTOR_COUNT"); do
  actor=$(printf "%s-%03d" "$SUBSTRATE_PREFIX" "$i")
  target="${SUBSTRATE_ATESPACE}/${actor}"

  result=$(kubectl exec -n "$BENCHMARK_NAMESPACE" benchmark-client -- sh -c '
set -eu
router_url="$1"
target="$2"
creds=/run/router-client

wake_seconds=$(curl -sS -o /dev/null -w "%{time_total}" \
  --cacert "${creds}/router-ca.pem" \
  --cert "${creds}/credential-bundle.pem" \
  --key "${creds}/credential-bundle.pem" \
  -X POST \
  -H "ate-target-actor: ${target}" \
  "$router_url")

warm_seconds=$(curl -sS -o /dev/null -w "%{time_total}" \
  --cacert "${creds}/router-ca.pem" \
  --cert "${creds}/credential-bundle.pem" \
  --key "${creds}/credential-bundle.pem" \
  -X POST \
  -H "ate-target-actor: ${target}" \
  "$router_url")

printf "%s\t%s" "$wake_seconds" "$warm_seconds"
' sh "$SUBSTRATE_ROUTER_URL" "$target")

  printf "%s\t%s\n" "$actor" "$result" >> "$SUBSTRATE_RESULTS_FILE"
  kubectl ate suspend actor "$actor" -a "$SUBSTRATE_ATESPACE" >/dev/null
done
```

Each `curl` opens a new mTLS connection to the router, so both Substrate numbers
now include a TLS handshake that the plain-HTTP baseline does not pay. The
pre-1.0 numbers below did not.

Watch worker assignment in another terminal while the benchmark runs:

```bash
while true; do
  clear
  date
  kubectl ate get workers -n ate-demo-counter
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

Capture configured resource requests for both workload models:

```bash
printf "baseline_cpu_request_per_pod=%s\n" "$BASELINE_CPU_REQUEST"
printf "baseline_memory_request_per_pod=%s\n" "$BASELINE_MEMORY_REQUEST"
printf "substrate_worker_cpu_request_per_pod=%s\n" "$SUBSTRATE_WORKER_CPU_REQUEST"
printf "substrate_worker_memory_request_per_pod=%s\n" "$SUBSTRATE_WORKER_MEMORY_REQUEST"

printf "baseline_total_cpu_request_millicores=%s\n" \
  "$((BASELINE_RUNNING_PODS * ${BASELINE_CPU_REQUEST%m}))"
printf "baseline_total_memory_request_mib=%s\n" \
  "$((BASELINE_RUNNING_PODS * ${BASELINE_MEMORY_REQUEST%Mi}))"
printf "substrate_total_cpu_request_millicores=%s\n" \
  "$((SUBSTRATE_WORKLOAD_PODS * ${SUBSTRATE_WORKER_CPU_REQUEST%m}))"
printf "substrate_total_memory_request_mib=%s\n" \
  "$((SUBSTRATE_WORKLOAD_PODS * ${SUBSTRATE_WORKER_MEMORY_REQUEST%Mi}))"
```

Confirm Substrate worker container requests from the live worker Pods:

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

The Kubernetes baseline is running one always-on Pod per logical workload. With
`ACTOR_COUNT=50`, that means 50 `k8s-counter-*` Pods are running even when they
are mostly idle. Each baseline Pod has explicit CPU and memory requests, so the
requested always-on capacity grows linearly with the number of logical workloads.

The Substrate side is running the same logical workload count as actors, but only
the worker pool stays hot. In this run (pre-1.0 build), the counter WorkerPool had 5
`counter-*` worker Pods. Each worker Pod has explicit CPU and memory
requests, so the requested always-on capacity grows with worker count, not actor
count.

The main difference is the always-on footprint:

```
Kubernetes baseline: 50 running workload Pods
Agent Substrate:     5 running worker Pods for 50 logical actors
```

Your result shows the core optimization: 50 idle logical workloads do not require
50 always-on workload Pods when they run as Substrate actors.

## Step 8: Summarize Latency

Generate p50/p95 summaries for both models:

```bash
{
  printf "actor_count=%s\n" "$ACTOR_COUNT"
  printf "baseline_running_pods=%s\n" "$BASELINE_RUNNING_PODS"
  printf "substrate_workload_pods=%s\n" "$SUBSTRATE_WORKLOAD_PODS"
  printf "substrate_workerpool_replicas=%s\n" "$WORKER_REPLICAS"
  printf "baseline_total_cpu_request_millicores=%s\n" \
    "$((BASELINE_RUNNING_PODS * ${BASELINE_CPU_REQUEST%m}))"
  printf "baseline_total_memory_request_mib=%s\n" \
    "$((BASELINE_RUNNING_PODS * ${BASELINE_MEMORY_REQUEST%Mi}))"
  printf "substrate_total_cpu_request_millicores=%s\n" \
    "$((SUBSTRATE_WORKLOAD_PODS * ${SUBSTRATE_WORKER_CPU_REQUEST%m}))"
  printf "substrate_total_memory_request_mib=%s\n" \
    "$((SUBSTRATE_WORKLOAD_PODS * ${SUBSTRATE_WORKER_MEMORY_REQUEST%Mi}))"

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

This summary compares the same 50 logical workloads in two runtime models.

The Kubernetes baseline has 50 running Pods, one always-on Pod per counter workload:
```
baseline_running_pods=50
```

Agent Substrate has the same 50 logical workloads as actors, but only 5 worker Pods stay running:
```
substrate_workload_pods=5
substrate_workerpool_replicas=5
```

That is the cost optimization: Substrate keeps the idle footprint at 5 worker Pods instead of 50 always-on workload Pods.

The latency numbers show the tradeoff (measured on a pre-1.0 build):
```
baseline_first_p95_seconds=0.021
baseline_warm_p95_seconds=0.005
substrate_wake_p95_seconds=0.611
substrate_warm_p95_seconds=0.016
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

This is the cost-savings summary for the benchmark. More specifically, it shows workload Pod-hour reduction, which is the clearest infrastructure cost proxy in this lab.

With the numbers above:
```
baseline_running_pods=50
substrate_workload_pods=5
```

Step 9 calculates:
```
baseline_workload_pod_hours_per_hour=50
substrate_workload_pod_hours_per_hour=5
pod_hours_saved_per_hour=45
workload_pod_hour_reduction_pct=90.0%
actor_to_worker_pod_ratio=10.0:1
```

Which means for the same 50 logical workloads:

Kubernetes baseline keeps 50 workload Pods running.
Substrate keeps 5 worker Pods running.

That is a 90% reduction in always-on workload Pods.

Sidenote: This is not a literal cloud bill calculation by itself. It is a measured infrastructure footprint reduction. The optional `POD_HOURLY_COST` section then turns that Pod-hour reduction into an estimated dollar amount if you provide a Pod-hour cost.

## Cleanup

Delete Substrate actors and their atespace:

```bash
for i in $(seq 1 "$ACTOR_COUNT"); do
  actor=$(printf "%s-%03d" "$SUBSTRATE_PREFIX" "$i")
  kubectl ate delete actor "$actor" -a "$SUBSTRATE_ATESPACE" || true
done

kubectl ate delete atespace "$SUBSTRATE_ATESPACE"
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
go run ./cmd/ate-setup delete demo counter
```

Optionally drop the benchmark client's SPIFFE ID from
`--ingress-allowed-spiffe-ids` by re-running the same `deploy atenet --config ...` command
without it.

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
kubectl ate get actors -a "$SUBSTRATE_ATESPACE"
kubectl ate get workers -n ate-demo-counter
```

A TLS handshake failure from the router usually means the client's SPIFFE ID
(`spiffe://cluster.local/ns/${BENCHMARK_NAMESPACE}/sa/benchmark-client`) is not on
`--ingress-allowed-spiffe-ids`. With an empty allowlist the router serves no
listener at all.

If `kubectl top pods` fails, `metrics-server` is not installed or not ready. The
latency and Pod-count portions of the benchmark still work.

If actor suspend or restore fails with an error like `invalid snapshot URI prefix
"": missing bucket` or worker logs show `incompatible FeatureSet` (both seen on a
pre-1.0 build), the actor
restore likely crossed nodes with different CPU feature sets. Pin the
`WorkerPool` to one zone as shown in the prerequisites, then recreate the
benchmark actors:

```bash
for i in $(seq 1 "$ACTOR_COUNT"); do
  actor=$(printf "%s-%03d" "$SUBSTRATE_PREFIX" "$i")
  kubectl ate delete actor "$actor" -a "$SUBSTRATE_ATESPACE" || true
done

for i in $(seq 1 "$ACTOR_COUNT"); do
  actor=$(printf "%s-%03d" "$SUBSTRATE_PREFIX" "$i")
  kubectl ate create actor "$actor" -a "$SUBSTRATE_ATESPACE" --template "$TEMPLATE_REF" || true
done
```

For install problems (control plane Pods not ready, demo deploy timing out),
see the [setup lab](../../install-and-setup/setup-gke.md).

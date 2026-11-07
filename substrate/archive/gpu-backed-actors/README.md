---
title: "GPU-Backed Actors on Agent Substrate"
date: 2026-08-29
description: >
  Archived. Agent Substrate v1.0.0 does not pass GPUs into actor sandboxes,
  so this lab does not run. Kept for when a release adds a device API.
tags: [agent-substrate, kubernetes, gke, gpu, gvisor, actors]
author: Michael Levan
---

# GPU-Backed Actors

> **Archived: not working on v1.0.0.** Substrate v1.0.0 does not pass devices through to
> actors. The pre-1.0 behavior this lab was written against (the worker pod's
> GPU injected into every actor container) was removed while the device API is
> designed. A `nvidia.com/gpu` limit on a WorkerPool is now an ordinary
> extended resource: it places the worker pod on a GPU node and reserves the
> device, and nothing else reads it. See "Devices (GPUs) — temporarily
> unsupported" in `docs/reference/api-guide.md` at the `v1.0.0` tag.
>
> The steps below use v1.0.0 syntax, so the pool and template apply cleanly.
> The agent in `workload/` exits on boot when `nvidia-smi` finds no GPU, so the
> golden build for `gpu-agent` will fail (the template's `ERROR` column is set).
>
> **TODO (v1.0.0):** Re-test this lab once a release adds the device API.

An actor gets a GPU the same way a Pod does: put `nvidia.com/gpu` on the
**WorkerPool**. There is no GPU field on `ActorTemplate`. Substrate passes
the assigned device into every container in the actor (gVisor nvproxy).
(Pre-1.0 behavior. See the note above.)

This lab runs a small HTTP agent on that pool. On boot, and again on `GET /gpu`,
the agent shells out to `nvidia-smi` and exits the child. That is the pattern
a real agent should use: GPU as a tool call, not as process-resident VRAM.

A model server that keeps weights in GPU memory cannot be suspended today.
gVisor cannot checkpoint an open CUDA context, and the golden snapshot uses
the same image.

## What you need

- Agent Substrate v1.0.0 on a GKE Standard cluster (see the [setup lab](../../install-and-setup/setup-gke.md)),
  installed with `spiffe://cluster.local/ns/ate-system/sa/atenet-client` in
  `--ingress-allowed-spiffe-ids` so `kubectl ate proxy actor` works.
- A Linux `amd64` node that advertises `nvidia.com/gpu` (any NVIDIA SKU).
- NVIDIA device plugin exposing `nvidia.com/gpu`.
- `atelet` scheduled on GPU nodes (add a GPU taint toleration if they are tainted).
- A Substrate checkout at `v1.0.0`, `docker`+buildx, `jq`, `kubectl`, Go,
  `kubectl-ate` (`go install ./cmd/kubectl-ate` from the checkout).
- `KO_DOCKER_REPO` set to a registry your cluster can pull from.

The pre-1.0 lab also needed the NVIDIA Container Toolkit on the GPU nodes and a
glibc rebuild of the worker image, so the worker could exec `nvidia-ctk`. The
v1.0.0 worker does neither, so both are gone from this lab.

## 1. Cluster checks

```bash
export SUBSTRATE_DIR=/path/to/substrate   # checked out at v1.0.0
export KO_DOCKER_REPO=<your-registry>

kubectl get pods -n ate-system
kubectl get sandboxconfig gvisor-default
```

Confirm some node advertises `nvidia.com/gpu` (any SKU is fine):

```bash
kubectl get nodes -o json | jq -r \
  '["NAME","GPU","GKE_ACCEL","PRODUCT"],
   (.items[] | [
     .metadata.name,
     (.status.allocatable["nvidia.com/gpu"] // "-"),
     (.metadata.labels["cloud.google.com/gke-accelerator"] // "-"),
     (.metadata.labels["nvidia.com/gpu.product"] // "-")
   ]) | @tsv' | column -t
```

## 2. Build the images

These images are what the WorkerPool and ActorTemplate in the next steps
point at.

The worker image is the stock `ateworker-gvisor`. Build it from the checkout:

```bash
export WORKER_IMAGE=$(
  cd "$SUBSTRATE_DIR" &&
  KO_DOCKER_REPO="$KO_DOCKER_REPO" \
  KO_DEFAULTPLATFORMS=linux/amd64 \
  ./hack/run-tool.sh ko build ./cmd/ateworker-gvisor
)
echo "$WORKER_IMAGE"
```

Substrate does not ship a GPU actor. The image in `workload/` is the agent;
it runs `nvidia-smi` inside the actor as a child process (run this from this
directory):

```bash
docker buildx build \
  --platform linux/amd64 \
  --push \
  --provenance=false \
  --metadata-file /tmp/gpu-agent.json \
  --tag "${KO_DOCKER_REPO}/gpu-actor-workload:gpu-agent" \
  workload/

export GPU_WORKLOAD_IMAGE="${KO_DOCKER_REPO}/gpu-actor-workload@$(jq -er '."containerimage.digest"' /tmp/gpu-agent.json)"
echo "$GPU_WORKLOAD_IMAGE"
```

Snapshots go to the install's `--snapshot-location`. A per-template location
is behind the `PerTemplateSnapshotLocation` preview gate, so this lab does not
set one.

## 3. Apply the GPU WorkerPool

Before v1.0.0, `nvidia.com/gpu` on the pool was the whole passthrough switch.
On v1.0.0 it only places the worker on a node that advertises that resource
and reserves the device.

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: ate-demo-gpu
  labels:
    gpu-backed-actors-demo: "true"
---
apiVersion: ate.dev/v1
kind: WorkerPool
metadata:
  name: gpu-workers
  namespace: ate-demo-gpu
  labels:
    workload: gpu
spec:
  replicas: 1
  workerImage: ${WORKER_IMAGE}
  sandboxClasses:
  - name: gvisor
  template:
    tolerations:
    - key: nvidia.com/gpu
      operator: Exists
      effect: NoSchedule
    resources:
      requests:
        cpu: 500m
        memory: 2Gi
        nvidia.com/gpu: "1"
      limits:
        cpu: "2"
        memory: 4Gi
        nvidia.com/gpu: "1"
EOF
```

```bash
kubectl -n ate-demo-gpu rollout status deployment/gpu-workers --timeout=10m
```

The same YAML lives in [`manifests/workerpool.yaml`](manifests/workerpool.yaml).

## 4. Create the ActorTemplate

No GPU field here. `workerSelector` pins actors to the pool above. Templates are
not Kubernetes objects on v1.0.0. They live in an **atespace** and are created
through the ate API. Creating the template starts the golden snapshot: Substrate
boots a hidden actor, waits for the `/readyz` wakeup probe (after `nvidia-smi`
has exited), then checkpoints.

```bash
kubectl ate create atespace ate-demo-gpu

kubectl ate create actor-template -f - <<EOF
metadata:
  atespace: ate-demo-gpu
  name: gpu-agent
workerSelector:
  matchLabels:
    workload: gpu
containers:
- name: gpu-agent
  image: ${GPU_WORKLOAD_IMAGE}
  wakeupProbe:
    httpGet:
      path: /readyz
      port: 80
resources:
  limits:
    cpuMillicores: 1000
    memoryBytes: 2147483648 # 2Gi
snapshotConfig:
  preferredFidelity: SNAPSHOT_FIDELITY_MEMORY
EOF
```

Wait for the golden tag (or an error):

```bash
for i in $(seq 1 90); do
  T=$(kubectl ate get actor-template gpu-agent -a ate-demo-gpu -o json)
  TAG=$(echo "$T" | jq -r '.status.goldenSnapshotStatus.goldenTag.name // empty')
  ERR=$(echo "$T" | jq -r '.status.goldenSnapshotStatus.errorMessage // empty')
  [ -n "$TAG" ] && { echo "golden tag: $TAG"; break; }
  [ -n "$ERR" ] && { echo "golden build failed: $ERR"; break; }
  sleep 10
done
```

`kubectl ate get actor-templates -a ate-demo-gpu` shows the same thing in its
`GOLDEN TAG` and `ERROR` columns.

The same template lives in [`manifests/actortemplate.yaml`](manifests/actortemplate.yaml).

## 5. Create and resume the actor

Actors are control-plane records, not Kubernetes objects.

```bash
kubectl ate create atespace gpu-demo
kubectl ate create actor gpu-1 -a gpu-demo --template ate-demo-gpu/gpu-agent
kubectl ate resume actor gpu-1 -a gpu-demo
kubectl ate logs actor gpu-1 -a gpu-demo
```

Resume restores the golden snapshot, so the boot-time `nvidia-smi` already ran
in the golden actor and is not in this actor's logs. The pre-1.0 `--boot` flag
(cold start) is gone. Use `GET /` in the next step to see the boot probe.

## 6. Call the actor

```bash
kubectl ate proxy actor gpu-1 -a gpu-demo
```

That forwards `127.0.0.1:8000` to the actor's port 80 over the router's mTLS.
In another terminal:

```bash
curl -sS http://localhost:8000/

curl -sS http://localhost:8000/gpu
```

`/` is the boot-time probe (survives suspend). `/gpu` runs `nvidia-smi` now.

## Cleanup

```bash
kubectl ate delete actor gpu-1 -a gpu-demo
kubectl ate delete atespace gpu-demo
kubectl ate delete actor-template gpu-agent -a ate-demo-gpu
kubectl ate delete atespace ate-demo-gpu
kubectl delete workerpool gpu-workers -n ate-demo-gpu
kubectl delete namespace ate-demo-gpu
```

Deleting the template also deletes its golden actor and golden snapshot. That
does not delete GPU nodes or images. Actor snapshots live under the install's
`--snapshot-location`.

> **TODO (v1.0.0):** Confirm where in the snapshot bucket this lab's objects land,
> and whether deleting the actor and template removes them, before adding back a
> `gcloud storage rm` step.

## Troubleshooting

| Symptom | Check |
|---|---|
| Worker Pod Pending | GPU allocatable on the node, taint, `nvidia.com/gpu` in **requests and limits** |
| No atelet pod on the GPU node | Stock atelet tolerates only `ate.dev/sandboxClass` and `cloud.google.com/compute-class`, not `nvidia.com/gpu`. GKE GPU nodes use that taint. Patch the DaemonSet: `kubectl -n ate-system patch ds atelet --type=strategic -p '{"spec":{"template":{"spec":{"tolerations":[{"key":"nvidia.com/gpu","operator":"Exists","effect":"NoSchedule"}]}}}}'` |
| Template `ERROR` column set | `kubectl ate get actor-template gpu-agent -a ate-demo-gpu -o yaml` for the message; atelet logs on the GPU node; worker pod logs. On v1.0.0 the probe fails because no GPU reaches the actor (see the note at the top) |
| Suspend nvproxy error | A process still holds a CUDA context. This agent does not. |

The pre-1.0 claim that `microvm` WorkerPools reject `nvidia.com/gpu` no longer
holds: v1.0.0 accepts the limit on any pool and does not interpret it.

---
title: "GPU-Backed Actors on Agent Substrate"
date: 2026-08-29
description: >
  Run an agent actor on a GPU WorkerPool: nvidia.com/gpu on the pool is
  enough for Substrate to pass the device into the sandbox. The actor uses
  the GPU as a child-process tool call so golden snapshot and suspend still
  work.
tags: [agent-substrate, kubernetes, gke, gpu, gvisor, actors]
author: Michael Levan
---

# GPU-Backed Actors

An actor gets a GPU the same way a Pod does: put `nvidia.com/gpu` on the
**WorkerPool**. There is no GPU field on `ActorTemplate`. Substrate passes
the assigned device into every container in the actor (gVisor nvproxy).

This lab runs a small HTTP agent on that pool. On boot, and again on `GET /gpu`,
the agent shells out to `nvidia-smi` and exits the child. That is the pattern
a real agent should use: GPU as a tool call, not as process-resident VRAM.

A model server that keeps weights in GPU memory cannot be suspended today.
gVisor cannot checkpoint an open CUDA context, and the golden snapshot uses
the same image.

## What you need

- Agent Substrate on a GKE Standard cluster (see the [setup lab](../../setup.md)).
- A Linux `amd64` node that advertises `nvidia.com/gpu` (any NVIDIA SKU).
- NVIDIA device plugin exposing `nvidia.com/gpu`.
- **NVIDIA Container Toolkit on the GPU nodes** (`nvidia-ctk` under
  `/usr/local/nvidia/toolkit`). gpu-operator installs this; GKE's built-in GPU
  node images often do not.
- Driver files mounted into GPU pods, usually `/usr/local/nvidia`.
- `atelet` scheduled on GPU nodes (add a GPU taint toleration if they are tainted).
- A Substrate checkout, `docker`+buildx, `jq`, `kubectl`, `gcloud`, Go,
  `kubectl-ate`.
- `KO_DOCKER_REPO` and `BUCKET_NAME` from your Substrate env file.

The default `ateom-gvisor` image is distroless and cannot exec `nvidia-ctk`.
The glibc rebuild in step 2 is required.

## 1. Cluster checks

```bash
source /path/to/substrate/.ate-dev-env.sh
export SUBSTRATE_DIR=/path/to/substrate

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

The default `ateom-gvisor` worker image is `gcr.io/distroless/static-debian13`.
That image cannot exec `nvidia-ctk`, so it cannot inject a GPU into the
sandbox. Rebuild it on glibc:

```bash
export ATEOM_GPU_IMAGE=$(
  cd "$SUBSTRATE_DIR" &&
  KO_DOCKER_REPO="$KO_DOCKER_REPO" \
  KO_DEFAULTPLATFORMS=linux/amd64 \
  KO_DEFAULTBASEIMAGE=debian:stable-slim \
  ./hack/run-tool.sh ko build ./cmd/ateom-gvisor
)
echo "$ATEOM_GPU_IMAGE"
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

```bash
export SNAPSHOT_LOCATION="gs://${BUCKET_NAME}/ate-demo-gpu/"
```

## 3. Apply the GPU WorkerPool

`nvidia.com/gpu` on the pool is the whole passthrough switch. The scheduler
places the worker on any node that advertises that resource.

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: ate-demo-gpu
  labels:
    gpu-backed-actors-demo: "true"
---
apiVersion: ate.dev/v1alpha1
kind: WorkerPool
metadata:
  name: gpu-workers
  namespace: ate-demo-gpu
  labels:
    workload: gpu
spec:
  replicas: 1
  sandboxClass: gvisor
  workerImage: ${ATEOM_GPU_IMAGE}
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

## 4. Apply the ActorTemplate

No GPU field here. `workerSelector` pins actors to the pool above. Applying
the template starts the golden snapshot: Substrate boots a hidden actor,
waits for `/readyz` (after `nvidia-smi` has exited), then checkpoints.

```bash
kubectl apply -f - <<EOF
apiVersion: ate.dev/v1alpha1
kind: ActorTemplate
metadata:
  name: gpu-agent
  namespace: ate-demo-gpu
spec:
  sandboxClass: gvisor
  workerSelector:
    matchLabels:
      workload: gpu
  containers:
  - name: gpu-agent
    image: ${GPU_WORKLOAD_IMAGE}
    readyz:
      httpGet:
        path: /readyz
        port: 80
  resources:
    limits:
      cpu: "1"
      memory: 2Gi
  snapshotsConfig:
    location: ${SNAPSHOT_LOCATION}
    onPause: Full
    onCommit: Full
EOF
```

```bash
kubectl -n ate-demo-gpu wait \
  --for=condition=Ready actortemplate/gpu-agent --timeout=15m
```

The same YAML lives in [`manifests/actortemplate.yaml`](manifests/actortemplate.yaml).

## 5. Create and resume the actor

Actors are control-plane records, not Kubernetes objects.

```bash
kubectl ate create atespace gpu-demo
kubectl ate create actor gpu-1 --atespace gpu-demo --template ate-demo-gpu/gpu-agent
kubectl ate resume actor gpu-1 --atespace gpu-demo --boot
kubectl ate logs actors gpu-1 --atespace gpu-demo
```

`--boot` cold-starts this actor so its logs include `nvidia-smi`. Without it,
resume restores the golden snapshot (the GPU probe already ran there).

## 6. Call the actor

```bash
kubectl -n ate-system port-forward svc/atenet-router 8000:80
```

```bash
curl -sS \
  -H 'Host: gpu-1.gpu-demo.actors.resources.substrate.ate.dev' \
  http://localhost:8000/

curl -sS \
  -H 'Host: gpu-1.gpu-demo.actors.resources.substrate.ate.dev' \
  http://localhost:8000/gpu
```

`/` is the boot-time probe (survives suspend). `/gpu` runs `nvidia-smi` now.

## Cleanup

```bash
kubectl ate delete actor gpu-1 --atespace gpu-demo --any-state
kubectl ate delete atespace gpu-demo
kubectl delete actortemplate gpu-agent -n ate-demo-gpu
kubectl delete workerpool gpu-workers -n ate-demo-gpu
kubectl delete namespace ate-demo-gpu
```

That does not delete GPU nodes, images, or snapshot objects. Review then
delete the prefix if you want it gone:

```bash
gcloud storage ls "gs://${BUCKET_NAME}/ate-demo-gpu/**"
gcloud storage rm --recursive "gs://${BUCKET_NAME}/ate-demo-gpu/"
```

## Troubleshooting

| Symptom | Check |
|---|---|
| Worker Pod Pending | GPU allocatable on the node, taint, `nvidia.com/gpu` in **requests and limits** |
| No atelet pod on the GPU node | Stock atelet does not tolerate `nvidia.com/gpu`. GKE GPU nodes use that taint. Patch the DaemonSet: `kubectl -n ate-system patch ds atelet --type=strategic -p '{"spec":{"template":{"spec":{"tolerations":[{"key":"nvidia.com/gpu","operator":"Exists","effect":"NoSchedule"}]}}}}'` |
| `nvidia-ctk cdi generate failed` | Toolkit at `/usr/local/nvidia/toolkit` on the node (gpu-operator). GKE's built-in GPU image often has no `nvidia-ctk`. Override with `ATE_NVIDIA_TOOLKIT_HOST_PATH` / `ATE_NVIDIA_DRIVER_ROOT` on `ate-controller` only if your layout differs |
| Template never Ready | Golden actor in `ate-golden`; ateom/atelet logs; probe fails if the GPU is missing |
| Suspend nvproxy error | A process still holds a CUDA context. This agent does not. |

gVisor only. `microvm` WorkerPools reject `nvidia.com/gpu`.

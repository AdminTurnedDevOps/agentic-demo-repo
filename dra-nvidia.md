# Kubernetes DRA with NVIDIA GPUs

Example walkthrough: **schedule** and **splice** (share / time-slice) NVIDIA GPUs via Dynamic Resource Allocation (DRA). The workloads in each section already exercise the GPU once scheduled.

DRA replaces opaque `nvidia.com/gpu: "1"` device-plugin counts with claim-based allocation: workloads declare what they need, the NVIDIA DRA driver publishes what exists, and the scheduler matches them.

| Concept | Role |
| --- | --- |
| **DeviceClass** | Named category of devices (e.g. `gpu.nvidia.com`). Installed by the driver. |
| **ResourceSlice** | Per-node inventory: GPUs, attributes (product, architecture), capacities (memory). |
| **ResourceClaim** | Workload demand for device(s). Can be shared across pods. |
| **ResourceClaimTemplate** | Factory: each pod gets its own claim (like a PVC template). |
| **GpuConfig** | NVIDIA opaque params on a claim: `TimeSlicing`, `MPS`, etc. |

References:

- [Kubernetes DRA](https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/)
- [NVIDIA DRA driver](https://github.com/kubernetes-sigs/dra-driver-nvidia-gpu) (`kubernetes-sigs/dra-driver-nvidia-gpu`)
- [GPU Operator DRA install](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/dra-intro-install.html)

---

## Mental model

```text
                    ┌─────────────────────┐
  Node GPUs  ──►    │ ResourceSlice       │  (inventory + attrs)
                    └─────────┬───────────┘
                              │
  DeviceClass gpu.nvidia.com  │  CEL selectors / firstAvailable
                              ▼
                    ┌─────────────────────┐
  Workload   ──►    │ ResourceClaim(s)    │  (demand + GpuConfig)
                    └─────────┬───────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         exclusive       share in pod    share across pods
         (template,      (1 claim,       (1 ResourceClaim,
          1:1 pod)        N containers)   N pods, TimeSlicing/MPS)
                              │
                              ▼
                    Pod scheduled → kubelet plugin prepares GPU → CDI injects
```

---

## Prerequisites

- Kubernetes **v1.36+** (DRA GA path; examples use `resource.k8s.io/v1`)
- Nodes with NVIDIA GPUs + driver (GPU Operator-managed or pre-installed). As long as you have nodes that have a GPU available (e.g - NVIDIA Tesla T4 GPU), the NVIDIA DRA Driver can see what nodes have that GPU available and if that GPU is free (not currently consumed), it'll pick it up and schedule the workloads to said node.
- NVIDIA DRA Driver for GPUs installed; GPU device plugin **disabled** when DRA owns allocation
- CDI enabled in the container runtime (GPU Operator configures this)

### Label GPU nodes

```bash
kubectl label node <gpu-node> nvidia.com/dra-kubelet-plugin=true
```

### Install sketch (GPU Operator + DRA driver)

Disable the classic device plugin so DRA owns GPU allocation:

```bash
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia
helm repo update

helm upgrade --install gpu-operator nvidia/gpu-operator \
  --version=v26.3.3 \
  --namespace gpu-operator --create-namespace \
  --set devicePlugin.enabled=false \
  --set driver.manager.env[0].name=NODE_LABEL_FOR_GPU_POD_EVICTION \
  --set driver.manager.env[0].value="nvidia.com/dra-kubelet-plugin"
```

`values-dra.yaml` for the DRA driver:

```yaml
image:
  pullPolicy: IfNotPresent
kubeletPlugin:
  nodeSelector:
    nvidia.com/dra-kubelet-plugin: "true"
```

```bash
helm upgrade -i dra-driver-nvidia-gpu nvidia/dra-driver-nvidia-gpu \
  --version=0.4.1 \
  --namespace nvidia-dra-driver-gpu --create-namespace \
  --set nvidiaDriverRoot=/run/nvidia/driver \
  --set gpuResourcesEnabledOverride=true \
  -f values-dra.yaml
```

> **GKE:** use `nvidiaDriverRoot: "/home/kubernetes/bin/nvidia"` and add GPU tolerations on the kubelet plugin (see NVIDIA docs).

### Validate

```bash
kubectl get pods -n nvidia-dra-driver-gpu
kubectl get deviceclass
kubectl get resourceslice
```

Expected DeviceClasses when GPU allocation is enabled:

```text
gpu.nvidia.com
mig.nvidia.com
```

Inspect what a node advertises:

```bash
kubectl get resourceslice -o yaml | less
# device.attributes: architecture, productName, uuid, ...
# device.capacity.memory: e.g. 16Gi, 23028Mi
```

---

## 1. Schedule — exclusive GPU per pod

Each pod gets its own claim via a **ResourceClaimTemplate**. Scheduler allocates a free GPU from `gpu.nvidia.com`.

Sidenote: No splice needed. Default is exclusive: one claim → one free GPU → pod scheduled there.

The goal here is to say "any NVIDIA GPUs available, schedule them"

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: dra-nvidia-demo
---
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata:
  name: single-gpu
  namespace: dra-nvidia-demo
spec:
  spec:
    devices:
      requests:
      - name: gpu
        exactly:
          deviceClassName: gpu.nvidia.com
          count: 1
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: exclusive-gpu
  namespace: dra-nvidia-demo
spec:
  replicas: 2
  selector:
    matchLabels:
      app: exclusive-gpu
  template:
    metadata:
      labels:
        app: exclusive-gpu
    spec:
      containers:
      - name: cuda
        image: ubuntu:22.04
        command: ["bash", "-c"]
        args:
        - |
          nvidia-smi -L
          trap 'exit 0' TERM
          sleep infinity & wait
        resources:
          claims:
          - name: gpu
      resourceClaims:
      - name: gpu
        resourceClaimTemplateName: single-gpu
      tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
```

```bash
kubectl apply -f exclusive-gpu.yaml
kubectl get resourceclaim -n dra-nvidia-demo
kubectl logs -n dra-nvidia-demo deploy/exclusive-gpu --all-pods
```

Each replica owns a distinct claim (`…-gpu-xxxxx`, state `allocated,reserved`). Two pods on a single-GPU node → second stays `Pending` until capacity frees.

---

## 2. Schedule with selectors (right GPU, not just any GPU)

CEL selectors match ResourceSlice attributes / capacity. Prefer a product, require memory, or ranked fallbacks with `firstAvailable`.

This is where you begin to make specific selections for GPUs. In this example, you're using CEL to say "I need a GPU with greater VRAM than 20Gi".

### Memory floor

```yaml
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata:
  name: gpu-gt-20gi
  namespace: dra-nvidia-demo
spec:
  spec:
    devices:
      requests:
      - name: gpu
        exactly:
          deviceClassName: gpu.nvidia.com
          selectors:
          - cel:
              expression: >-
                device.capacity["gpu.nvidia.com"].memory.isGreaterThan(quantity("20Gi"))
```

## 3. Prefer A Specific GPU

You can also pin to a specific GPU that you want to use. For example, pin this claim to Tesla T4 via the product name advertised on ResourceSlices.

Confirm the exact string in your cluster (`kubectl get resourceslice -o yaml`); it is usually `Tesla T4`.

```yaml
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata:
  name: prefer-tesla-t4
  namespace: dra-nvidia-demo
spec:
  spec:
    devices:
      requests:
      - name: gpu
        exactly:
          deviceClassName: gpu.nvidia.com
          selectors:
          - cel:
              expression: >-
                device.attributes["gpu.nvidia.com"].productName == "Tesla T4"
```

Optional: prefer T4, fall back to any free GPU if none is available:

```yaml
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata:
  name: prefer-tesla-t4
  namespace: dra-nvidia-demo
spec:
  spec:
    devices:
      requests:
      - name: gpu
        firstAvailable:
        - name: tesla-t4
          deviceClassName: gpu.nvidia.com
          selectors:
          - cel:
              expression: >-
                device.attributes["gpu.nvidia.com"].productName == "Tesla T4"
        - name: any-gpu
          deviceClassName: gpu.nvidia.com
```

Wire the pod the same way: `resourceClaims[].resourceClaimTemplateName: prefer-tesla-t4` and `resources.claims: [{name: gpu}]`.

---

## 4. Splice — share one GPU across containers (same pod)

One claim, multiple containers reference it. Both see the same UUID from `nvidia-smi`.

```yaml
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata:
  name: shared-gpu-in-pod
  namespace: dra-nvidia-demo
spec:
  spec:
    devices:
      requests:
      - name: gpu
        exactly:
          deviceClassName: gpu.nvidia.com
---
apiVersion: v1
kind: Pod
metadata:
  name: two-ctrs-one-gpu
  namespace: dra-nvidia-demo
spec:
  containers:
  - name: ctr0
    image: ubuntu:22.04
    command: ["bash", "-c"]
    args: ["nvidia-smi -L; trap 'exit 0' TERM; sleep infinity & wait"]
    resources:
      claims:
      - name: shared-gpu
  - name: ctr1
    image: ubuntu:22.04
    command: ["bash", "-c"]
    args: ["nvidia-smi -L; trap 'exit 0' TERM; sleep infinity & wait"]
    resources:
      claims:
      - name: shared-gpu
  resourceClaims:
  - name: shared-gpu
    resourceClaimTemplateName: shared-gpu-in-pod
  tolerations:
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
```

```bash
kubectl logs -n dra-nvidia-demo pod/two-ctrs-one-gpu --all-containers --prefix
# both containers print the same GPU UUID
```

---

## 5. Splice — share one GPU across pods (time-slicing)

**Key pattern:** use a single **ResourceClaim** (not a template). Many pods set `resourceClaimName` to that claim so they all reserve the same allocation.

NVIDIA `GpuConfig` sets sharing strategy to **TimeSlicing** (or **MPS**).

```yaml
apiVersion: resource.k8s.io/v1
kind: ResourceClaim
metadata:
  name: timesliced-gpu
  namespace: dra-nvidia-demo
spec:
  devices:
    requests:
    - name: ts-gpu
      exactly:
        deviceClassName: gpu.nvidia.com
    config:
    - requests: ["ts-gpu"]
      opaque:
        driver: gpu.nvidia.com
        parameters:
          apiVersion: resource.nvidia.com/v1beta1
          kind: GpuConfig
          sharing:
            strategy: TimeSlicing
            timeSlicingConfig:
              # Short | Default | Long — longer intervals reduce context-switch cost
              interval: Long
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ts-share
  namespace: dra-nvidia-demo
spec:
  replicas: 4
  selector:
    matchLabels:
      app: ts-share
  template:
    metadata:
      labels:
        app: ts-share
    spec:
      containers:
      - name: nbody
        image: nvcr.io/nvidia/k8s/cuda-sample:nbody-cuda11.6.0-ubuntu18.04
        command: ["bash", "-c"]
        args:
        - |
          trap 'exit 0' TERM
          /tmp/sample --benchmark --numbodies=4226000 &
          wait
        resources:
          claims:
          - name: gpu
      resourceClaims:
      - name: gpu
        # Same claim for every replica → true multi-pod share
        resourceClaimName: timesliced-gpu
      tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
```

```bash
kubectl apply -f timeslice.yaml
kubectl get resourceclaim -n dra-nvidia-demo timesliced-gpu
# STATE: allocated,reserved

kubectl describe resourceclaim -n dra-nvidia-demo timesliced-gpu
# Status.Reserved For lists all 4 pods
# Allocation shows Strategy: TimeSlicing
```

### Template vs shared claim

| Goal | Use |
| --- | --- |
| 1 GPU per pod (exclusive) | `ResourceClaimTemplate` + `resourceClaimTemplateName` |
| N pods on one GPU (share / splice) | One `ResourceClaim` + `resourceClaimName` on every pod |
| N containers in one pod on one GPU | One claim (template or claim) referenced by each container |

---

## 6. Splice — TimeSlicing + MPS on different requests

One claim template can request two devices with different sharing strategies (from upstream `gpu-test5`):

```yaml
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata:
  name: multi-share-mode
  namespace: dra-nvidia-demo
spec:
  spec:
    devices:
      requests:
      - name: ts-gpu
        exactly:
          deviceClassName: gpu.nvidia.com
      - name: mps-gpu
        exactly:
          deviceClassName: gpu.nvidia.com
      config:
      - requests: ["ts-gpu"]
        opaque:
          driver: gpu.nvidia.com
          parameters:
            apiVersion: resource.nvidia.com/v1beta1
            kind: GpuConfig
            sharing:
              strategy: TimeSlicing
              timeSlicingConfig:
                interval: Long
      - requests: ["mps-gpu"]
        opaque:
          driver: gpu.nvidia.com
          parameters:
            apiVersion: resource.nvidia.com/v1beta1
            kind: GpuConfig
            sharing:
              strategy: MPS
              mpsConfig:
                defaultActiveThreadPercentage: 50
                defaultPinnedDeviceMemoryLimit: 10Gi
```

Containers attach to a specific request:

```yaml
resources:
  claims:
  - name: shared-gpus
    request: ts-gpu   # or mps-gpu
```

---

## Quickstart

Lite end-to-end demo: claim a **Tesla T4**, schedule a Deployment, print GPU info from the pod.

Assumes Prerequisites are done (`deviceclass` / `resourceslice` present, DRA driver Running).

### 1. Apply

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: dra-nvidia-demo
---
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata:
  name: tesla-t4
  namespace: dra-nvidia-demo
spec:
  spec:
    devices:
      requests:
      - name: gpu
        exactly:
          deviceClassName: gpu.nvidia.com
          selectors:
          - cel:
              expression: >-
                device.attributes["gpu.nvidia.com"].productName == "Tesla T4"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tesla-t4-demo
  namespace: dra-nvidia-demo
spec:
  replicas: 1
  selector:
    matchLabels:
      app: tesla-t4-demo
  template:
    metadata:
      labels:
        app: tesla-t4-demo
    spec:
      containers:
      - name: cuda
        image: ubuntu:22.04
        command: ["bash", "-c"]
        args:
        - |
          set -e
          echo "=== GPU claim attached; listing devices ==="
          nvidia-smi -L
          echo "=== nvidia-smi summary ==="
          nvidia-smi
          echo "=== idle (delete the Deployment to free the T4) ==="
          trap 'exit 0' TERM
          sleep infinity & wait
        resources:
          claims:
          - name: gpu
      resourceClaims:
      - name: gpu
        resourceClaimTemplateName: tesla-t4
      tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
```

```bash
kubectl apply -f dra-nvidia-quickstart.yaml
```

### 2. Wait for schedule + claim

```bash
kubectl -n dra-nvidia-demo wait --for=condition=Available deploy/tesla-t4-demo --timeout=120s
kubectl -n dra-nvidia-demo get pods -o wide
kubectl -n dra-nvidia-demo get resourceclaim
# expect STATE: allocated,reserved
```

If the pod stays `Pending`:

```bash
kubectl -n dra-nvidia-demo describe pod -l app=tesla-t4-demo
# check productName on slices matches "Tesla T4"
kubectl get resourceslice -o yaml | grep -A1 productName
```

### 3. See output (GPU in use)

```bash
kubectl -n dra-nvidia-demo logs deploy/tesla-t4-demo
```

Expect something like:

```text
=== GPU claim attached; listing devices ===
GPU 0: Tesla T4 (UUID: GPU-…)
=== nvidia-smi summary ===
+-----------------------------------------------------------------------------+
| NVIDIA-SMI …                                                                |
|   0  Tesla T4            …                                                  |
+-----------------------------------------------------------------------------+
```

Or exec for a live view:

```bash
kubectl -n dra-nvidia-demo exec deploy/tesla-t4-demo -- nvidia-smi -L
```

### 4. Cleanup

```bash
kubectl delete ns dra-nvidia-demo
```

---

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Pod `Pending`: cannot allocate claims | Free GPUs? `kubectl get resourceslice`, competing claims, CEL too strict |
| Claim stuck `pending` | No consumer yet, or no matching device on any Ready node |
| `nvidia-smi` missing in container | DRA plugin not preparing device; claim not mounted via `resources.claims` |
| Classic `nvidia.com/gpu` + DRA both used | Enable DRA extended-resource path (K8s ≥1.36 default) or pick one model |
| Driver upgrade leaves plugin stuck | Node label `nvidia.com/dra-kubelet-plugin=true` + GPU Operator eviction env |

```bash
kubectl describe pod -n dra-nvidia-demo <pod>
kubectl describe resourceclaim -n dra-nvidia-demo <claim>
kubectl logs -n nvidia-dra-driver-gpu -l app.kubernetes.io/name=dra-driver-nvidia-gpu
```
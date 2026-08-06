---
title: "Agent Substrate: Enable and Use the MicroVM Sandbox Class on GKE"
date: 2026-08-04
description: >
  Hands-on GKE lab for turning on Substrate's microvm sandbox class (Kata +
  Cloud Hypervisor via ateom-microvm), staging runtime assets to GCS, deploying
  a microVM WorkerPool and ActorTemplate, and proving guest-memory
  suspend/resume across workers. Distinct from standalone Kata RuntimeClass
  pod isolation.
tags: [agent-substrate, gke, microvm, kata, cloud-hypervisor, sandboxclass, suspend-resume]
author: Michael Levan
---

# MicroVM on Agent Substrate (GKE)

Tldr; Substrate can run actors inside a **micro-VM** instead of gVisor. Same
control plane (actors, workers, atenet, suspend/resume) — different
`sandboxClass`, different `ateom`, and a content-addressed toolchain that
atelet fetches from **GCS** at runtime.

This lab is **not** the standalone Kata / RuntimeClass path in
[`standalone-setup.md`](standalone-setup.md) (whole Pods inside microVMs).
Here the microVM is Substrate's **actor sandbox** on a worker pod:
`sandboxClass: microvm` + `ateom-microvm` + Cloud Hypervisor guest on **GKE**.

## What this lab proves

| Beat | Proof |
|---|---|
| MicroVM is a first-class sandbox class | `WorkerPool` + `ActorTemplate` with `sandboxClass: microvm` schedule only onto matching pools |
| Toolchain is not baked into the worker image | `SandboxConfig` assets staged to `gs://$BUCKET_NAME/kata-assets/`; atelet fetches them |
| Guest memory survives teleport | In-RAM counter continues after suspend + resume on another worker |

## What Substrate pieces this uses

| Concept | Where it lives |
|---|---|
| `sandboxClass: microvm` | `WorkerPool.spec` and `ActorTemplate.spec` — hard scheduling gate; snapshots are **not** portable across gVisor ↔ microVM |
| `SandboxConfig` | Cluster-scoped CR; pins microVM asset URLs + sha256 per arch |
| `ateom-microvm` | Herder image in the worker pod; drives Kata agent + Cloud Hypervisor (no containerd kata shim) |
| Runtime assets | `cloud-hypervisor`, `virtiofsd`, `vmlinux`, `rootfs.img`, `configuration-clh.toml` under `gs://$BUCKET_NAME/kata-assets/` |
| Node placement | Controller mounts `/dev/kvm` and selects nodes labeled `ate.dev/sandboxClass=microvm` |
| Counter microVM demo | `demos/counter/counter-microvm.yaml.tmpl` + `hack/run-microvm-demo.sh` |

### gVisor vs microVM tldr;

Tldr; gVisor is software/kernel (`ateom-gvisor`) isolation and microVM is
hardware isolation/virtualization via a process (`ateom-microvm` + VMM) in the
Worker. Both run as Actor Sandboxes inside Worker Pods.

```text
gVisor (default)          microVM
─────────────────         ─────────────────────────────
ateom-gvisor              ateom-microvm
runsc asset               VMM + guest kernel/rootfs set
process C/R               guest memory snapshot (+ durable dirs over virtio-fs)
no /dev/kvm required      needs KVM / nested virt + node label
```

---

## Prerequisites

- **GKE Standard** cluster (not Autopilot — workers need privileged / hostPath
  and `/dev/kvm`).
- A Node Pool that supports nested virtualization (e.g - `n2-standard-4`)
- Substrate checkout: work from `substrate/substrate` (the nested upstream
  tree) with a current `main` pull.
- Substrate installed: Follow [setup](../setup.md)
- Confirm control-plane basics if you already installed:
```bash
source .ate-dev-env.sh
kubectl get pods -n ate-system
```

- Run the following to ensure that theres a `sandboxClass` label on the nodes available so the node can be enabled with MicroVM.
```bash
kubectl get nodes -L ate.dev/sandboxClass
```

---

## Enabling microVM

Run the following command to get the sandbox configuration. By default, expect gVisor to be the default from a normal install

```bash
kubectl get sandboxconfig
```

The next step is to set `ate.dev/sandboxClass=microvm` on the nodes that will host microVM Workers (add at pool create, or kubectl label existing nodes). That placement label is what the prereq check looks for. It does not replace gVisor as the cluster default sandbox class.

### Enable At Node Creation Time

Label at node-pool create time (preferred):

```bash
# include when creating/updating the pool:
#   --node-labels=ate.dev/sandboxClass=microvm
#   --enable-nested-virtualization   # where supported for your machine type
```

### Label Existing Nodes

```bash
kubectl get nodes
```

```bash
kubectl label node <NODE_NAME> ate.dev/sandboxClass=microvm
```

---

## Actor Deployment Architecture

Because there are going to be Actors that use MicroVM instead of gVisor, the first thing you may think is "do I need to specify the node to deploy to when creating an Actor?" and the answer is no. Actors are not scheduled onto nodes directly. Instead, the class is chosen via the template and matching pool.

1. `SandboxConfig`
2. `WorkerPool`
3. `ActorTemplate`

```
Actor --template--> ActorTemplate (sandboxClass: microvm)
                         |
                         v
                    WorkerPool (sandboxClass: microvm)
                         |
                         v
              worker pods → nodes labeled ate.dev/sandboxClass=microvm
```

Example:

```yaml
apiVersion: ate.dev/v1alpha1
kind: SandboxConfig
metadata:
  name: my-microvm   # any name
spec:
  sandboxClass: microvm
  # default: true   # optional; at most one default per class
  assets:
    amd64:   # or arm64 — must match nodes
      cloud-hypervisor:
        url: "gs://${BUCKET_NAME}/kata-assets/cloud-hypervisor"
        sha256: "<sha>"
      virtiofsd:
        url: "gs://${BUCKET_NAME}/kata-assets/virtiofsd"
        sha256: "<sha>"
      kata-kernel:
        url: "gs://${BUCKET_NAME}/kata-assets/vmlinux"
        sha256: "<sha>"
      kata-image:
        url: "gs://${BUCKET_NAME}/kata-assets/rootfs.img"
        sha256: "<sha>"
      kata-config:
        url: "gs://${BUCKET_NAME}/kata-assets/configuration-clh.toml"
        sha256: "<sha>"
---
apiVersion: ate.dev/v1alpha1
kind: WorkerPool
metadata:
  name: my-microvm-pool
  namespace: my-ns
  labels:
    workload: my-microvm   # optional; for workerSelector
spec:
  replicas: 2
  sandboxClass: microvm
  sandboxConfigName: my-microvm          # points at #1
  ateomImage: ko://github.com/agent-substrate/substrate/cmd/ateom-microvm
---
apiVersion: ate.dev/v1alpha1
kind: ActorTemplate
metadata:
  name: my-app
  namespace: my-ns
spec:
  sandboxClass: microvm                  # must match pool
  pauseImage: "registry.k8s.io/pause:3.10.2@sha256:..."  # as in demos
  containers:
  - name: app
    image: <your-workload-image>
    readyz:
      httpGet:
        path: /readyz   # whatever your app exposes
        port: 80
  workerSelector:                        # optional but usual
    matchLabels:
      workload: my-microvm
  snapshotsConfig:
    location: gs://${BUCKET_NAME}/my-app/
```

Then, to deploy an Actor, specify the template that has the microVM sandbox class:

```bash
kubectl ate create atespace demo   # if needed
kubectl ate create actor my-actor-1 -a demo --template my-ns/my-app
```

The template already has `sandboxClass: microvm`, so Substrate only uses microVM pools. Those pools' workers are already constrained to microVM-labeled nodes.

### Use the upstream MicroVM demo

There's a MicroVM demo under `demos/counter/counter-microvm.yaml.tmpl` that deploys the same configs you see above (namespace, SandboxConfig, WorkerPool, ActorTemplate) if you don't want to manually create one yourself.

Run the following from the **substrate** repo root:

**Sidenote:** this is what it does:
- **`assemble.sh`** — Download/build the microVM runtime binaries for `amd64` into `bin/microvm-assets/amd64/` (`cloud-hypervisor`, `virtiofsd`, guest kernel, rootfs, config). Local only; nothing is applied to the cluster yet.
- **`stage-to-gcs.sh`** — Upload those binaries to `gs://$BUCKET_NAME/kata-assets/` so atelet can fetch them when workers start.
- **`VIRTIOFSD_SHA256=...`** — Compute the sha256 of the staged `virtiofsd` binary so the SandboxConfig pin matches what was uploaded.
- **`sed ... counter-microvm.yaml.tmpl`** — Substitute `$BUCKET_NAME` and the virtiofsd hash into the demo template (namespace, SandboxConfig, WorkerPool, ActorTemplate).
- **`ko apply`** — Build/push any `ko://` images in that manifest (e.g. `ateom-microvm`, counter workload) to your registry and apply the rendered YAML to the cluster. The images need to be built/pushed for the microvm demo so the Actor can access them

```bash
source .ate-dev-env.sh

OUT="$PWD/bin/microvm-assets/amd64"

VIRTIOFSD_SHA256="$(sha256sum "${OUT}/virtiofsd" | awk '{print $1}')"
echo "sha=$VIRTIOFSD_SHA256"

sed -e "s|\${BUCKET_NAME}|${BUCKET_NAME}|g" \
    -e "s|\${VIRTIOFSD_SHA256}|${VIRTIOFSD_SHA256}|g" \
    demos/counter/counter-microvm.yaml.tmpl \
  | ./hack/run-tool.sh ko apply -f - -- --context="${KUBECTL_CONTEXT}"
```

Wait for **Ready** before creating an Actor (golden snapshot):

```bash
kubectl wait --for=condition=Ready \
  actortemplate/counter-microvm -n ate-demo-counter-microvm --timeout=600s
```

Then create an actor from that template and hit it through atenet-router:

```bash
kubectl ate create atespace demo

kubectl ate create actor my-counter-1 -a demo \
  --template ate-demo-counter-microvm/counter-microvm

kubectl -n ate-system port-forward svc/atenet-router 8000:80
```

In another terminal:

```bash
curl -s -X POST \
  -H "Host: my-counter-1.demo.actors.resources.substrate.ate.dev" \
  http://localhost:8000/
```

---

## Understand the asset model

Nothing Kata-specific is baked into the worker image. On first use, **atelet**
pulls the microVM toolchain from **GCS** into the node cache using the
`SandboxConfig` entries.

Asset set (assembled by `hack/microvm-assets/assemble.sh`):

| File | Role |
|---|---|
| `cloud-hypervisor` | VMM |
| `virtiofsd` | Serves OCI rootfs lower into the guest (virtio-fs) |
| `vmlinux` | Guest kernel |
| `rootfs.img` | Guest rootfs image |
| `configuration-clh.toml` | Base Kata/CLH config |

**Arch note:** assets are **single-arch** (unlike runsc's dual amd64/arm64
pins in one config). Stage and pin shas for the **GKE node** architecture.
Your `.ate-dev-env.sh` often sets `KO_DEFAULTPLATFORMS=linux/amd64` even when
the laptop is arm64 — match **nodes**, not the laptop.

---

## Step 3 — Manual path (same pieces, explicit)

Use this when you already have a healthy control plane and only want the
microVM demo layer.

### 3a. Assemble assets

On a machine that can build/fetch for the **node** arch:

```bash
# Typical GKE nodes are amd64
ARCH=amd64 OUT="$PWD/bin/microvm-assets/amd64" hack/microvm-assets/assemble.sh
```

### 3b. Stage to the GCS snapshot bucket

```bash
OUT="$PWD/bin/microvm-assets/amd64" BUCKET="$BUCKET_NAME" hack/microvm-assets/stage-to-gcs.sh
# objects land under gs://${BUCKET_NAME}/kata-assets/
```

### 3c. Apply the microVM WorkerPool + template

`run-microvm-demo.sh` is preferred because it rewrites `${VIRTIOFSD_SHA256}`
when the binary is not byte-reproducible. On amd64, committed pins usually
match the prebuilt binary.

```bash
VIRTIOFSD_SHA256="$(sha256sum bin/microvm-assets/${ARCH}/virtiofsd | awk '{print $1}')"
sed -e "s|\${BUCKET_NAME}|${BUCKET_NAME}|g" \
    -e "s|\${VIRTIOFSD_SHA256}|${VIRTIOFSD_SHA256}|g" \
    demos/counter/counter-microvm.yaml.tmpl \
  | ./hack/run-tool.sh ko apply -f -
```

That creates:

- Namespace `ate-demo-counter-microvm`
- `SandboxConfig/counter-microvm` (`sandboxClass: microvm`)
- `WorkerPool/counter-microvm` (`replicas: 2`, `ateomImage: .../ateom-microvm`)
- `ActorTemplate/counter-microvm` (`sandboxClass: microvm`)

Wait for the golden snapshot:

```bash
kubectl wait --for=condition=Ready \
  actortemplate/counter-microvm -n ate-demo-counter-microvm --timeout=600s
```

Inspect:

```bash
kubectl get sandboxconfig counter-microvm -o yaml
kubectl get workerpool -n ate-demo-counter-microvm
kubectl get pods -n ate-demo-counter-microvm -o wide
# workers should land on nodes labeled ate.dev/sandboxClass=microvm
```

---

## Step 4 — Create an actor and hit it through atenet

Same client path as gVisor actors: **atenet-router** (Envoy or agentgateway)
+ Host header. Sandbox class does not change actor DNS.

```bash
go install ./cmd/kubectl-ate   # if needed
export PATH="$(go env GOPATH)/bin:$PATH"

kubectl ate create atespace demo
kubectl ate create actor my-counter-1 -a demo \
  --template ate-demo-counter-microvm/counter-microvm

kubectl ate get actor my-counter-1 -a demo
```

Port-forward the router and increment the in-RAM counter:

```bash
kubectl -n ate-system port-forward svc/atenet-router 8000:80
```

In another terminal:

```bash
for i in 1 2 3; do
  curl -s -X POST \
    -H "Host: my-counter-1.demo.actors.resources.substrate.ate.dev" \
    http://localhost:8000/
  echo
done
```

Note the count (and worker assignment from `kubectl ate get actor`).

---

## Step 5 — Prove guest-memory suspend / resume

The counter lives in **guest RAM**. Continuing the count after suspend +
resume (especially on another worker) proves the microVM memory snapshot
round-tripped.

```bash
# Capture worker before suspend
kubectl ate get actor my-counter-1 -a demo

kubectl ate suspend actor my-counter-1 -a demo
kubectl ate get actor my-counter-1 -a demo
# expect STATUS_SUSPENDED; worker released

# Resume (traffic through the router also resumes on demand)
kubectl ate resume actor my-counter-1 -a demo
# or just curl again through atenet-router

kubectl ate get actor my-counter-1 -a demo
# note worker pod — ideally a different pod than before if pool has capacity

curl -s -X POST \
  -H "Host: my-counter-1.demo.actors.resources.substrate.ate.dev" \
  http://localhost:8000/
```

If the count continues from where you left off, microVM checkpoint/restore
worked.

---

#### How the pieces connect (the overall architecture)

```text
Client
  -> atenet-router (Envoy or agentgateway)
  -> ResumeActor / worker assignment
  -> mTLS to atunnel on worker :443
  -> ateom-microvm
       boots Cloud Hypervisor guest (assets from SandboxConfig / GCS)
       actor process inside guest
```

Controller behavior for `sandboxClass: microvm` workers:

- Mount host `/dev/kvm` into the worker
- `nodeSelector: ate.dev/sandboxClass=microvm` (+ matching toleration)

Actor template rules that differ from gVisor:

- Multiple `durableDir` volumes allowed (microVM shares one virtio-fs upper)  
- `externalVolumeTemplate` remains **gVisor-only**  
- Class is **immutable** on the template; no cross-class restore  

---

## Cleanup

```bash
# Actors first (must be suspended for delete)
kubectl ate suspend actor my-counter-1 -a demo 2>/dev/null || true
kubectl ate delete actor my-counter-1 -a demo
kubectl ate delete atespace demo

# Demo CRs / namespace
kubectl delete -n ate-demo-counter-microvm \
  actortemplate counter-microvm \
  workerpool counter-microvm --ignore-not-found
kubectl delete sandboxconfig counter-microvm --ignore-not-found
kubectl delete ns ate-demo-counter-microvm --ignore-not-found
```

Leaving the core `ate-system` install intact is fine; microVM is additive.

To tear down the whole platform:

```bash
./hack/install-ate.sh --delete-ate-system
```

Optional: remove staged assets from GCS if you no longer need them:

```bash
gcloud storage rm -r "gs://${BUCKET_NAME}/kata-assets/" || true
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Worker pods `Pending` | Nodes labeled `ate.dev/sandboxClass=microvm`? Nested virt / `/dev/kvm` on the GKE pool? |
| `SandboxConfig` rejected on apply | Full asset map for the arch; admission policy requires the microVM file set |
| Golden snapshot never Ready | atelet logs; GCS object URLs reachable from nodes (WI / bucket IAM); sha256 matches staged bytes |
| Resume hang / wrong count | Asset version skew (virtiofsd ≥ v1.14.0 for snapshot fix); don't mix gVisor and microVM templates for the same actor |
| Built images wrong arch | `KO_DEFAULTPLATFORMS` vs node arch; re-assemble with `ARCH=amd64` (typical GKE) to match nodes |

Debugging:

```bash
kubectl -n ate-system logs daemonset/atelet --tail=100
kubectl -n ate-demo-counter-microvm get pods -o wide
kubectl -n ate-demo-counter-microvm describe pods
```

---

## How this differs from `standalone-setup.md`

| | Standalone microVM lab | This lab (Substrate on GKE) |
|---|---|---|
| Goal | Pod-level isolation via Kata RuntimeClass | Actor sandbox class inside Substrate workers |
| API | `runtimeClassName: kata-*` on Pods | `sandboxClass: microvm` on WorkerPool / ActorTemplate |
| Lifecycle | Normal Pod start/stop | Suspend / resume / multiplex / atenet wake |
| Toolchain | Cluster containerd + Kata install | `SandboxConfig` assets from GCS via atelet |
| Ingress | Normal Service / Gateway | Actor DNS → atenet-router → atunnel |

Use **standalone** when you want every Kubernetes Pod in a VM. Use **this lab**
when you want Substrate actors with VM-grade isolation and the same actor
lifecycle as gVisor.

---

## References (upstream in this repo)

- `substrate/hack/run-microvm-demo.sh`
- `substrate/hack/microvm-assets/` (especially `stage-to-gcs.sh`)
- `substrate/demos/counter/counter-microvm.yaml.tmpl`
- `substrate/docs/api-guide.md` (SandboxConfig, sandboxClass)
- `substrate/docs/architecture.md` (sandbox classes)
- Counter demo notes: `substrate/demos/counter/README.md` (Micro-VM variant)
- GKE control-plane setup: [`../setup.md`](../setup.md)

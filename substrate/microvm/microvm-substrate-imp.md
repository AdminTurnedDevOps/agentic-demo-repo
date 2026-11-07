---
title: "Agent Substrate: Enable and Use the MicroVM Sandbox Class on GKE"
date: 2026-08-04
description: >
  Hands-on GKE lab for turning on Substrate's microvm sandbox class (Kata +
  Cloud Hypervisor via ateworker-microvm), staging runtime assets to GCS, deploying
  a microVM WorkerPool and ActorTemplate, and proving guest-memory
  suspend/resume across workers. Distinct from standalone Kata RuntimeClass
  pod isolation.
tags: [agent-substrate, gke, microvm, kata, cloud-hypervisor, sandboxclass, suspend-resume]
author: Michael Levan
---

# MicroVM on Agent Substrate (GKE)

Tldr; Substrate can run actors inside a **micro-VM** instead of gVisor. Same
control plane (actors, workers, atenet, suspend/resume) — different
sandbox class on the `WorkerPool`, different `ateworker`, and a
content-addressed toolchain that atelet fetches from **GCS** at runtime.

This lab is **not** the standalone Kata / RuntimeClass path in
[`standalone-setup.md`](standalone-setup.md) (whole Pods inside microVMs).
Here the microVM is Substrate's **actor sandbox** on a worker pod:
`sandboxClasses: [{name: microvm}]` + `ateworker-microvm` + Cloud Hypervisor
guest on **GKE**.

## What this lab proves

| Beat | Proof |
|---|---|
| MicroVM is a first-class sandbox class | A `WorkerPool` with `sandboxClasses: [{name: microvm}]`, and an `ActorTemplate` whose `workerSelector` points only at that pool |
| Toolchain is not baked into the worker image | `SandboxConfig` assets staged to `gs://${BUCKET_NAME}-assets/microvm-assets/<arch>/<sha256>`; atelet fetches them |
| Guest memory survives teleport | In-RAM counter continues after suspend + resume on another worker |

## What Substrate pieces this uses

| Concept | Where it lives |
|---|---|
| Sandbox class | `WorkerPool.spec.sandboxClasses[].name` (`gvisor` or `microvm`, exactly one per pool). The `ActorTemplate` has no class field: it picks pools with `workerSelector`. An actor's first snapshot records the class, and every later restore stays on it; snapshots are **not** portable across gVisor ↔ microVM |
| `SandboxConfig` | Cluster-scoped CR (`ate.dev/v1`); pins microVM asset URLs + sha256 per arch, per version. `deploy ate-system` installs one named `microvm` as the class default |
| `ateworker-microvm` | Worker image in the worker pod; drives the Kata guest + Cloud Hypervisor directly (no containerd kata shim) |
| Runtime assets | `cloud-hypervisor`, `virtiofsd`, `vmlinux` (`kata-kernel`), `rootfs.img` (`kata-image`) under `gs://${BUCKET_NAME}-assets/microvm-assets/<arch>/` |
| Node placement | Controller requests the `ate.dev/kvm` device that atelet advertises on nodes with `/dev/kvm`. A `ate.dev/sandboxClass=microvm:NoSchedule` taint is optional |
| Counter microVM demo | `demos/counter/counter-microvm.yaml.tmpl` + `counter-microvm-template.yaml.tmpl`, deployed with `go run ./cmd/ate-setup deploy demo counter-microvm` |

### gVisor vs microVM tldr;

Tldr; gVisor is software/kernel (`ateworker-gvisor`) isolation and microVM is
hardware isolation/virtualization via a process (`ateworker-microvm` + VMM) in the
Worker. Both run as Actor Sandboxes inside Worker Pods.

```text
gVisor (default)          microVM
─────────────────         ─────────────────────────────
ateworker-gvisor          ateworker-microvm
runsc asset               VMM + guest kernel/rootfs set
process C/R               guest memory snapshot (+ durable dirs over virtio-fs)
no /dev/kvm required      needs KVM / nested virt (ate.dev/kvm device)
```

---

## Prerequisites

- **GKE Standard** cluster, **GKE 1.37+** (not Autopilot — workers need
  `/dev/kvm`, and atelet is privileged + `hostPath`). Provisioning moved out of
  the Substrate repo into
  [substrate-gke](https://github.com/ai-on-gke/substrate-gke):
  `go -C tools/setup-gcp run . bootstrap` (or `create cluster|bucket|iam`).
  For v1.0.0 pass `--atelet-snapshot-access=false` to `create iam`. Manual
  path: [manual-gke-setup.md](https://github.com/ai-on-gke/substrate-gke/blob/main/docs/manual-gke-setup.md).
- A Node Pool that supports nested virtualization (e.g - `n2-standard-4`)
- Substrate checkout of the **v1.0.0 tag** (not `main`):
```bash
git clone --branch v1.0.0 https://github.com/agent-substrate/substrate.git
cd substrate
```
- Buckets: `create bucket` makes the snapshot bucket (`BUCKET_NAME`) and the
  asset bucket (`${BUCKET_NAME}-assets`). atelet no longer has snapshot-bucket
  access; snapshot transfers use per-actor tokens from ate-api-server's
  credential exchange, running as the `SNAPSHOT_TRANSFER_GSA_NAME` service
  account (`ate-snapshot-transfer` by default, created by `create iam`).
- Substrate installed with `ate-setup` (both sandbox classes are the default):
```bash
export PROJECT_ID=<project>
export BUCKET_NAME=<snapshot-bucket>
export SNAPSHOT_LOCATION="gs://${BUCKET_NAME}/"
export SNAPSHOT_TRANSFER_GSA_NAME=ate-snapshot-transfer
export KO_DOCKER_REPO=<registry your cluster pulls from>   # deploy demo builds with ko

go run ./cmd/ate-setup deploy ate-system \
  --credential-provider='{"name":"k8s.io"}' \
  --ingress-allowed-spiffe-ids=spiffe://cluster.local/ns/ate-system/sa/atenet-client \
  --image-repo ghcr.io/agent-substrate/substrate --image-tag v1.0.0
```
  The SPIFFE ID is what `kubectl ate proxy actor` presents to the router.
  Leave out `--image-repo`/`--image-tag` to build the control plane with `ko`.
- `kubectl-ate` from the same checkout (`go install ./cmd/kubectl-ate`)
- Confirm control-plane basics if you already installed:
```bash
kubectl get pods -n ate-system
```

- Confirm which nodes can host microVM workers. atelet advertises the
  `ate.dev/kvm` device on nodes that have `/dev/kvm`; empty means no KVM:
```bash
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.capacity.ate\.dev/kvm}{"\n"}{end}'
```

---

## Enabling microVM

Run the following command to get the sandbox configuration. A default
v1.0.0 install (`--sandbox-classes=gvisor,microvm`) creates both
`gvisor-default` and `microvm`.

```bash
kubectl get sandboxconfig
```

If `microvm` is missing (the cluster was installed with
`--sandbox-classes=gvisor`), add it. Pass the same settings as the original
install, or the install record with `--config`:

```bash
go run ./cmd/ate-setup deploy sandboxconfig --sandbox-classes=gvisor,microvm
```

That assembles the guest assets for `amd64` and `arm64`, stages them to
`gs://${BUCKET_NAME}-assets/microvm-assets/<arch>/<sha256>`, and applies the
cluster-wide `microvm` `SandboxConfig`.

Node placement no longer depends on a label. The controller requests the
`ate.dev/kvm` device on microVM worker pods, and atelet only advertises it
where `/dev/kvm` exists, so the nodes need nested virtualization. That is the
whole requirement. Reserving those nodes for microVM workers is optional: taint
them `ate.dev/sandboxClass=microvm:NoSchedule`, which microVM worker pods
tolerate. It does not change gVisor as the cluster default sandbox class.

### Enable At Node Creation Time

Enable nested virtualization (and optionally the taint) at node-pool create time (preferred):

```bash
# include when creating/updating the pool:
#   --enable-nested-virtualization   # where supported for your machine type
#   --node-taints=ate.dev/sandboxClass=microvm:NoSchedule   # optional: reserve the pool
```

### Taint Existing Nodes (optional)

```bash
kubectl get nodes
```

```bash
kubectl taint node <NODE_NAME> ate.dev/sandboxClass=microvm:NoSchedule
```

---

## Actor Deployment Architecture

Because there are going to be Actors that use MicroVM instead of gVisor, the first thing you may think is "do I need to specify the node to deploy to when creating an Actor?" and the answer is no. Actors are not scheduled onto nodes directly. Instead, the class is chosen by the pool, and the template picks the pool.

1. `SandboxConfig` (cluster-scoped CR; `microvm` already installed)
2. `WorkerPool` (namespaced CR)
3. `ActorTemplate` (**not a CRD**: a Substrate API record in an atespace, created with `kubectl ate create actor-template`)

```
Actor --template--> ActorTemplate (workerSelector: workload=my-microvm)
                         |
                         v
                    WorkerPool (labels: workload=my-microvm, sandboxClasses: [microvm])
                         |
                         v
              worker pods → nodes advertising ate.dev/kvm
```

Example. A custom `SandboxConfig` is optional; without `configRef` a pool uses
the class default (`microvm`). Its shape, if you pin your own asset set:

```yaml
apiVersion: ate.dev/v1
kind: SandboxConfig
metadata:
  name: my-microvm   # any name
  # annotations:
  #   sandboxconfig.ate.dev/is-class-default: "true"   # optional
spec:
  sandboxClass: microvm
  defaultVersion: v1
  versions:
  - name: v1
    assets:
      amd64:   # and/or arm64 — must cover your nodes
        cloud-hypervisor:
          url: "gs://${BUCKET_NAME}-assets/microvm-assets/amd64/<sha>"
          sha256: "<sha>"
        virtiofsd:
          url: "gs://${BUCKET_NAME}-assets/microvm-assets/amd64/<sha>"
          sha256: "<sha>"
        kata-kernel:
          url: "gs://${BUCKET_NAME}-assets/microvm-assets/amd64/<sha>"
          sha256: "<sha>"
        kata-image:
          url: "gs://${BUCKET_NAME}-assets/microvm-assets/amd64/<sha>"
          sha256: "<sha>"
```

The pool (`kubectl apply`; use `ko apply` if you keep the `ko://` image):

```yaml
apiVersion: ate.dev/v1
kind: WorkerPool
metadata:
  name: my-microvm-pool
  namespace: my-ns
  labels:
    workload: my-microvm   # what the template's workerSelector matches
spec:
  replicas: 2
  sandboxClasses:
  - name: microvm
    configRef:
      name: microvm          # or my-microvm; omit for the class default
  workerImage: ghcr.io/agent-substrate/substrate/ateworker-microvm:v1.0.0
  # or: ko://go.ate.dev/substrate/cmd/ateworker-microvm
  template:
    resources:
      limits:
        cpu: "1"
        memory: 1Gi
```

The template (protojson YAML, `my-app.yaml`). Images must be pinned by digest:

```yaml
metadata:
  atespace: demo
  name: my-app
containers:
- name: app
  image: <your-workload-image>@sha256:...
  wakeupProbe:
    httpGet:
      path: /readyz   # whatever your app exposes
      port: 80
workerSelector:
  matchLabels:
    workload: my-microvm
resources:
  limits:
    cpuMillicores: 1000
    memoryBytes: 536870912   # 512Mi; microVM minimum is 128Mi
snapshotConfig:
  preferredFidelity: SNAPSHOT_FIDELITY_MEMORY
```

Snapshots go to the cluster-wide `SNAPSHOT_LOCATION`; there is no per-template
bucket path any more (that is a preview field behind `PerTemplateSnapshotLocation`).

Then, to deploy an Actor, create the atespace and template, and create the actor from the template:

```bash
kubectl ate create atespace demo   # if needed
kubectl ate create actor-template -f my-app.yaml
kubectl ate create actor my-actor-1 -a demo --template my-app
```

`--template` takes the template **name**, resolved in the actor's atespace.
The template's `workerSelector` only matches the microVM pool, so Substrate
only uses microVM workers, and those workers only land on KVM-capable nodes.

### Use the upstream MicroVM demo

There's a MicroVM demo under `demos/counter/` (`counter-microvm.yaml.tmpl` for the namespace + WorkerPool, `counter-microvm-template.yaml.tmpl` for the ActorTemplate) that deploys the same configs you see above if you don't want to manually create one yourself.

Run the following from the **substrate** repo root (v1.0.0 checkout):

**Sidenote:** this is what it does:
- **Builds the counter image with `ko`** — releases don't publish demo images, so run it **without** `--image-repo` and with `KO_DOCKER_REPO` set.
- **Applies `counter-microvm.yaml.tmpl`** — namespace `ate-demo-counter-microvm` and the `counter-microvm` WorkerPool (`workerImage: ko://go.ate.dev/substrate/cmd/ateworker-microvm`, `configRef: microvm`), then waits for the workers.
- **Creates the `ate-demo-counter-microvm` atespace** and the `counter-microvm` ActorTemplate through the Substrate API.
- **Waits for the golden snapshot.** The guest assets were already staged by `deploy ate-system`; there's no separate assemble/stage step any more.

```bash
go run ./cmd/ate-setup deploy demo counter-microvm
```

Check the golden snapshot (the `GOLDEN TAG` column is set once it is ready; `ERROR` means the build failed, `-o yaml` shows why):

```bash
kubectl ate get actor-templates -a ate-demo-counter-microvm
```

Then create an actor from that template and reach it through atenet-router. The template lives in the `ate-demo-counter-microvm` atespace, so the actor does too:

```bash
kubectl ate create actor my-counter-1 -a ate-demo-counter-microvm \
  --template counter-microvm
```

```bash
kubectl ate proxy actor my-counter-1 -a ate-demo-counter-microvm
```

`kubectl ate proxy actor` serves `127.0.0.1:8000` and forwards it to actor
port 80 over the router's mTLS CONNECT listener, routing by
`ate-target-actor: ate-demo-counter-microvm/my-counter-1`. The old
`<actor>.<atespace>.actors.resources.substrate.ate.dev` Host header routing is
gone, and so is the plain-HTTP router port.

In another terminal:

```bash
curl -s -X POST http://localhost:8000/
```

You'll see an output similar to the below:
```
preserved memory count: 1 | preserved file counter: 1 | preserved rootfs counter: 1
```

---

#### Understand the asset model

Nothing Kata-specific is baked into the worker image. On first use, **atelet**
pulls the microVM toolchain from **GCS** into the node cache using the
`SandboxConfig` entries, through the node's object-store plugin. On GKE that
plugin can only read the asset bucket, `${BUCKET_NAME}-assets`.

Asset set (assembled and staged by `ate-setup deploy ate-system` / `deploy sandboxconfig`, pinned in `manifests/ate-install/sandboxconfig-microvm.yaml.tmpl`):

| File | `SandboxConfig` asset | Role |
|---|---|---|
| `cloud-hypervisor` | `cloud-hypervisor` | VMM |
| `virtiofsd` | `virtiofsd` | Serves OCI rootfs lower into the guest (virtio-fs) |
| `vmlinux` | `kata-kernel` | Guest kernel |
| `rootfs.img` | `kata-image` | Guest rootfs image |

There is no `configuration-clh.toml` any more; `ateworker-microvm` boots
Cloud Hypervisor itself.

**Arch note:** on GKE, `ate-setup` stages both `amd64` and `arm64` and the
`microvm` config pins both, so mixed-arch node pools work. The pools one
template selects must still share a CPU architecture, since a memory snapshot
only restores on the arch it was taken on.

---

## Prove guest-memory suspend / resume

Use the **`my-counter-1`** actor from the demo step above. The counter lives
in **guest RAM**. Continuing the count after suspend + resume (especially on
another worker) proves the microVM memory snapshot round-tripped.

Keep (or re-open) the proxy if it is not still running:

```bash
kubectl ate proxy actor my-counter-1 -a ate-demo-counter-microvm
```

See the Actor (note its `WORKER POD`)
```bash
kubectl ate get actor my-counter-1 -a ate-demo-counter-microvm
```

Run the `curl` a few times

```bash
curl -s -X POST http://localhost:8000/
```

Suspend the Actor. After suspending get Actor, expect `ACTOR_STATE_SUSPENDED` and `WORKER POD` `<none>`. Add `--mode=sync` to wait until the snapshot is in GCS (the default uploads it in the background)
```bash
kubectl ate suspend actor my-counter-1 -a ate-demo-counter-microvm
kubectl ate get actor my-counter-1 -a ate-demo-counter-microvm
```

Resume the Actor with live traffic

```bash
curl -s -X POST http://localhost:8000/
```

Check where the Actor ended up (see if it moved to another Worker)

```bash
kubectl ate get actor my-counter-1 -a ate-demo-counter-microvm
```

Watch **`preserved memory count`** in the curl body. If it continues from where
you left off (e.g. was `1`, becomes `2`+), microVM checkpoint/restore worked.

---

#### How the pieces connect (the overall architecture)

```text
Client (kubectl ate proxy actor, mTLS client cert on the SPIFFE allowlist)
  -> atenet-router (Envoy or agentgateway), routes on ate-target-actor
  -> ResumeActor / worker assignment
  -> mTLS to atunnel on the worker
  -> ateworker-microvm
       boots Cloud Hypervisor guest (assets from SandboxConfig / GCS)
       actor process inside guest
```

Controller behavior for `microvm` worker pools:

- Request the `ate.dev/kvm` device (atelet advertises it only where `/dev/kvm` exists)
- Tolerate `ate.dev/sandboxClass=microvm:NoSchedule`, so tainted pools can be reserved for microVM workers

Actor template rules that differ from gVisor (see `docs/reference/sandbox-classes.md`):

- `resources.limits.memoryBytes` is guest RAM and must be at least 128 MiB; VMM + virtiofsd overhead is booked against the worker on top
- `cpuMillicores` becomes whole vCPUs (rounded up, minimum 1)
- Per-container `resources.limits` are enforced (on gVisor they're accepted but ignored)
- `durableDir` volumes and rootfs uppers live on the host and are shared over virtio-fs; `VOLUMES`/`ROOTFS` snapshots are tar archives
- The class is set by the first snapshot; no cross-class restore

---

## Cleanup

```bash
# Actor first
kubectl ate delete actor my-counter-1 -a ate-demo-counter-microvm

# Demo WorkerPool, template, atespace, namespace
go run ./cmd/ate-setup delete demo counter-microvm
```

If you created the manual example above, delete it the same way: actors, then
`kubectl ate delete actor-template my-app -a demo`, then
`kubectl ate delete atespace demo`, then the WorkerPool / namespace with `kubectl delete`.

Leaving the core `ate-system` install intact is fine; microVM is additive.

To tear down the whole platform:

```bash
go run ./cmd/ate-setup delete ate-system
```

Optional, after the platform is gone: remove the staged assets from GCS. The
`microvm` `SandboxConfig` points at them, so don't do this on a live install.

```bash
gcloud storage rm -r "gs://${BUCKET_NAME}-assets/microvm-assets/" || true
```

GCP resources (cluster, buckets, IAM) are torn down from substrate-gke:
`tools/setup-gcp/teardown.sh [--all|--cluster-scoped]` or `tools/cleanup-gcp`.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Worker pods `Pending` | Does any node advertise `ate.dev/kvm` (nested virt / `/dev/kvm` on the GKE pool)? If you tainted the pool, is it the `ate.dev/sandboxClass=microvm` key? |
| WorkerPool never creates a Deployment | `kubectl get workerpool -n <ns> -o yaml`: `status.sandboxClasses[].conditions` `Resolved=False` (`SandboxConfigNotFound`, `DefaultConfigNotFound`, ...) |
| `SandboxConfig` rejected on apply | Full asset set (`cloud-hypervisor`, `virtiofsd`, `kata-kernel`, `kata-image`) for every arch of every version; a ValidatingAdmissionPolicy enforces it |
| Golden snapshot never Ready | `kubectl ate get actor-template <name> -a <atespace> -o yaml`; atelet `SandboxRuntimeSyncFailed` events on the worker pod (asset URL unreachable, sha256 mismatch); assets must live in `${BUCKET_NAME}-assets`, not the snapshot bucket |
| Resume hang / wrong count | Snapshot fidelity is `SNAPSHOT_FIDELITY_MEMORY`? Don't let one template select both gVisor and microVM pools |
| Built images wrong arch | `KO_DEFAULTPLATFORMS` vs node arch for images you build yourself |

Debugging:

```bash
kubectl -n ate-system logs daemonset/atelet --tail=100
kubectl -n ate-demo-counter-microvm get pods -o wide
kubectl events -n ate-demo-counter-microvm --for workerpool/counter-microvm
kubectl -n ate-demo-counter-microvm describe pods
```

---

## How this differs from `standalone-setup.md`

| | Standalone microVM lab | This lab (Substrate on GKE) |
|---|---|---|
| Goal | Pod-level isolation via Kata RuntimeClass | Actor sandbox class inside Substrate workers |
| API | `runtimeClassName: kata-*` on Pods | `sandboxClasses: [{name: microvm}]` on WorkerPool; template `workerSelector` picks the pool |
| Lifecycle | Normal Pod start/stop | Suspend / resume / multiplex / atenet wake |
| Toolchain | Cluster containerd + Kata install | `SandboxConfig` assets from GCS via atelet |
| Ingress | Normal Service / Gateway | `ate-target-actor` → atenet-router (mTLS) → atunnel |

Use **standalone** when you want every Kubernetes Pod in a VM. Use **this lab**
when you want Substrate actors with VM-grade isolation and the same actor
lifecycle as gVisor.

---

## References (upstream, v1.0.0 tag)

- `demos/counter/counter-microvm.yaml.tmpl` and `counter-microvm-template.yaml.tmpl`
- `demos/counter/README.md` (Running on microVM)
- `manifests/ate-install/sandboxconfig-microvm.yaml.tmpl`
- `docs/reference/api-guide.md` (SandboxConfig, MicroVM SandboxConfig)
- `docs/reference/sandbox-classes.md`
- `docs/dev/microvm-local.md` (kind / Lima)
- `cmd/ate-setup/commands.md`
- GKE provisioning: [substrate-gke](https://github.com/ai-on-gke/substrate-gke)
- GKE control-plane setup: [`../install-and-setup/setup-gke.md`](../install-and-setup/setup-gke.md)

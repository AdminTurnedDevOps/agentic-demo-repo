---
title: "Agent Substrate Demo: Install, Deploy, and Run a Stateful Actor on GKE"
date: 2026-05-30
description: >
  End-to-end walkthrough for standing up Agent Substrate on a GKE cluster,
  deploying the stateful counter demo, and driving an actor through its full
  create / resume / suspend / delete lifecycle.
tags: [agent-substrate, kubernetes, gke, gvisor, actors, workers]
author: Michael Levan
---

# Agent Substrate Demo (GKE)

This guide takes you from an existing **GKE** cluster to a running, stateful
**actor** on [Agent Substrate](https://github.com/agent-substrate/substrate).
Provisioning is done with raw `gcloud` commands (or `tools/setup-gcp` if you're
building a cluster from scratch); snapshots are stored in a GCS bucket.

> What you'll see: a counter actor that preserves its in-memory value across a
> full **suspend → snapshot → resume** cycle, even when it lands on a different
> worker pod. That is the core Substrate capability — multiplexing many idle
> actors onto a small pool of warm pods.

GKE is the supported cloud path: it's the one managed offering that can enable the
Pod Certificate beta APIs the control plane depends on. (CI itself runs on `kind`,
where the apiserver flags are set directly — not on GKE.) See
[Why GKE](#why-gke-the-pod-certificate-requirement) at the end for the details.

---

## Prerequisites

### Cluster

A **GKE Standard** cluster. **Autopilot will not work**: `atelet` runs a
`privileged` container and mounts a `hostPath` (`manifests/ate-install/atelet.yaml`),
and the worker pods it manages do the same (`internal/controllers/workerpool_controller.go`).
Autopilot rejects both. The cluster must also be able to enable the Pod Certificate
beta APIs (see [Why GKE](#why-gke-the-pod-certificate-requirement)); Step 2a does this.

### GCP requirements

- A GCP **project** with billing enabled.
- Authenticated for application-default credentials:
  `gcloud auth application-default login`.
- `setup-gcp` enables the required APIs (Service Usage, Resource Manager,
  Container, Storage, Network Connectivity) for you.

> **gVisor / `runsc`:** Substrate sandboxes actors with gVisor and checkpoints
> them with `runsc`. **No special node pool or `runtimeClassName` is required** —
> `runsc` runs nested inside the worker pod, so `setup-gcp` provisions a standard
> node pool (`substrate-node-pool`, machine type from `GVISOR_NODE_MACHINE_TYPE`).
> Checkpoint/restore currently requires a `runsc` build that supports the
> `--allow-connected-on-save` flag (works around a networking resumption bug); this
> is noted in `docs/architecture.md`. Checkpointing fails without it.

### Required tools

| Tool | Version | Notes |
|---|---|---|
| Go | ≥ 1.26.3 | Matches the repo `go.mod` toolchain. Runs `setup-gcp` and builds `kubectl-ate`. |
| `gcloud` | recent | Authenticates the cluster, registry, and IAM operations. |
| `kubectl` | Match your cluster's minor version | Substrate targets the latest stable Kubernetes release and the one prior. |
| `git` | any recent | The `hack/` scripts resolve the repo root via `git rev-parse`. |

Images are built and pushed by `ko` (invoked by `hack/install-ate.sh`) to your `KO_DOCKER_REPO`; `valkey` (state store) is deployed for you by the install script. You do not install them manually.

`ko` is a build tool for Go container images from Google. It builds an image straight from Go source without a Dockerfile and without a Docker daemon.

### Get the source

```bash
git clone https://github.com/agent-substrate/substrate.git
cd substrate
```

> **Run every command below from the root of the `substrate` repo.** The `hack/`
> scripts use `git rev-parse --show-toplevel` and the demo manifests live inside
> this repo.

---

## Step 1: Configure environment

`setup-gcp` and `hack/install-ate.sh` read configuration from an env file. Copy
the example and edit it for your project:

```bash
cp hack/ate-dev-env.sh.example .ate-dev-env.sh
```

Key values to set (see `hack/ate-dev-env.sh.example`):

| Variable | Example | Purpose |
|---|---|---|
| `PROJECT_ID` | `my-substrate-proj` | Target GCP project. |
| `PROJECT_NUMBER` | `123456789012` | Numeric project ID; the example file auto-derives it via `gcloud projects describe`. Used to build the IAM principals. |
| `GCE_REGION` | `us-central1` | Region for the **snapshot bucket**. |
| `CLUSTER_LOCATION` | `us-central1-c` | Zone (or region) your cluster lives in. **This — not `GCE_REGION` — is what `gcloud container` commands take as `--location`.** |
| `CLUSTER_NAME` | `substrate-poc` | Name of your **existing** GKE cluster. |
| `CLUSTER_VERSION` | `1.35.0-gke.2398000` | Pinned GKE version (only used when creating a cluster via `setup-gcp`). |
| `GVISOR_NODE_MACHINE_TYPE` | `c3-standard-4` | Worker node machine type. |
| `BUCKET_NAME` | `my-substrate-snapshots` | GCS bucket for snapshots. |
| `KO_DOCKER_REPO` | `gcr.io/my-substrate-proj/ate-images` | Image registry for `ko`. |

```bash
source .ate-dev-env.sh
```

---

## Step 2 — Provision GCP resources

> This guide assumes you **already have a GKE cluster** with the GCP APIs enabled
> (see Prerequisites). The commands below are the remaining `setup-gcp` steps as
> raw `gcloud` — the snapshot bucket, the IAM bindings, and making sure your
> cluster carries the Pod Certificate beta APIs + Workload Identity. The IAM and
> cluster-update steps are additive and safe to re-run; the bucket creation (2b) is
> the exception — it errors if the bucket already exists.
>
> **Building from scratch instead?** `go run ./tools/setup-gcp --all` does all six
> steps for you. Do **not** run it — or `--create-cluster` — against a cluster you
> built by hand: `tools/setup-gcp/cmd/cluster.go` will **delete and recreate** the
> cluster if its network/subnet don't match your env file.

The env file you sourced in Step 1 already exports `PROJECT_ID`, `PROJECT_NUMBER`,
`CLUSTER_NAME`, `GCE_REGION`, and `BUCKET_NAME`. Derive the two identities the
bindings reference:

```bash
export ATELET_PRINCIPAL="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${PROJECT_ID}.svc.id.goog/subject/ns/ate-system/sa/atelet"
export NODE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
```

### 2a. Ensure the cluster has the Pod Certificate beta APIs + Workload Identity

A hand-made cluster usually lacks these, and without them the control plane
(`ate-api-server`, `atenet-router`, `valkey`) can't start. Both are additive
updates (this is exactly what `cmd/cluster.go` reconciles on an existing cluster):

```bash
gcloud container clusters update "$CLUSTER_NAME" \
  --location="$CLUSTER_LOCATION" --project="$PROJECT_ID" \
  --enable-kubernetes-unstable-apis=certificates.k8s.io/v1beta1/podcertificaterequests,certificates.k8s.io/v1beta1/clustertrustbundles

gcloud container clusters update "$CLUSTER_NAME" \
  --location="$CLUSTER_LOCATION" --project="$PROJECT_ID" \
  --workload-pool="${PROJECT_ID}.svc.id.goog"
```

> Enabling beta APIs changes the control plane, but **existing nodes may need to be
> recreated** before the feature is fully usable on them. If the system pods stay
> not-ready after install, roll the node pool (e.g. `gcloud container clusters
> upgrade "$CLUSTER_NAME" --location="$CLUSTER_LOCATION" --node-pool=<pool-name>` to
> the same version) so nodes pick up the change.

> Node pools must run the **GKE Metadata Server** for the atelet Workload Identity
> binding to resolve. Pools created *after* you enable `--workload-pool` get it by
> default; update a pre-existing pool with:
> ```bash
> gcloud container node-pools update <pool-name> --cluster="$CLUSTER_NAME" \
>   --location="$CLUSTER_LOCATION" --project="$PROJECT_ID" --workload-metadata=GKE_METADATA
> ```

### 2b. Create the snapshot bucket (`--create-snapshot-bucket`)

```bash
gcloud storage buckets create "gs://${BUCKET_NAME}" \
  --project="$PROJECT_ID" --location="$GCE_REGION" --uniform-bucket-level-access
```

### 2c. Bucket-scoped IAM for atelet (`--create-iam-policy-bindings`)

```bash
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
  --member="$ATELET_PRINCIPAL" --role=roles/storage.objectAdmin
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
  --member="$ATELET_PRINCIPAL" --role=roles/storage.bucketViewer
```

### 2d. Project-level IAM (`--grant-gke-node-permissions` + `--grant-atelet-permissions`)

Node service account (image pull) and the atelet principal (snapshots + image pull):

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${NODE_SA}" --role=roles/storage.objectViewer
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${NODE_SA}" --role=roles/artifactregistry.reader

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="$ATELET_PRINCIPAL" --role=roles/storage.objectAdmin
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="$ATELET_PRINCIPAL" --role=roles/artifactregistry.reader
```

### 2e. Point `kubectl` at your cluster

```bash
gcloud container clusters get-credentials "$CLUSTER_NAME" \
  --location="$CLUSTER_LOCATION" --project="$PROJECT_ID"
kubectl get nodes
```

> **Command-accuracy note:** these `gcloud` flags were verified against Google
> Cloud SDK 484.0.0. Flags vary by version — confirm with
> `gcloud <group> <command> --help` if yours differs.

---

## Step 3 — Install the Agent Substrate system

This builds the core images (via `ko`, pushed to `KO_DOCKER_REPO`) and deploys the
control plane and node components: the CRDs, the `ate-api-server` (control plane),
the `pod-certificate-controller` (in-cluster mTLS signer that fulfills the
`PodCertificateRequest`s), `atelet` (node DaemonSet), `atenet` (DNS + Envoy router),
and `valkey` (dynamic state store).

```bash
./hack/install-ate.sh --deploy-ate-system
```

Wait for the system pods to become ready:

```bash
kubectl get pods -n ate-system --watch
```

> Run `./hack/install-ate.sh --help` to see all granular deploy/delete targets
> (e.g. `--deploy-ate-apiserver`, `--deploy-atenet`, `--delete-ate-system`).

---

## Step 4 — Deploy the counter demo

The counter demo is a small stateful Go HTTP server that increments an in-memory
counter on every request. Deploying it creates the `ate-demo-counter` namespace,
a `WorkerPool`, and an `ActorTemplate`.

```bash
./hack/install-ate.sh --deploy-demo-counter
```

Wait until the template's golden snapshot is ready:

```bash
kubectl wait --for=condition=Ready actortemplate/counter \
  -n ate-demo-counter --timeout=5m
```

What was created:

```bash
kubectl get workerpool,actortemplate -n ate-demo-counter
```

- **WorkerPool** `counter` — the pool of warm pods that actors get multiplexed onto.
- **ActorTemplate** `counter` — the immutable actor definition; Substrate builds a
  "golden snapshot" (version 0) from it so new actors hydrate instantly.

---

## Step 5 — Install the CLI

`kubectl-ate` is a `kubectl` plugin for managing actors and workers.

```bash
go install ./cmd/kubectl-ate
```

Confirm it's on your `PATH` and registered as a plugin:

```bash
kubectl ate --help
```

> If `kubectl ate` is not found, ensure your Go bin directory
> (`$(go env GOPATH)/bin`) is on your `PATH`.

---

## Step 6 — Create an actor

Create an actor instance from the counter template. The actor ID must be a valid
DNS-1123 label (lowercase alphanumeric + hyphens).

```bash
kubectl ate create actor my-counter-1 --template ate-demo-counter/counter
```

The `--template` value is `<namespace>/<name>` — here `ate-demo-counter/counter`.

The actor starts in `SUSPENDED` state — no worker pod is consumed yet:

```bash
kubectl ate get actor my-counter-1
```

---

## Step 7 — Drive traffic to the actor

Substrate routes to actors by a uniform DNS name:
`<actor-id>.actors.resources.substrate.ate.dev`. Port-forward the `atenet` router
and pass the actor's name in the `Host` header.

In one terminal, port-forward the router:

```bash
kubectl port-forward -n ate-system svc/atenet-router 8000:80
```

In a **second terminal**, send a request. The first request triggers an
on-demand **resume**: the router pauses traffic, the control plane claims a warm
worker, `atelet`/`ateom` restore the snapshot into the sandbox, then the request
is forwarded.

```bash
curl -X POST -H "Host: my-counter-1.actors.resources.substrate.ate.dev" \
  http://localhost:8000
```

Send it a few more times and watch the counter increment. Confirm the actor is
now `RUNNING` and bound to a worker IP:

```bash
kubectl ate get actor my-counter-1
kubectl ate get workers
```

---

## Step 8 — Prove state survives suspend/resume

This is the payoff. Suspend the actor — Substrate checkpoints its full memory +
disk state to the GCS snapshot bucket and reclaims the worker pod:

```bash
kubectl ate suspend actor my-counter-1
kubectl ate get actor my-counter-1   # -> SUSPENDED, no worker
```

Now hit it again. The next request resumes the actor from its snapshot —
possibly on a different worker — and the counter **continues from where it left
off** rather than resetting:

```bash
curl -X POST -H "Host: my-counter-1.actors.resources.substrate.ate.dev" \
  http://localhost:8000
```

Stream the actor's logs to watch activity across the lifecycle:

```bash
kubectl ate logs actor my-counter-1
```

---

## Step 9 — Clean up

Delete the actor (only suspended actors can be deleted):

```bash
kubectl ate suspend actor my-counter-1   # if currently running
kubectl ate delete actor my-counter-1
```

Remove the demo resources (namespace, WorkerPool, ActorTemplate):

```bash
./hack/install-ate.sh --delete-demo-counter
```

Tear down the whole Substrate system and all demos:

```bash
./hack/install-ate.sh --delete-all
```

Remove the GCP resources that Step 2 created — **without deleting your cluster**.
`./hack/teardown.sh --all` would also run `--delete-cluster` (deletes
`$CLUSTER_NAME`) and `--delete-gvisor-node-pool`; since you brought your own
cluster, use the granular flags instead:

```bash
./hack/teardown.sh \
  --revoke-gke-node-permissions \
  --delete-iam-policy-bindings \
  --delete-snapshot-bucket
```

> **Project-level atelet roles are not reversed by teardown.** The script removes
> the *bucket-scoped* atelet bindings but has no reverse for the project-level
> `objectAdmin` / `artifactregistry.reader` grants from Step 2d. Remove them by hand
> (`--condition=None` matches how they were added):
> ```bash
> gcloud projects remove-iam-policy-binding "$PROJECT_ID" \
>   --member="$ATELET_PRINCIPAL" --role=roles/storage.objectAdmin --condition=None
> gcloud projects remove-iam-policy-binding "$PROJECT_ID" \
>   --member="$ATELET_PRINCIPAL" --role=roles/artifactregistry.reader --condition=None
> ```

---

## What just happened (mapping to the architecture)

| Step | Substrate mechanism |
|---|---|
| Create actor | Record written to the **valkey** state store as `SUSPENDED`, referencing the `counter` `ActorTemplate` (new actors hydrate from its golden snapshot). No pod consumed. |
| First request | `atenet` (Envoy + ext_proc) reads the actor ID from the `Host` header, queries the control plane, and triggers `ResumeActor`. |
| Resume | Control plane claims a warm worker from the `WorkerPool`; `atelet` + `ateom` restore the snapshot into the gVisor sandbox; status → `RUNNING`. |
| Suspend | `ateom` checkpoints memory + disk via `runsc`; `atelet` streams the snapshot to the GCS bucket; the worker is wiped and returned to the pool; status → `SUSPENDED`. |
| Resume again | The actor rehydrates from its **last** snapshot, so in-memory state (the counter) persists across the cycle. |

Config resources (`WorkerPool`, `ActorTemplate`) live in the Kubernetes API as
CRDs; high-churn instance state (`Actor`, `Worker`) lives in valkey — keeping the
Kubernetes control plane out of the request hot path.

---

## Why GKE (the Pod Certificate requirement)

Substrate's `cmd/podcertcontroller` issues per-pod mTLS **Pod Certificates** for
the core system components. **Three** pods mount a `podCertificate` projected
volume: `ate-api-server`, `atenet-router`, and `valkey`. (The
`pod-certificate-controller` is the *signer*; it bootstraps from plain `secret`
CA-pool volumes, not `podCertificate` — see
`manifests/ate-install/pod-certificate-controller.yaml`.)

A `podCertificate` projected volume requires the apiserver to serve
`certificates.k8s.io/v1beta1` plus the `PodCertificateRequest`,
`ClusterTrustBundle`, and `ClusterTrustBundleProjection` feature gates — **off by
default** as of Kubernetes 1.36. The volume must mount for the pod to run, so
without these the control plane, router, and state store never start.

GKE exposes a supported knob for exactly these beta APIs (`EnableK8SBetaApis`, set
by `tools/setup-gcp/cmd/cluster.go`). Managed AKS exposes no supported way to turn
these gates on — the standing request ([Azure/AKS#1887](https://github.com/Azure/AKS/issues/1887))
was closed without one — so the system pods can't mount their certificates there.
To run Substrate on Azure you'd need a cluster where you control the apiserver
flags (Cluster API / kubeadm / k3s), not stock managed AKS.

> Pod Certificates secure Substrate's **own infrastructure**. Actor identity is a
> separate mechanism: the `SessionIdentity` gRPC service (`MintJWT` / `MintCert`),
> backed by session-id JWT/CA pool secrets. Actor/worker/ateom pods do **not**
> mount `podCertificate` volumes.

---

## Troubleshooting

- **`kubectl ate` not found** — add `$(go env GOPATH)/bin` to your `PATH` and
  re-run `go install ./cmd/kubectl-ate`.
- **System pods stuck not-ready** — check `kubectl get pods -n ate-system` and
  `kubectl describe` / `kubectl logs` the pending pod. If `ate-api-server`,
  `atenet-router`, or `valkey` are stuck mounting a volume, confirm the cluster
  was created with `EnableK8SBetaApis` (see [Why GKE](#why-gke-the-pod-certificate-requirement)).
- **Image pull errors** — confirm the node service account has
  `roles/artifactregistry.reader` (granted by `--grant-gke-node-permissions`) and
  that `KO_DOCKER_REPO` matches where `ko` pushed the images.
- **Snapshot read/write errors** — confirm the `atelet` workload-identity binding
  (`--create-iam-policy-bindings`) and that `BUCKET_NAME` exists.
- **Checkpoint/restore fails** — your `runsc` likely lacks
  `--allow-connected-on-save`; this requirement is documented in
  `docs/architecture.md`.
- **Reset dynamic state** — `kubectl ate admin debug-flush-redis` clears the
  valkey store (destructive; dev only).

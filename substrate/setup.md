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
Provisioning is done with raw `gcloud` commands; snapshots are stored in a GCS
bucket.

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

- A GCP **project** with billing enabled. The commands in this section use
  `$PROJECT_ID`; Step 1 persists it in the env file, but set it now so the commands
  below work top-to-bottom:

  ```bash
  export PROJECT_ID=<your-project-id>
  ```
- Authenticated three ways — CLI login (for the `gcloud` commands), application
  default credentials (for client libraries), and a Docker credential helper (so
  `ko` can push to `gcr.io`):

  ```bash
  gcloud auth login
  gcloud auth application-default login --project="$PROJECT_ID"
  gcloud auth configure-docker gcr.io
  ```

  > If your `KO_DOCKER_REPO` is in **Artifact Registry** instead of `gcr.io`, point
  > the helper at that host, e.g. `gcloud auth configure-docker us-docker.pkg.dev`.
- The required APIs enabled on the project:

  ```bash
  gcloud services enable \
    cloudresourcemanager.googleapis.com \
    container.googleapis.com \
    networkconnectivity.googleapis.com \
    serviceusage.googleapis.com \
    storage.googleapis.com \
    --project="$PROJECT_ID"
  ```

> **gVisor / `runsc`:** Substrate sandboxes actors with gVisor and checkpoints
> them with `runsc`. **No special node pool or `runtimeClassName` is required** —
> `runsc` runs nested inside the worker pod, so a standard node pool is enough.
> Use a machine type with room for the worker pods (e.g. `c3-standard-4`).
> Checkpoint/restore currently requires a `runsc` build that supports the
> `--allow-connected-on-save` flag (works around a networking resumption bug); this
> is noted in `docs/architecture.md`. Checkpointing fails without it.

### Required tools

| Tool | Version | Notes |
|---|---|---|
| Go | ≥ 1.26.3 | Matches the repo `go.mod` toolchain. Builds `kubectl-ate`. |
| `gcloud` | recent | Authenticates the cluster, registry, and IAM operations. |
| `kubectl` | Match your cluster's minor version | Substrate targets the latest stable Kubernetes release and the one prior. |
| `git` | any recent | The `hack/` scripts resolve the repo root via `git rev-parse`. |
| `openssl` | any recent | `hack/install-ate.sh` uses it to convert the valkey CA cert (DER → PEM). |
| `curl` | any recent | Drives traffic to the actor in Steps 7–8. |

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

`hack/install-ate.sh` reads configuration from an env file, and the `gcloud`
commands below reference the same variables. Copy the example and edit it for your
project:

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
| `CLUSTER_VERSION` | `1.35.0-gke.2398000` | Present in the example file; **not used by this guide** since your cluster already exists. |
| `GVISOR_NODE_MACHINE_TYPE` | `c3-standard-4` | Worker node machine type. |
| `BUCKET_NAME` | `my-substrate-snapshots` | GCS bucket for snapshots. |
| `KO_DOCKER_REPO` | `gcr.io/my-substrate-proj/ate-images` | Image registry for `ko`. |

```bash
source .ate-dev-env.sh
```

---

## Step 2 — Provision GCP resources

> This guide assumes you **already have a GKE Standard cluster** with the GCP APIs
> enabled (see Prerequisites). The `gcloud` commands below configure the snapshot
> bucket, the IAM bindings, and make sure your cluster carries the Pod Certificate
> beta APIs + Workload Identity. The IAM and cluster-update steps are additive and
> safe to re-run; the bucket creation (2b) is the exception — it errors if the
> bucket already exists.
>
> **Multi-pool clusters:** `atelet` runs as a **DaemonSet** (every node) and the
> worker pods it manages have **no node selector**, so Substrate workloads can land
> on *any* node pool. Repeat the per-pool steps below — node-SA discovery + IAM
> grants (2d), GKE Metadata Server (2a), and the beta-API node rollout (2a) — for
> **every** pool where workloads may schedule, not just one.

The env file you sourced in Step 1 already exports `PROJECT_ID`, `PROJECT_NUMBER`,
`CLUSTER_NAME`, `GCE_REGION`, and `BUCKET_NAME`. Derive the two identities the
bindings reference:

```bash
export ATELET_PRINCIPAL="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${PROJECT_ID}.svc.id.goog/subject/ns/ate-system/sa/atelet"
export NODE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
```

> `NODE_SA` above is the **default** Compute Engine service account. GKE recommends
> (and your existing pools may already use) a **custom** node service account — in
> which case the image-pull bindings in Step 2d must go to *that* SA, not the
> default. Discover the SA each relevant pool actually runs as:
> ```bash
> gcloud container node-pools describe <pool-name> \
>   --cluster="$CLUSTER_NAME" --location="$CLUSTER_LOCATION" \
>   --project="$PROJECT_ID" --format='value(config.serviceAccount)'
> ```
> If it returns anything other than `default`, set `NODE_SA` to that address. See
> the [GKE node service-account docs](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/service-accounts).

### 2a. Ensure the cluster has the Pod Certificate beta APIs + Workload Identity

A hand-made cluster usually lacks these, and without them the control plane
(`ate-api-server`, `atenet-router`, `valkey`) can't start. Both are additive
updates to an existing cluster:

```bash
gcloud container clusters update "$CLUSTER_NAME" \
  --location="$CLUSTER_LOCATION" --project="$PROJECT_ID" \
  --enable-kubernetes-unstable-apis=certificates.k8s.io/v1beta1/podcertificaterequests,certificates.k8s.io/v1beta1/clustertrustbundles

gcloud container clusters update "$CLUSTER_NAME" \
  --location="$CLUSTER_LOCATION" --project="$PROJECT_ID" \
  --workload-pool="${PROJECT_ID}.svc.id.goog"
```

> Enabling beta APIs changes the control plane, but **existing nodes only pick up
> the newly-enabled beta APIs once they are recreated** — a same-version, in-place
> operation does *not* apply them. Either upgrade the pool to a **later** GKE
> version, or create a fresh node pool. To upgrade:
> ```bash
> gcloud container clusters upgrade "$CLUSTER_NAME" \
>   --location="$CLUSTER_LOCATION" --project="$PROJECT_ID" \
>   --node-pool=<pool-name> --cluster-version=<later-version>
> ```
> See the [GKE beta API docs](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/use-beta-apis#ensure_that_nodes_use_the_newly-enabled_beta_apis).

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

> **Run cleanup only in a dedicated demo project, or for resources you know were
> added solely for this guide.** The teardown flags and the manual commands below
> remove *whole* IAM bindings and **delete the bucket**. In a shared project, those
> roles or that bucket may predate this demo or be used by unrelated workloads —
> removing them can break those workloads. If in doubt, remove the specific
> member/role pairs by hand instead of running `--delete-iam-policy-bindings`.

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
> (the Step 2d `add` commands create *unconditioned* bindings, so `--condition=None`
> is what targets them on removal):
> ```bash
> gcloud projects remove-iam-policy-binding "$PROJECT_ID" \
>   --member="$ATELET_PRINCIPAL" --role=roles/storage.objectAdmin --condition=None
> gcloud projects remove-iam-policy-binding "$PROJECT_ID" \
>   --member="$ATELET_PRINCIPAL" --role=roles/artifactregistry.reader --condition=None
> ```

> **Custom node SAs are not reversed either.** `--revoke-gke-node-permissions` only
> revokes from the **default** Compute Engine SA (`hack/teardown.sh` hardcodes it).
> If you granted the Step 2d node-SA roles to a **custom** `$NODE_SA`, remove those
> by hand too:
> ```bash
> gcloud projects remove-iam-policy-binding "$PROJECT_ID" \
>   --member="serviceAccount:${NODE_SA}" --role=roles/storage.objectViewer --condition=None
> gcloud projects remove-iam-policy-binding "$PROJECT_ID" \
>   --member="serviceAccount:${NODE_SA}" --role=roles/artifactregistry.reader --condition=None
> ```

> **The Step 2a cluster changes are not rolled back.** This cleanup removes the
> bucket and IAM only. It does **not** undo the cluster mutations from Step 2a —
> Workload Identity, the GKE Metadata Server on your pools, the node rollout, and
> the enabled beta APIs all remain. Per the
> [GKE beta API docs](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/use-beta-apis),
> **enabled beta APIs cannot be disabled** on a cluster (`gcloud` offers no
> `--disable-kubernetes-unstable-apis`); Workload Identity can be turned off with
> `--disable-workload-identity` if you need to. If you want a pristine cluster,
> delete and recreate it.

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
the core system workloads. Three components mount a `podCertificate` projected
volume: `ate-api-server`, `atenet-router`, and `valkey` — and valkey is a
6-replica `StatefulSet` plus a `valkey-cluster-init` `Job`, so that's several pods,
not one. (The `pod-certificate-controller` is the *signer*; it bootstraps from
plain `secret` CA-pool volumes, not `podCertificate` — see
`manifests/ate-install/pod-certificate-controller.yaml`.)

A `podCertificate` projected volume requires the apiserver to serve
`certificates.k8s.io/v1beta1` plus the `PodCertificateRequest`,
`ClusterTrustBundle`, and `ClusterTrustBundleProjection` feature gates — **off by
default** as of Kubernetes 1.36. The volume must mount for the pod to run, so
without these the control plane, router, and state store never start.

GKE exposes a supported knob for exactly these beta APIs — the
`--enable-kubernetes-unstable-apis` flag you ran in Step 2a. **GKE is the managed
path this guide verifies.** A managed-AKS path is *not* documented or verified here;
turning these gates on requires control over apiserver flags, which managed offerings
typically don't expose (the standing AKS request is
[Azure/AKS#1887](https://github.com/Azure/AKS/issues/1887)). On Azure you'd most
likely need a cluster where you control those flags (Cluster API / kubeadm / k3s)
rather than stock managed AKS — confirm against current provider docs before relying
on it.

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
  `atenet-router`, or `valkey` are stuck mounting a volume, confirm the Pod
  Certificate beta APIs were enabled in Step 2a **and** the nodes the pods landed on
  were rolled out so they actually serve those APIs (see [Why GKE](#why-gke-the-pod-certificate-requirement)).
- **Image pull errors** — confirm the node service account (the one each pool
  actually runs as — see Step 2d) has `roles/artifactregistry.reader` and that
  `KO_DOCKER_REPO` matches where `ko` pushed the images.
- **Snapshot read/write errors** — work through each layer the snapshot path
  depends on:
  - the **bucket-scoped** atelet bindings exist (Step 2c: `objectAdmin` +
    `bucketViewer`) and `BUCKET_NAME` exists;
  - the **project-level** atelet bindings exist (Step 2d: `objectAdmin` +
    `artifactregistry.reader`);
  - the atelet Workload Identity resolves — i.e. the **GKE Metadata Server is
    enabled on the pool the atelet pod landed on** (Step 2a). On a multi-pool
    cluster it's easy to miss a pool.
- **Checkpoint/restore fails** — your `runsc` likely lacks
  `--allow-connected-on-save`; this requirement is documented in
  `docs/architecture.md`.
- **Reset dynamic state** — `kubectl ate admin debug-flush-redis` clears the
  valkey store (destructive; dev only).

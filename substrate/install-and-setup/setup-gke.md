---
title: "Agent Substrate Demo: Install, Deploy, and Run a Stateful Actor on GKE"
date: 2026-05-30
description: >
  End-to-end walkthrough for standing up Agent Substrate v1.0.0 on a GKE cluster,
  deploying the stateful counter demo, and driving an actor through its full
  create / resume / suspend / delete lifecycle.
tags: [agent-substrate, kubernetes, gke, gvisor, actors, workers]
author: Michael Levan
---

# Agent Substrate Demo (GKE)

This guide takes you from a GKE cluster to a running, stateful **actor** on
[Agent Substrate](https://github.com/agent-substrate/substrate) v1.0.0.
GCP provisioning is done with `setup-gcp` from
[ai-on-gke/substrate-gke](https://github.com/ai-on-gke/substrate-gke).
Substrate itself is installed with `ate-setup` from the Substrate repo.
Snapshots are stored in a GCS bucket.

> What you'll see: a counter actor that preserves its in-memory value across a
> full **suspend → snapshot → resume** cycle, even when it lands on a different
> worker pod. That is the core Substrate capability: multiplexing many idle
> actors onto a small pool of warm pods.

> **Want the easy path?** substrate-gke ships an interactive installer that runs
> every step below for you:
> `curl -sSL https://raw.githubusercontent.com/ai-on-gke/substrate-gke/main/install.sh | bash -s -- --demo`.
> This guide runs the same steps by hand, so you can see each one. It follows
> substrate-gke's [Setting up GKE by hand](https://github.com/ai-on-gke/substrate-gke/blob/main/docs/manual-gke-setup.md).

---

## What changed from the pre-1.0 install

| Before (May 2026) | v1.0.0 |
|---|---|
| `./hack/install-ate.sh --deploy-ate-system` | `go run ./cmd/ate-setup deploy ate-system ...` |
| `go run ./tools/setup-gcp` and `hack/teardown.sh` in the Substrate repo | `go -C tools/setup-gcp run . ...` and `tools/setup-gcp/teardown.sh` in **substrate-gke** |
| Every image built with `ko` and pushed to your registry | Prebuilt images: `--image-repo ghcr.io/agent-substrate/substrate --image-tag v1.0.0` |
| valkey state store | PostgreSQL, either bundled or external/Cloud SQL |
| atelet held the snapshot-bucket roles | ate-api-server's credential exchange issues per-actor tokens through a **snapshot transfer service account**. atelet only reads the asset bucket |
| Enabled the Pod Certificate **beta** APIs with `--enable-kubernetes-unstable-apis` | GKE **1.37+** serves them as `v1` by default. 1.37 is the minimum |
| `ActorTemplate` was a CRD (`kubectl get actortemplate`) | `ActorTemplate` is an API record (`kubectl ate get actor-templates`) |
| `ate.dev/v1alpha1` | `ate.dev/v1` |
| `ateom` in the worker pod | `ateworker-gvisor` / `ateworker-microvm` |
| `Host: <actor>.actors.resources.substrate.ate.dev` through a port-forward | `kubectl ate proxy actor`, or the `ate-target-actor: <atespace>/<actor>` header over mTLS |
| Router reachable by anyone | Only clients whose SPIFFE IDs are on `--ingress-allowed-spiffe-ids`. **If the list is empty, nothing gets in** |
| No credential provider choice | `--credential-provider` is **required** |

---

## Prerequisites

### Cluster

A **GKE Standard** cluster running **GKE 1.37 or later** on the control plane
**and every node pool**. 1.37 serves the PodCertificateRequest and
ClusterTrustBundle APIs as `v1` by default, and Substrate needs both. At the time
of writing, 1.37 is only on the **Rapid** channel. `setup-gcp` stops before
changing anything if the control plane or any pool is older, and prints the
upgrade command for each.

**Autopilot will not work.** `atelet` runs a `privileged` container that mounts a
`hostPath`, and so do the worker pods it manages. Autopilot rejects both.

The cluster also needs **Workload Identity**, with the **GKE Metadata Server** on
every pool where Substrate pods can land. Both atelet and ate-api-server reach
GCS through Workload Identity.

> **Turn off node auto-upgrade on pools that run workers, and don't use spot or
> preemptible nodes for them.** When a worker pod is deleted, its actors get 30
> minutes to suspend. An actor that's still awake when that window closes goes
> to `CRASHED`. A crashed actor can't be resumed, and its state is lost unless
> you revert it. GKE auto-upgrade drains nodes on Google's schedule, not yours:
> ```bash
> gcloud container node-pools update <pool-name> \
>   --cluster "$CLUSTER_NAME" --location "$CLUSTER_LOCATION" \
>   --no-enable-autoupgrade
> ```
> Change versions with the
> [rolling upgrade runbook](https://github.com/agent-substrate/substrate/blob/v1.0.0/docs/guides/upgrade.md)
> instead.

### GCP

- A GCP **project** with billing enabled, and an account that has Owner or
  Editor on it. `setup-gcp` creates buckets, service accounts, and IAM bindings.
- Authenticated. You need the CLI login, application default credentials, and a
  Docker credential helper. The helper is only for the counter demo, whose image
  `ko` builds and pushes:

  ```bash
  export PROJECT_ID=<your-project-id>
  gcloud auth login
  gcloud auth application-default login --project="$PROJECT_ID"
  gcloud auth configure-docker us-west1-docker.pkg.dev   # the host of your KO_DOCKER_REPO
  ```

### Required tools

| Tool | Version | Notes |
|---|---|---|
| Go | ≥ 1.27.3 | The v1.0.0 `go.mod` toolchain. `ate-setup` and `setup-gcp` both run with `go run`. If your Go is older, `GOTOOLCHAIN=auto` can download the right one |
| `gcloud` | recent | Also install `gke-gcloud-auth-plugin` (`gcloud components install gke-gcloud-auth-plugin`) |
| `kubectl` | Match your cluster's minor version | Substrate supports the latest stable Kubernetes release and the one before it |
| `git` | any recent | |
| Docker with `buildx` | recent | Only to build images from source. The counter demo image always needs a build |
| `curl` | any recent | Sends traffic to the actor in Steps 7–8 |

You don't install PostgreSQL, Envoy, or the worker images yourself.
`ate-setup` deploys them.

### Get the source

You need **two checkouts**:

```bash
mkdir -p ~/gitrepos && cd ~/gitrepos

# GKE provisioning: setup-gcp, teardown.sh, cleanup-gcp
git clone https://github.com/ai-on-gke/substrate-gke.git

# Substrate itself, pinned to the release: ate-setup, manifests, demos, kubectl-ate
git clone --branch v1.0.0 https://github.com/agent-substrate/substrate.git substrate-v1.0.0
```

> **Use a clean clone of the tag.** The manifests come from the checkout, even
> when you install prebuilt images, so the checkout has to match the image tag.
> `ate-setup` also sources `.ate-dev-env.sh` from the checkout root if one
> exists. A leftover dev env file in an older clone will silently change your
> install.

---

## Step 1: Configure environment

`setup-gcp`, `teardown.sh`, and `ate-setup` all read the same variables. Start
from substrate-gke's example:

```bash
cd ~/gitrepos/substrate-gke
cp tools/setup-gcp/ate-dev-env.sh.example .ate-dev-env.sh
```

Edit it for your project:

| Variable | Example | Purpose |
|---|---|---|
| `PROJECT_ID` | `my-substrate-proj` | Target GCP project |
| `PROJECT_NUMBER` | derived | The example derives it with `gcloud projects describe`. Workload Identity principals use the **number** |
| `GCE_REGION` | `us-west1` | Region for the buckets and the Artifact Registry repo |
| `CLUSTER_LOCATION` | `us-west1-c` | Zone or region of the cluster. `gcloud container` takes **this** as `--location` |
| `CLUSTER_NAME` | `substrate-poc` | Your existing cluster, or the one `setup-gcp` should create |
| `CLUSTER_VERSION` / `RELEASE_CHANNEL` | `1.37` / `rapid` | Only used when `setup-gcp` creates the cluster |
| `BUCKET_NAME` | `my-substrate-snapshots` | Snapshot bucket, **56 characters or fewer**. `setup-gcp` also creates `${BUCKET_NAME}-assets` for microVM assets |
| `SNAPSHOT_LOCATION` | `gs://${BUCKET_NAME}/` | Where ate-api-server stores snapshots. **Required on GKE** |
| `SNAPSHOT_TRANSFER_GSA_NAME` | `ate-snapshot-transfer` | The service account snapshot transfers run as. **Required on GKE** |
| `NODE_GSA_NAME` | `ate-gke-node` | Node service account for a cluster `setup-gcp` creates |
| `KO_DOCKER_REPO` | `us-west1-docker.pkg.dev/my-substrate-proj/ate-images` | Where `ko` pushes the counter demo image |
| `KUBECTL_CONTEXT` | `gke_my-proj_us-west1-c_substrate-poc` | Optional. Pins `ate-setup` to this context |

Then add the Substrate install settings. The env file sets the GKE settings,
and the rest come from upstream's `hack/ate-dev-env.sh.example`:

```bash
cat >> .ate-dev-env.sh <<'EOF'

# Substrate install settings (agent-substrate/substrate v1.0.0)
# Egress credential provider. {"name":"k8s.io"} is the bundled Kubernetes
# Secrets provider; {"enabled":false} turns credential injection off.
export ATE_CREDENTIAL_PROVIDER='{"name":"k8s.io"}'
# Clients the ingress router lets reach actors. atenet-client is the identity
# `kubectl ate proxy actor` presents. Add your own frontends later; each deploy
# replaces this list.
export ATE_INGRESS_ALLOWED_SPIFFE_IDS=spiffe://cluster.local/ns/ate-system/sa/atenet-client
# gVisor only. Drop this (default gvisor,microvm) to also stage microVM assets.
export ATE_INSTALL_SANDBOX_CLASSES=gvisor
EOF

source .ate-dev-env.sh
```

> Source this file in **every shell** you use for the rest of the guide.

---

## Step 2: Provision GCP resources

`setup-gcp bootstrap` covers the whole GCP side in one idempotent run:

- the APIs;
- the node service account;
- the cluster, if it doesn't exist yet;
- the snapshot and asset buckets;
- the snapshot transfer service account;
- the IAM grants;
- the monitoring dashboards;
- optionally, an Artifact Registry repository.

On an **existing** cluster, it updates the settings that can change in place:
Workload Identity, the PodCertificate APIs, and Managed OpenTelemetry. It
**never** deletes or recreates the cluster.

```bash
cd ~/gitrepos/substrate-gke
go -C tools/setup-gcp run . bootstrap \
  --create-repository \
  --atelet-snapshot-access=false
```

- **`--create-repository`** creates the Artifact Registry repo that
  `KO_DOCKER_REPO` names, and lets the nodes pull from it. The counter demo image
  is pushed there in Step 4.
- **`--atelet-snapshot-access=false`** stops atelet from getting the snapshot
  bucket roles. Only Substrate ≤ v0.5.0 needed them. In v1.0.0, every snapshot
  transfer runs on a token scoped to one actor.

### What it grants

All of these are **resource-scoped**. Nothing is granted on the project except
the node service account's role.

| Member | Role | On |
|---|---|---|
| `ate-system/ate-api-server` (WI principal) | `storage.objectAdmin`, `storage.bucketViewer` | snapshot bucket |
| `ate-system/ate-api-server` (WI principal) | `iam.serviceAccountTokenCreator` | the snapshot transfer SA |
| `${SNAPSHOT_TRANSFER_GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com` | `storage.objectAdmin`, `storage.bucketViewer` | snapshot bucket |
| `ate-system/atelet` (WI principal) | `storage.objectViewer` | `${BUCKET_NAME}-assets` |
| `ate-system/atelet` (WI principal) | `artifactregistry.reader` | the image repository. For your **actor image** repos, `setup-gcp` only prints the command |
| node SA | `container.defaultNodeServiceAccount` | project |
| each node pool's SA | `artifactregistry.reader` | the image repository |

WI principals have the form
`principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${PROJECT_ID}.svc.id.goog/subject/ns/ate-system/sa/<sa>`.
The [setup-gcp README](https://github.com/ai-on-gke/substrate-gke/blob/main/tools/setup-gcp/README.md#what-create-iam-actually-grants)
has the manual `gcloud` equivalent, for projects where you can't run the tool
with project-level IAM permissions.

> **Bringing your own cluster:** `bootstrap` doesn't add Substrate's optional
> `ate-system-infra` / `ate-postgres` node pools to an existing cluster. It
> prints the `gcloud container node-pools create` commands instead. Without
> those pools, the system components share the worker nodes, which is fine for a
> demo. Also check that every pool runs the GKE Metadata Server:
> ```bash
> gcloud container node-pools describe <pool-name> --cluster="$CLUSTER_NAME" \
>   --location="$CLUSTER_LOCATION" --project="$PROJECT_ID" \
>   --format='value(config.workloadMetadataConfig.mode)'   # want GKE_METADATA
> ```

Point `kubectl` at the cluster:

```bash
gcloud container clusters get-credentials "$CLUSTER_NAME" \
  --location="$CLUSTER_LOCATION" --project="$PROJECT_ID"
kubectl get nodes
```

> A cluster `setup-gcp` creates has **only a DNS-based control plane endpoint**.
> IAM authorizes each request (`container.clusters.connect`) before it reaches
> the API server. `get-credentials` handles this for you.

---

## Step 3: Install the Agent Substrate system

From the **Substrate** checkout, deploy the control plane from the published
v1.0.0 images. `ko` doesn't run, and you need no write access to a registry:

```bash
cd ~/gitrepos/substrate-v1.0.0
source ~/gitrepos/substrate-gke/.ate-dev-env.sh

go run ./cmd/ate-setup deploy ate-system \
  --image-repo ghcr.io/agent-substrate/substrate \
  --image-tag v1.0.0 \
  --storage-bucket-name="$BUCKET_NAME" \
  --credential-provider="$ATE_CREDENTIAL_PROVIDER" \
  --ingress-allowed-spiffe-ids="$ATE_INGRESS_ALLOWED_SPIFFE_IDS" \
  --sandbox-classes=gvisor
```

The env file already supplies the last four flags. They're spelled out here so
you can see what the install depends on.

This deploys:

| Component | What it is |
|---|---|
| CRDs (`ate.dev/v1`) | `WorkerPool`, `SandboxConfig`, `CSIDriverConfig` |
| `postgres` | Bundled PostgreSQL, the state store for actors, templates, workers, tags, and policies. It authenticates with pod certificates, not passwords |
| `ate-api-server` | gRPC control plane: actor lifecycle, scheduling, authz, and the snapshot credential exchange |
| `ate-idp-server` | Issues and publishes the keys for actor JWTs (OIDC discovery) |
| `ate-controller` | Reconciles WorkerPools into worker Deployments |
| `pod-certificate-controller` | Signs the pod certificates for mTLS between components |
| `atelet` | Node DaemonSet for images, sandbox assets, and snapshot streaming |
| `atenet-router` | Ingress to actors (Envoy). TLS only, admits allowlisted SPIFFE IDs, and routes on `ate-target-actor` |
| `atenet-egress` | Default-deny egress gateway, with credential injection |
| `k8s-credential-provider` | Serves `ate-secret://k8s.io/...` credentials to the egress gateway |
| `SandboxConfig/gvisor-default` | The gVisor runtime assets |

Wait for the system pods:

```bash
kubectl get pods -n ate-system --watch
```

Each run prints every setting it resolved and where the setting came from: a
flag, the env, a config file, or a default. The run also writes a record of the
install:

```
recorded this configuration in ~/Library/Caches/ate-setup/installs/<context>.yaml
```

**Keep that file.** Later `deploy` runs and upgrades take it with `--config`, so
a partial redeploy (`deploy atenet`, `deploy sandboxconfig`) doesn't drop
settings:

```bash
go run ./cmd/ate-setup deploy atenet \
  --config ~/Library/Caches/ate-setup/installs/<context>.yaml \
  --ingress-allowed-spiffe-ids="$ATE_INGRESS_ALLOWED_SPIFFE_IDS,spiffe://cluster.local/ns/shop/sa/frontend"
```

> **Other install options**
> - **microVM:** leave off `--sandbox-classes=gvisor`. The default,
>   `gvisor,microvm`, uploads the Kata and Cloud Hypervisor guest assets to
>   `gs://${BUCKET_NAME}-assets` and applies a `microvm` SandboxConfig. microVM
>   workers need a node pool with nested virtualization (`/dev/kvm`). `e2`
>   machine types can't do it. If an upload fails with `[SSL] PEM lib`, set
>   `CLOUDSDK_STORAGE_PARALLEL_COMPOSITE_UPLOAD_ENABLED=False`.
> - **agentgateway dataplane:** `--atenet-dataplane agentgateway`. It works with
>   the same `--credential-provider` values as Envoy.
> - **Dedicated system pools:** if the cluster has nodes labeled and tainted
>   `ate.dev/workloadType=ate-system-infra` and `ate-postgres`, add
>   `--cordon-system-infra-components`. Before v1.0.0, this flag was
>   `--cordon-control-plane`.
> - **Postgres on C4/N4 nodes:** add `--ateapi-postgres-storage-class dynamic-rwo`.
> - **External Postgres / Cloud SQL:** set
>   `ATE_API_POSTGRES_READ_WRITE_CONNECTION_STRING` (env only), or
>   `--ateapi-postgres-cloudsql-instance`. See `docs/guides/postgres.md` and
>   substrate-gke's `tools/setup-gcp/cloud-sql.md`.
> - **Settings as a file:** `--config substrate-install.yaml`, with
>   `kind: SubstrateInstall`. See `docs/guides/operator-install.md`.

---

## Step 4: Deploy the counter demo

The counter demo is a small stateful Go HTTP server that increments an in-memory
counter on every request. Deploying it creates:

- the `ate-demo-counter` namespace;
- a `WorkerPool` CRD;
- an **atespace** called `ate-demo-counter`;
- an **ActorTemplate** API record, `counter`, in that atespace.

**Releases don't publish demo images.** Run this **without** `--image-repo`, so
`ko` builds the demo image (and its worker image) and pushes them to
`KO_DOCKER_REPO`:

```bash
go run ./cmd/ate-setup deploy demo counter
```

Check the pool, and wait for the template's golden snapshot. The `GOLDEN TAG`
column fills in once it's ready, and `ERROR` shows if the build failed:

```bash
kubectl get workerpool -n ate-demo-counter
go run ./cmd/kubectl-ate get actor-templates -a ate-demo-counter   # or `kubectl ate` after Step 5
```

- **WorkerPool** `counter` is the pool of warm worker pods that actors are
  multiplexed onto. It runs 3 replicas of `ateworker-gvisor`. Each worker hosts
  many actors, each in its own sandbox, up to the pool's
  `template.resources.limits`.
- **ActorTemplate** `counter` is the immutable actor definition. Substrate boots
  it once and saves a **golden snapshot**, so new actors start from that.

> `kubectl get actortemplate` returns nothing in v1.0.0. Templates, actors,
> workers, and tags live in PostgreSQL behind the ate API, not in etcd. Only
> `WorkerPool`, `SandboxConfig`, and `CSIDriverConfig` are Kubernetes objects.

---

## Step 5: Install the CLI

`kubectl-ate` is a `kubectl` plugin for managing atespaces, templates, actors,
and workers. Use the v1.0.0 build. Either take the release binary:

```bash
curl -fsSLO https://github.com/agent-substrate/substrate/releases/download/v1.0.0/kubectl-ate-darwin-arm64
curl -fsSLO https://github.com/agent-substrate/substrate/releases/download/v1.0.0/kubectl-ate-darwin-arm64.sha256
shasum -a 256 -c kubectl-ate-darwin-arm64.sha256
install -m 0755 kubectl-ate-darwin-arm64 "$(go env GOPATH)/bin/kubectl-ate"   # must be on PATH, see below
```

or build it from the tag checkout:

```bash
go install ./cmd/kubectl-ate
```

`go install` drops the binary in `$(go env GOPATH)/bin`, usually `~/go/bin`.
`kubectl` finds plugins by scanning `PATH`, so that directory must be on it:

```bash
echo 'export PATH="$PATH:$(go env GOPATH)/bin"' >> ~/.zshrc
source ~/.zshrc
which kubectl-ate && kubectl ate --help
```

`kubectl ate` port-forwards to `svc/api` in `ate-system` on its own, and checks
the API server's certificate against the cluster's ClusterTrustBundles.
Without `--token-file`, it acts as the shared `ate-client` ServiceAccount. Fine
for a demo, but for real users, give each person their own identity. See
`docs/guides/authentication.md` and `docs/guides/authorization.md`.

---

## Step 6: Create an actor

Create an actor from the counter template. Actors live in an **atespace**,
Substrate's own namespace (not a Kubernetes namespace), and `--template` names a
template **in that atespace**. The name must be a DNS-1123 label.

```bash
kubectl ate create actor my-counter-1 -a ate-demo-counter --template counter
```

> `--template` takes `<template-name>`, resolved in the actor's atespace, or
> `<atespace>/<template-name>` for a template in another atespace. Before v1.0.0
> the prefix was a Kubernetes namespace; it is now an atespace.

The actor is created without taking a worker. Its first request resumes it:

```bash
kubectl ate get actor my-counter-1 -a ate-demo-counter
```

---

## Step 7: Drive traffic to the actor

The router no longer routes on DNS names or `Host` headers. It accepts mTLS
connections only from allowlisted SPIFFE IDs, and picks the actor from the
`ate-target-actor: <atespace>/<actor>` header. From your workstation,
`kubectl ate proxy actor` handles both. It presents the `atenet-client` identity
you allowlisted in Step 3.

In one terminal:

```bash
kubectl ate proxy actor my-counter-1 -a ate-demo-counter   # 127.0.0.1:8000 -> actor port 80
```

In a **second terminal**, send a request:

```bash
curl -X POST -i http://localhost:8000/
```

The first request triggers an on-demand **resume**:

1. The router parks the request.
2. ate-api-server places the actor on a warm worker with room.
3. atelet and `ateworker-gvisor` restore the golden snapshot into a new gVisor
   sandbox.
4. The router forwards the request.

Send it a few more times and watch the counter increment. Then look at the actor
and the workers:

```bash
kubectl ate get actor my-counter-1 -a ate-demo-counter   # RUNNING, with a worker
kubectl ate get workers -n ate-demo-counter
```

> If you get `403`, the client's SPIFFE ID isn't on
> `--ingress-allowed-spiffe-ids`. Redeploy atenet with the full list (Step 3).

---

## Step 8: Prove state survives suspend/resume

This is the payoff. Suspend the actor with `--mode=sync`, which waits until the
snapshot has reached the GCS bucket. The default, async, keeps the snapshot on
the node and uploads it in the background:

```bash
kubectl ate suspend actor my-counter-1 -a ate-demo-counter --mode=sync
kubectl ate get actor my-counter-1 -a ate-demo-counter   # SUSPENDED, no worker
```

Hit it again with the proxy still running. The actor resumes from its snapshot,
possibly on a different worker, and the counter **continues from where it left
off** instead of resetting:

```bash
curl -X POST -i http://localhost:8000/
```

Follow the actor's logs, or its lifecycle events, across the cycle:

```bash
kubectl ate logs actor my-counter-1 -a ate-demo-counter -f
kubectl ate logs actor my-counter-1 -a ate-demo-counter --source=lifecycle
```

---

## Step 9: Clean up

Delete the actor. This works in any state:

```bash
kubectl ate delete actor my-counter-1 -a ate-demo-counter
```

Remove the demo (its namespace, WorkerPool, and template):

```bash
go run ./cmd/ate-setup delete demo counter
```

Remove the Substrate control plane, or use `delete all` to also remove every
registered demo:

```bash
go run ./cmd/ate-setup delete ate-system
```

Remove the GCP resources from Step 2. Run this from the **substrate-gke**
checkout:

> **Run cleanup only in a dedicated demo project, or on resources you know were
> created for this guide.** `--all` also deletes the snapshot transfer and node
> service accounts and the dashboards. Every Substrate cluster in the project
> shares those.

```bash
cd ~/gitrepos/substrate-gke

# You brought the cluster: keep it, delete the buckets and the bindings on them.
./tools/cleanup-gcp --project "$PROJECT_ID" --cluster "$CLUSTER_NAME" \
  --location "$CLUSTER_LOCATION" --bucket "$BUCKET_NAME" --keep-cluster

# setup-gcp created the cluster: delete it, its buckets, and its bindings, but
# keep the shared accounts.
tools/setup-gcp/teardown.sh --cluster-scoped

# Delete everything, including the shared service accounts and dashboards.
tools/setup-gcp/teardown.sh --all
```

`cleanup-gcp` asks for confirmation and keeps the Artifact Registry repo unless
you pass `--delete-repository`. APIs stay enabled, and they cost nothing while
unused.

---

## What just happened (mapping to the architecture)

| Step | Substrate mechanism |
|---|---|
| Deploy demo | `ate-controller` turns the `WorkerPool` into a Deployment of `ateworker-gvisor` pods. ate-api-server stores the `ActorTemplate` in PostgreSQL, boots it once, and publishes a **golden snapshot** tag named by the template UID |
| Create actor | ate-api-server writes the actor record to PostgreSQL. No worker is used yet |
| First request | `atenet-router` (Envoy) checks the client's SPIFFE ID, reads `ate-target-actor`, and calls `ResumeActor`. It parks the request for up to `--parked-request-budget` (5s) |
| Resume | ate-api-server picks a worker with free capacity and doesn't take the whole worker. `atelet` streams the snapshot, and `ateworker-gvisor` restores it into a gVisor sandbox. State → `RUNNING` |
| Suspend | `ateworker-gvisor` checkpoints memory and disk with `runsc`. `atelet` uploads the snapshot to GCS on a per-actor token from ate-api-server's credential exchange, which impersonates `ate-snapshot-transfer`. The sandbox is freed, and the worker stays warm for other actors. State → `SUSPENDED` |
| Resume again | The actor restores from its **last** snapshot, so its in-memory state (the counter) carries across the cycle |

Only the config resources (`WorkerPool`, `SandboxConfig`) are Kubernetes CRDs.
Templates and the high-churn instance state (`Actor`, `Worker`, `Tag`) live in
PostgreSQL behind the ate API, which keeps the Kubernetes control plane out of
the request hot path.

---

## Why GKE (the Pod Certificate requirement)

Substrate's components authenticate to each other with **Pod Certificates**: the
apiserver, router, egress gateway, PostgreSQL clients, and `kubectl ate proxy`.
These are `podCertificate` projected volumes, signed by Substrate's own
`pod-certificate-controller`, with trust distributed through
**ClusterTrustBundles**. A pod that can't mount its certificate never starts.

GKE 1.37 serves `PodCertificateRequest` and `ClusterTrustBundle` under
`certificates.k8s.io/v1` by default. That's why 1.37 is the floor, and why the
old `--enable-kubernetes-unstable-apis` step is gone. Upstream supports the
latest stable Kubernetes release and the previous minor. Upstream 1.37 turns
these APIs on by default, so any 1.37 cluster serves them. For AKS, see
[setup-aks.md](setup-aks.md). On older clusters you need control of the
apiserver to turn them on: kind (the CI path, where
`hack/create-kind-cluster.sh` sets them up), Cluster API, kubeadm, or k3s.

> Pod Certificates secure Substrate's **own infrastructure**. Actor identity is
> separate. The actor identity CA (ECDSA P-256) and actor JWTs signed by
> `ate-idp-server` identify actors to the egress gateway and the snapshot
> credential exchange. The old `SessionIdentity` service (`MintJWT` /
> `MintCert`) no longer exists.

---

## Coming from the pre-1.0 install

- **There's no in-place upgrade from 0.x or an RC to 1.0.0.** Reinstall. Rolling
  upgrades are supported from 1.x onward (`docs/guides/upgrade.md`). The cleanest
  path is a fresh cluster. To reuse the cluster, remove the old install with the
  tooling that created it (`./hack/install-ate.sh --delete-all` from that old
  checkout) before Step 3.
- **Remove the old atelet and node grants.** The May install granted atelet
  `storage.objectAdmin` and `artifactregistry.reader` **on the project**, plus
  `objectAdmin` and `bucketViewer` on the bucket. It also granted the default
  Compute Engine SA `storage.objectViewer` and `artifactregistry.reader` on the
  project. v1.0.0 needs none of these, and `setup-gcp` only adds bindings. From
  the substrate-gke checkout:
  ```bash
  tools/setup-gcp/teardown.sh --revoke-atelet-permissions
  tools/setup-gcp/teardown.sh --revoke-gke-node-permissions
  ```
  Run the bucket-scoped removals from the
  [setup-gcp README](https://github.com/ai-on-gke/substrate-gke/blob/main/tools/setup-gcp/README.md#moving-to-per-actor-snapshot-credentials)
  too, **after** v1.0.0 is installed. On an older release, removing them breaks
  every suspend and resume with `403`.
- **Snapshots and templates don't carry over.** Recreate the ActorTemplates with
  `kubectl ate create actor-template`. Any `kind: ActorTemplate` CRD YAML has to
  be converted to the API-record shape. See
  `demos/counter/counter-template.yaml.tmpl` at the tag.
- **Images now run as their own `USER` and `WORKDIR`.** An image with a non-root
  `USER` stops running as root and has no effective capabilities. atelet refuses
  its old image cache, so delete `/var/lib/ate/image-cache` on each node once no
  actor runs there, or reboot the node. `capabilities.add` is limited to an
  allowlist, and unknown capability names are rejected.

---

## Troubleshooting

- **`kubectl ate` not found:** add `$(go env GOPATH)/bin` to your `PATH`, or
  install the release binary (Step 5).
- **`setup-gcp` stops on the cluster version:** the control plane or a node pool
  is older than 1.37. Upgrade with the commands it prints, or create a fresh pool
  on 1.37.
- **`ate-setup` refuses to deploy on GKE:** `SNAPSHOT_LOCATION` or
  `SNAPSHOT_TRANSFER_GSA_NAME` isn't set. Re-source `.ate-dev-env.sh`.
  `--credential-provider` is also required.
- **System pods stuck not-ready:** run `kubectl get pods -n ate-system`, then
  `kubectl describe` or `kubectl logs` the stuck pod. If a pod can't mount its
  `podCertificate` volume, check that the node pool runs 1.37+. The
  `objectstore-plugin` sidecar in the ate-api-server pod (the credential
  exchange) fetches the actor JWT keys from `ate-idp-server` through OIDC
  discovery. It exits on a certificate error. If `ate-idp-server` is unreachable,
  it only logs a warning, and snapshot transfers fail with `UNAVAILABLE` until a
  fetch succeeds.
- **Image pull errors on the demo:** you deployed the demo with `--image-repo`
  (there are no published demo images), or the node pool's SA lacks
  `artifactregistry.reader` on `KO_DOCKER_REPO`'s repository. Re-run `bootstrap`,
  which grants every pool's SA.
- **Image pull errors on actor images:** atelet pulls actor images under its own
  Workload Identity. Grant `ate-system/atelet` `artifactregistry.reader` on each
  actor image repo. `setup-gcp` prints the command.
- **`403` from GCS on suspend or resume:** check the snapshot transfer SA's
  bucket roles, ate-api-server's `serviceAccountTokenCreator` on that SA, and that
  Workload Identity and the GKE Metadata Server are on the pool ate-api-server
  runs on.
- **`403` from the router:** the client's SPIFFE ID isn't allowlisted. Each
  `deploy atenet` / `deploy ate-system` **replaces** the list, so pass the full
  list every time.
- **Golden snapshot never appears:** run
  `kubectl ate get actor-template counter -a ate-demo-counter -o yaml` and read the
  crash message. Actors created in the meantime cold-boot, which isn't an error.
- **Actor `CRASHED`:** you can't resume it.
  `kubectl ate revert actor <a> -a <atespace>` returns it to its last external
  snapshot.

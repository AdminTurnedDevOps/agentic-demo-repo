---
title: "Agent Substrate Demo: Install, Deploy, and Run a Stateful Actor on AKS"
date: 2026-11-06
description: >
  End-to-end walkthrough for installing Agent Substrate v1.0.0 on an existing
  AKS cluster running Kubernetes 1.37, deploying the stateful counter demo, and driving an
  actor through its full create / resume / suspend / delete lifecycle.
tags: [agent-substrate, kubernetes, aks, azure, gvisor, actors, workers]
author: Michael Levan
---

# Agent Substrate Demo (AKS)

This guide takes you from an AKS cluster you already run to a stateful
**actor** on [Agent Substrate](https://github.com/agent-substrate/substrate)
v1.0.0. Substrate is installed with `ate-setup` from the Substrate repo.
Snapshots are stored in an S3-compatible object store (RustFS) running inside
the cluster.

> What you'll see: a counter actor that preserves its in-memory value across a
> full **suspend → snapshot → resume** cycle, even when it lands on a different
> worker pod. That is the core Substrate capability: multiplexing many idle
> actors onto a small pool of warm pods.

> **AKS isn't an upstream install target.** `ate-setup` v1.0.0 knows two cluster
> profiles: kind, and GKE for everything else. This guide runs the GKE profile on
> AKS. It patches the v1.0.0 manifests for S3 storage and stubs out the
> GCP-only settings. It's built from the v1.0.0 source and **hasn't yet been run
> end to end on an AKS cluster**. The open questions are marked **TODO**. For
> the supported path, see the [GKE guide](setup-gke.md).

### What the patch changes

The [patch](aks/substrate-v1.0.0-aks.patch) edits three files in
`manifests/ate-install/`. `ate-setup` renders those files for a full install
and for the partial redeploys (`deploy atelet`, `deploy ate-api-server`), so
the patched settings hold either way:

| File | Change | Why |
|---|---|---|
| `ate-api-server.yaml` | The `objectstore-plugin` sidecar uses `ATE_STORAGE_BACKEND=s3`, plus the `AWS_*` settings for RustFS, with keys from the `ate-objectstore-s3` Secret | `ate-setup` hardcodes GCS everywhere but kind |
| `atelet.yaml` | The same storage change on atelet's sidecar. It also drops `--image-credential-provider-*` and their `hostPath` mounts | The mounts are GKE paths. On AKS, `FileOrCreate` leaves an empty file that atelet can't parse, and it crash-loops. Without the flags, atelet pulls anonymously |
| `base/kustomization.yaml` | Drops `atenet-router-monitoring.yaml` | That's a GKE Managed Prometheus `PodMonitoring`. The kind doesn't exist on AKS, and `ate-setup` applies strictly, so the whole install would stop on it |

`ate-setup` has no setting for any of these, so the patch is required.
Telemetry isn't patched: see [Limits on AKS](#limits-on-aks).

The patch, RustFS, and the Secret are the same S3 wiring upstream's own kind
overlay uses (`manifests/ate-install/kind/`), moved onto the base manifests.

---

## Prerequisites

### Cluster

A **Standard** AKS cluster (not AKS Automatic) running **Kubernetes 1.37 or
later** on the control plane **and every node pool**. 1.37 serves the
PodCertificateRequest and ClusterTrustBundle APIs as `certificates.k8s.io/v1`,
and they're on by default. Substrate needs both.

- **Not AKS Automatic.** `atelet` runs a privileged container with `hostPath`
  mounts, and the worker pods it manages run with seccomp and AppArmor
  `Unconfined` and extra capabilities. Automatic's deployment safeguards reject
  them. So does an Azure Policy assignment that bans privileged containers or
  `hostPath`. Check yours before you start.
- **Linux nodes, amd64.** This guide uses Ubuntu nodes. Azure Linux is
  untested here.
- **A network plugin that enforces NetworkPolicy.** The install denies ingress
  to every pod in `ate-system` by default, then allows specific traffic. This
  guide uses Azure CNI powered by Cilium. Azure NPM or Calico also enforce
  policy. Without one, the policies do nothing.
- **The OIDC issuer enabled** (`--enable-oidc-issuer`). ate-api-server trusts
  service account tokens from that issuer, and fetches its discovery document
  over the internet, so ate-api-server needs outbound access to
  `*.oic.prod-aks.azure.com`.
- **One VM size for the worker nodes, in one zone.** A snapshot restores onto
  any worker in the pool, so the nodes need the same CPU features. Azure Disks
  are zonal, so one zone also keeps the Postgres and RustFS volumes reachable.

> **Turn off automatic upgrades on pools that run workers, and don't use spot
> nodes for them.** When a worker pod is deleted, its actors get 30 minutes to
> suspend. An actor that's still awake when that window closes goes to
> `CRASHED`. A crashed actor can't be resumed, and its state is lost unless you
> revert it. AKS cluster auto-upgrade and node OS image upgrades both drain
> nodes on their own schedule. Turn both off for the whole cluster, and change
> versions with the
> [rolling upgrade runbook](https://github.com/agent-substrate/substrate/blob/v1.0.0/docs/guides/upgrade.md)
> instead.

Note the current channels, so you can restore them after the demo, then turn
both off:

```bash
az aks show -g <cluster-resource-group> -n <cluster-name> \
  --query '{cluster: autoUpgradeProfile.upgradeChannel, nodeOS: autoUpgradeProfile.nodeOsUpgradeChannel}'

az aks update -g <cluster-resource-group> -n <cluster-name> \
  --auto-upgrade-channel none --node-os-upgrade-channel None
```

### Required tools

| Tool | Version | Notes |
|---|---|---|
| Go | ≥ 1.27.3 | The v1.0.0 `go.mod` toolchain. `ate-setup` runs with `go run`. If your Go is older, `GOTOOLCHAIN=auto` can download the right one |
| Azure CLI (`az`) | recent | Checks and updates the cluster, and creates the ACR |
| `kubectl` | 1.36 or 1.37 | Within one minor of the cluster |
| `git` | any recent | Applies the patch |
| Docker | recent | `az acr login` writes its credentials into Docker's config, and `ko` reads them to push the demo image |
| `openssl` | any | Generates the RustFS secret key |
| `curl` | any recent | Sends traffic to the actor in Steps 9–10 |
| AWS CLI | optional | Only to list the snapshot bucket in Step 10 |

You don't install PostgreSQL, Envoy, RustFS, or the worker images yourself.
`ate-setup` and the manifests in this guide deploy them.

### Get the source

```bash
mkdir -p ~/gitrepos && cd ~/gitrepos

# Substrate itself, pinned to the release: ate-setup, manifests, demos, kubectl-ate
git clone --branch v1.0.0 https://github.com/agent-substrate/substrate.git substrate-v1.0.0
```

You also need this guide's support files. They're in
[`aks/`](aks/) next to this page:

| File | What it is |
|---|---|
| [`aks/substrate-v1.0.0-aks.patch`](aks/substrate-v1.0.0-aks.patch) | The manifest patch (Step 3) |
| [`aks/rustfs.yaml`](aks/rustfs.yaml) | RustFS, its volume, the bucket-init Job, and its NetworkPolicy (Step 4) |

> **Use a clean clone of the tag.** The manifests come from the checkout, even
> when you install prebuilt images, so the checkout has to match the image tag,
> and the patch only applies to v1.0.0. `ate-setup` also sources
> `.ate-dev-env.sh` from the checkout root if one exists. A leftover dev env file
> will silently change your install.

---

## Step 1: Configure environment

Write the settings to an env file outside the checkout. Change the values
marked `<...>`:

```bash
cat > ~/gitrepos/substrate-aks.env <<'EOF'
export RESOURCE_GROUP='<cluster-resource-group>'
export CLUSTER='<cluster-name>'
export ACR_NAME='<name>'

export AKS_FILES='<path-to-this-repo>/substrate/install-and-setup/aks'

export KO_DOCKER_REPO=${ACR_NAME}.azurecr.io/ate

export KUBECTL_CONTEXT=$CLUSTER

export SNAPSHOT_LOCATION=s3://ate-snapshots/

export PROJECT_ID=unused-on-aks
export SNAPSHOT_TRANSFER_GSA_NAME=unused-on-aks

unset CLUSTER_NAME CLUSTER_LOCATION

export ATE_CREDENTIAL_PROVIDER='{"name":"k8s.io"}'

export ATE_INGRESS_ALLOWED_SPIFFE_IDS=spiffe://cluster.local/ns/ate-system/sa/atenet-client

export ATE_INSTALL_SANDBOX_CLASSES=gvisor
EOF

source ~/gitrepos/substrate-aks.env
```

---

## Step 2: Prepare the registry


### Create the registry

`ko` pushes the counter demo image here in Step 6. Create it in the cluster's
resource group, with anonymous pull, which needs the **Standard** or
**Premium** SKU:

```bash
az acr create --resource-group "$RESOURCE_GROUP" --name "$ACR_NAME" --sku Standard
az acr update --name "$ACR_NAME" --anonymous-pull-enabled true
```

> **Anonymous pull makes every repository in the registry public.** Use a new
> registry that holds only demo and actor images, not one you already have.
> atelet pulls actor images itself, not through the kubelet. Without the
> GKE-specific credential provider flags, it can only pull anonymously. See
> [Limits on AKS](#limits-on-aks) for the alternative.

Attach it to the cluster, so the kubelet can pull the worker image:

```bash
az aks update -g "$RESOURCE_GROUP" -n "$CLUSTER" --attach-acr "$ACR_NAME"
```

Connect to ACR.

```bash
az acr login --name "$ACR_NAME"
```

---

## Step 3: Patch the Substrate checkout

Outside kind, `ate-setup` assumes GKE. It reads its manifests from this
checkout, and they hardcode GCS snapshot storage, GKE paths for atelet's image
credentials, and a GKE-only `PodMonitoring`. On AKS these break snapshots, crash
atelet, and stop the install. `ate-setup` has no settings for them, so the patch
changes the manifests instead.

```bash
cd ~/gitrepos/substrate-v1.0.0
git apply --check "$AKS_FILES/substrate-v1.0.0-aks.patch"   # dry run, prints nothing on success
git apply "$AKS_FILES/substrate-v1.0.0-aks.patch"
```

> Keep this checkout for this cluster. Every later `ate-setup deploy` reads the
> patched manifests from it. A redeploy from an unpatched checkout switches
> storage back to GCS and breaks every suspend and resume. `git apply -R` with
> the same file undoes the patch.

---

## Step 4: Create the snapshot store

Substrate's two `objectstore-plugin` sidecars read and write snapshots: one next
to ate-api-server, and one next to every atelet. After Step 3, both point at
`http://rustfs.ate-system.svc:9000` and take their keys from the
`ate-objectstore-s3` Secret. Create both before the install, so those pods start
on the first try:

```bash
kubectl create namespace ate-system --dry-run=client -o yaml | kubectl apply -f -

kubectl -n ate-system create secret generic ate-objectstore-s3 \
  --from-literal=AWS_ACCESS_KEY_ID=ate-snapshots \
  --from-literal=AWS_SECRET_ACCESS_KEY="$(openssl rand -hex 24)"

kubectl apply -f "$AKS_FILES/rustfs.yaml"
kubectl -n ate-system rollout status deploy/rustfs --timeout=5m
kubectl -n ate-system wait job/rustfs-bucket-init --for=condition=complete --timeout=5m
kubectl -n ate-system logs job/rustfs-bucket-init | tail -1     # bucket ate-snapshots created
```

`rustfs.yaml` is upstream's kind RustFS with these changes: credentials from the
Secret, a 100 GiB volume on the default StorageClass (Azure Disk), a `Recreate`
rollout so the disk never has two pods, and resource requests. Its
NetworkPolicy admits only ate-api-server, atelet, and the bucket-init Job.

> **Don't recreate the Secret with a new key** unless you also restart RustFS,
> ate-api-server, and atelet. They read it only at start.

> **RustFS is one pod on one disk.** That's enough for a demo, but losing the
> disk loses every snapshot. For anything longer-lived, point the sidecars at a
> real S3-compatible service instead: change `AWS_ENDPOINT_URL`, `AWS_REGION`,
> and the Secret, and set `SNAPSHOT_LOCATION` to that bucket. Azure Blob Storage
> doesn't speak S3, and v1.0.0 has no Blob backend.

---

## Step 5: Install the Agent Substrate system

From the patched checkout, deploy the control plane from the published v1.0.0
images. `ko` doesn't run, and you need no write access to a registry:

```bash
cd ~/gitrepos/substrate-v1.0.0
source ~/gitrepos/substrate-aks.env

go run ./cmd/ate-setup deploy ate-system \
  --context "$KUBECTL_CONTEXT" \
  --image-repo ghcr.io/agent-substrate/substrate \
  --image-tag v1.0.0 \
  --snapshot-location "$SNAPSHOT_LOCATION" \
  --credential-provider="$ATE_CREDENTIAL_PROVIDER" \
  --ingress-allowed-spiffe-ids="$ATE_INGRESS_ALLOWED_SPIFFE_IDS" \
  --sandbox-classes=gvisor
```

The env file already supplies every flag but the image ones. They're spelled
out so you can see what the install depends on. Before it touches the cluster,
check the report it prints:

- `storage.snapshotLocation` is `s3://ate-snapshots/`;
- `context` is your AKS context.

There's no issuer flag. With no GKE coordinates set, `ate-setup` reads the
service account token issuer from the cluster's OIDC discovery document. On
AKS with the OIDC issuer enabled, that's your `oic.prod-aks.azure.com` URL.

This deploys the following components:

| Component | What it is |
|---|---|
| CRDs (`ate.dev/v1`) | `WorkerPool`, `SandboxConfig`, `CSIDriverConfig` |
| `postgres` | Bundled PostgreSQL, the state store for actors, templates, workers, tags, and policies. It authenticates with pod certificates, not passwords. Its volume is 500 GiB on the default StorageClass |
| `ate-api-server` | gRPC control plane: actor lifecycle, scheduling, and authz. Its `objectstore-plugin` sidecar copies and deletes snapshots in RustFS |
| `ate-idp-server` | Issues and publishes the keys for actor JWTs (OIDC discovery) |
| `ate-controller` | Reconciles WorkerPools into worker Deployments |
| `pod-certificate-controller` | Signs the pod certificates for mTLS between components |
| `atelet` | Node DaemonSet for images, sandbox assets, and snapshot streaming. Its `objectstore-plugin` sidecar moves snapshots to and from RustFS |
| `atenet-router` | Ingress to actors (Envoy). TLS only, admits allowlisted SPIFFE IDs, and routes on `ate-target-actor` |
| `atenet-egress` | Default-deny egress gateway, with credential injection |
| `k8s-credential-provider` | Serves `ate-secret://k8s.io/...` credentials to the egress gateway |
| `SandboxConfig/gvisor-default` | The gVisor runtime assets |

Wait for the system pods:

```bash
kubectl get pods -n ate-system --watch
```

Then check that both sidecars came up on S3:

```bash
kubectl -n ate-system get deploy/ate-api-server ds/atelet \
  -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.spec.template.spec.initContainers[?(@.name=="objectstore-plugin")].env[?(@.name=="ATE_STORAGE_BACKEND")].value}{"\n"}{end}'
# ate-api-server: s3
# atelet: s3
kubectl -n ate-system logs deploy/ate-api-server -c objectstore-plugin | head
```

And that ate-api-server trusts your cluster's issuer. The two URLs must match
exactly:

```bash
kubectl -n ate-system get cm ate-api-authentication -o yaml | grep issuer
az aks show -g "$RESOURCE_GROUP" -n "$CLUSTER" --query oidcIssuerProfile.issuerUrl -o tsv
```

If the ConfigMap shows `https://kubernetes.default.svc`, discovery failed.
Redeploy with `--ateapi-expected-jwt-issuer "<issuerUrl from az aks show>"`.

Each run writes a record of the install:

```
recorded this configuration in ~/Library/Caches/ate-setup/installs/<context>.yaml
```

**Keep that file.** Later `deploy` runs take it with `--config`, so a partial
redeploy doesn't drop settings. Run them **from the patched checkout**:

```bash
go run ./cmd/ate-setup deploy atenet \
  --config ~/Library/Caches/ate-setup/installs/$KUBECTL_CONTEXT.yaml \
  --ingress-allowed-spiffe-ids="$ATE_INGRESS_ALLOWED_SPIFFE_IDS,spiffe://cluster.local/ns/shop/sa/frontend"
```

> **Other install options**
> - **Postgres storage:** the bundled database asks for 500 GiB on the default
>   StorageClass, which is Standard SSD on AKS. For Premium SSD, add
>   `--ateapi-postgres-storage-class managed-csi-premium`. For an external
>   Postgres, such as Azure Database for PostgreSQL, set
>   `ATE_API_POSTGRES_READ_WRITE_CONNECTION_STRING` (env only). See
>   `docs/guides/postgres.md`. **TODO:** not tried against Azure Database for
>   PostgreSQL.
> - **Telemetry:** add `--otlp-endpoint http://<your-collector>:4317`. It
>   rewrites `ate-otel-config` and restarts the components. The install record
>   keeps it, so later `deploy --config` runs apply it again. With
>   `--atenet-dataplane agentgateway`, the router's own
>   `AGENTGATEWAY_OTLP_ADDRESS` still points at `gke-managed-otel`, and
>   `--otlp-endpoint` doesn't change it.
> - **agentgateway dataplane:** `--atenet-dataplane agentgateway` renders
>   `manifests/ate-install/agentgateway`, which builds on the patched `base`. The
>   patch covers it.
> - **Dedicated system pools:** add AKS node pools with the
>   `ate.dev/workloadType=ate-system-infra` and `ate-postgres` labels and taints
>   (`az aks nodepool add --labels ... --node-taints ...:NoSchedule`), then
>   `--cordon-system-infra-components`.
> - **Settings as a file:** `--config substrate-install.yaml`, with
>   `kind: SubstrateInstall`. See `docs/guides/operator-install.md`.

---

## Step 6: Deploy the counter demo

The counter demo is a small stateful Go HTTP server that increments an in-memory
counter on every request. Deploying it creates:

- the `ate-demo-counter` namespace;
- a `WorkerPool` CRD;
- an **atespace** called `ate-demo-counter`;
- an **ActorTemplate** API record, `counter`, in that atespace.

**Releases don't publish demo images.** Run this **without** `--image-repo`, so
`ko` builds the demo image and its worker image, and pushes them to
`KO_DOCKER_REPO` in your ACR:

```bash
go run ./cmd/ate-setup deploy demo counter --context "$KUBECTL_CONTEXT"
```

Two components pull those images:

| Image | Pulled by | Works because |
|---|---|---|
| `ateworker-gvisor` (the worker pod) | the kubelet | `--attach-acr` |
| `counter` (the actor) | **atelet** | anonymous pull on the ACR |

Check the pool, and wait for the template's golden snapshot. The `GOLDEN TAG`
column fills in once it's ready, and `ERROR` shows if the build failed:

```bash
kubectl get workerpool -n ate-demo-counter
kubectl get pods -n ate-demo-counter -o wide
go run ./cmd/kubectl-ate get actor-templates -a ate-demo-counter   # or `kubectl ate` after Step 7
```

- **WorkerPool** `counter` is the pool of warm worker pods that actors are
  multiplexed onto. It runs 3 replicas of `ateworker-gvisor`, each limited to 1
  CPU and 1 GiB. Each worker hosts many actors, each in its own sandbox.
- **ActorTemplate** `counter` is the immutable actor definition. Substrate boots
  it once and saves a **golden snapshot** to RustFS, so new actors start from
  that.

> The golden snapshot is the first real test of the storage path. If it never
> appears, check the troubleshooting entries for S3 and image pulls before going
> further.

---

## Step 7: Install the CLI

`kubectl-ate` is a `kubectl` plugin for managing atespaces, templates, actors,
and workers. Use the v1.0.0 build. Either take the release binary:

```bash
curl -fsSLO https://github.com/agent-substrate/substrate/releases/download/v1.0.0/kubectl-ate-darwin-arm64
curl -fsSLO https://github.com/agent-substrate/substrate/releases/download/v1.0.0/kubectl-ate-darwin-arm64.sha256
shasum -a 256 -c kubectl-ate-darwin-arm64.sha256
install -m 0755 kubectl-ate-darwin-arm64 "$(go env GOPATH)/bin/kubectl-ate"   # must be on PATH
```

or build it from the tag checkout:

```bash
go install ./cmd/kubectl-ate
```

Make sure `$(go env GOPATH)/bin` is on your `PATH`:

```bash
echo 'export PATH="$PATH:$(go env GOPATH)/bin"' >> ~/.zshrc
source ~/.zshrc
which kubectl-ate && kubectl ate --help
```

`kubectl ate` port-forwards to `svc/api` in `ate-system` on its own, and checks
the API server's certificate against the cluster's ClusterTrustBundles. Without
`--token-file`, it acts as the shared `ate-client` ServiceAccount. That's fine
for a demo. Real users need their own identities: see
`docs/guides/authentication.md` and `docs/guides/authorization.md`.

---

## Step 8: Create an actor

```bash
kubectl ate create actor my-counter-1 -a ate-demo-counter --template counter
kubectl ate get actor my-counter-1 -a ate-demo-counter
```

Actors live in an **atespace**, Substrate's own namespace (not a Kubernetes
namespace). `--template` names a template in that atespace. The actor is created
without taking a worker. Its first request resumes it.

---

## Step 9: Drive traffic to the actor

The router accepts mTLS connections only from allowlisted SPIFFE IDs, and picks
the actor from the `ate-target-actor: <atespace>/<actor>` header.
`kubectl ate proxy actor` handles both. It presents the `atenet-client` identity
you allowlisted in Step 5.

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
3. atelet fetches the golden snapshot from RustFS, and `ateworker-gvisor`
   restores it into a new gVisor sandbox.
4. The router forwards the request.

Send it a few more times and watch the counter increment. Then look at the actor
and the workers:

```bash
kubectl ate get actor my-counter-1 -a ate-demo-counter   # RUNNING, with a worker
kubectl ate get workers -n ate-demo-counter
```

---

## Step 10: Prove state survives suspend/resume

Suspend the actor with `--mode=sync`, which waits until the snapshot has
reached the bucket:

```bash
kubectl ate suspend actor my-counter-1 -a ate-demo-counter --mode=sync
kubectl ate get actor my-counter-1 -a ate-demo-counter   # SUSPENDED, no worker
```

Hit it again with the proxy still running. The actor resumes from its snapshot,
possibly on a different worker, and the counter **continues from where it left
off**:

```bash
curl -X POST -i http://localhost:8000/
```

Follow the actor across the cycle:

```bash
kubectl ate logs actor my-counter-1 -a ate-demo-counter -f
kubectl ate logs actor my-counter-1 -a ate-demo-counter --source=lifecycle
```

To see the snapshots themselves, port-forward to RustFS and list the bucket.
This needs the AWS CLI locally:

```bash
kubectl -n ate-system port-forward svc/rustfs 9000:9000 &
AWS_ACCESS_KEY_ID=$(kubectl -n ate-system get secret ate-objectstore-s3 -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' | base64 -d) \
AWS_SECRET_ACCESS_KEY=$(kubectl -n ate-system get secret ate-objectstore-s3 -o jsonpath='{.data.AWS_SECRET_ACCESS_KEY}' | base64 -d) \
AWS_REGION=us-east-1 \
  aws --endpoint-url http://localhost:9000 s3 ls s3://ate-snapshots/ --recursive | head
kill %1
```

---

## Step 11: Clean up

Delete the actor and the demo:

```bash
kubectl ate delete actor my-counter-1 -a ate-demo-counter
go run ./cmd/ate-setup delete demo counter --context "$KUBECTL_CONTEXT"
```

Remove the control plane. This deletes the `ate-system` namespace, and with it
RustFS, its volume, every snapshot, and the `ate-objectstore-s3` Secret:

```bash
go run ./cmd/ate-setup delete ate-system --context "$KUBECTL_CONTEXT"
```

Deleting the namespace also deletes the Postgres and RustFS PVCs, and with
them their Azure Disks.

Detach the registry from the cluster, then delete it:

```bash
az aks update -g "$RESOURCE_GROUP" -n "$CLUSTER" --detach-acr "$ACR_NAME"
az acr delete --name "$ACR_NAME" --yes
```

The cluster keeps the settings from the prerequisites. The OIDC issuer stays
on, because it can't be turned off. To get automatic upgrades back, set the
channels you noted before you turned them off, for example:

```bash
az aks update -g "$RESOURCE_GROUP" -n "$CLUSTER" \
  --auto-upgrade-channel patch --node-os-upgrade-channel NodeImage
```

To reuse the Substrate checkout for another platform, undo the patch:

```bash
git -C ~/gitrepos/substrate-v1.0.0 apply -R "$AKS_FILES/substrate-v1.0.0-aks.patch"
```

---

## What just happened (mapping to the architecture)

| Step | Substrate mechanism |
|---|---|
| Deploy demo | `ate-controller` turns the `WorkerPool` into a Deployment of `ateworker-gvisor` pods. ate-api-server stores the `ActorTemplate` in PostgreSQL, boots it once, and writes a **golden snapshot** to RustFS |
| Create actor | ate-api-server writes the actor record to PostgreSQL. No worker is used yet |
| First request | `atenet-router` (Envoy) checks the client's SPIFFE ID, reads `ate-target-actor`, and calls `ResumeActor`. It parks the request for up to `--parked-request-budget` (5s) |
| Resume | ate-api-server picks a worker with free capacity. `atelet`'s sidecar streams the snapshot from RustFS, and `ateworker-gvisor` restores it into a gVisor sandbox. State → `RUNNING` |
| Suspend | `ateworker-gvisor` checkpoints memory and disk with `runsc`. `atelet`'s sidecar uploads the snapshot to RustFS with the Secret's keys. The worker stays warm for other actors. State → `SUSPENDED` |
| Resume again | The actor restores from its **last** snapshot, so the counter carries across the cycle |

Upstream Kubernetes 1.37 turns on
PodCertificateRequest, ClusterTrustBundle, and the ClusterTrustBundle projected
volume by default. AKS 1.37 runs those defaults, so the cluster needs no special
API flags.

---

## Limits on AKS

These come from v1.0.0 itself, not from this guide:

- **No per-actor snapshot credentials.** On GCS, ate-api-server hands each
  transfer a token scoped to one actor's snapshots. On S3, that exchange answers
  `UNIMPLEMENTED`. Every atelet holds keys that can read and write **every**
  snapshot in the bucket. A compromised node can read any actor's state.
- **No Azure Blob backend.** The `objectstore-plugin` serves GCS and S3 only.
  Upstream `main` adds `pkg/objectstore/actorauthz` for out-of-tree providers,
  but v1.0.0 has no Blob plugin.
- **atelet pulls actor images anonymously.** The patch removes the GKE
  credential-provider wiring, because AKS keeps its plugin elsewhere. **TODO
  (unverified):** AKS nodes ship the kubelet ACR credential provider at
  `/var/lib/kubelet/credential-provider/acr-credential-provider`, with config
  `/var/lib/kubelet/credential-provider-config.yaml`, which reads
  `/etc/kubernetes/azure.json`. Pointing atelet's
  `--image-credential-provider-config` and `--image-credential-provider-bin-dir`
  mounts at those paths might let it pull from a private ACR with the kubelet
  identity. Confirm the paths on a node (`kubectl debug node/...`) before you
  rely on it. atelet runs the plugin inside its own container, so that container
  also needs `/etc/kubernetes/azure.json` mounted at the same path, and the
  binary has to run in atelet's image.
- **gVisor only.** `ate-setup` stages the microVM guest assets with `gcloud`
  on any non-kind cluster. microVM also needs `/dev/kvm`, which means
  nested-virtualization VM sizes. Untested on AKS.
- **No managed telemetry.** The components export OTLP to `gke-managed-otel`,
  which doesn't exist on AKS, so they log export errors and the data is
  dropped. Nothing else is affected, and the Prometheus `/metrics` endpoints
  keep working. Set `--otlp-endpoint` to send telemetry to your own collector.
- **`ate-setup` still believes it's on GKE.** It prints `PROJECT_ID` and the
  transfer service account in its report, and writes the account into
  `ate-api-server-envvars`. Both are inert on S3.

---

## Troubleshooting

- **`az aks get-upgrades` doesn't offer `1.37`:** AKS hasn't reached your
  region yet, or the cluster is more than one minor version behind. Upgrade
  one minor version at a time.
- **`ate-setup` runs `gcloud container clusters get-credentials`:**
  `KUBECTL_CONTEXT` isn't set. Re-source the env file, or pass `--context`.
- **`ate-setup` refuses to deploy, asking for `SNAPSHOT_TRANSFER_GSA_NAME` or
  `PROJECT_ID`:** the env file isn't sourced. Both need a placeholder value on
  AKS.
- **`while applying PodMonitoring ... no matches for kind`:** the checkout
  isn't patched, or the patch was undone. Re-run Step 3.
- **`ate-api-server` or `atelet` stuck in `CreateContainerConfigError`:** the
  `ate-objectstore-s3` Secret is missing. Create it (Step 4).
- **`atelet` crash-loops with `Failed to configure image pull credentials`:**
  it's running the unpatched manifest. Re-run Step 3, then redeploy atelet from
  the patched checkout.
- **System pods stuck in `ContainerCreating`:** run `kubectl describe` on the
  pod. A `podCertificate` or `clusterTrustBundle` mount error means a node pool
  is older than 1.37, or `pod-certificate-controller` isn't running yet.
- **`401 Unauthenticated` from `kubectl ate`:** ate-api-server doesn't trust the
  token's issuer. Compare
  `kubectl -n ate-system get cm ate-api-authentication -o yaml` with
  `az aks show ... --query oidcIssuerProfile.issuerUrl`. If they differ, redeploy
  with `--ateapi-expected-jwt-issuer`. ate-api-server also needs outbound HTTPS
  to `*.oic.prod-aks.azure.com` to fetch the keys.
- **Suspend or resume fails with an S3 error (`connection refused`,
  `AccessDenied`, `NoSuchBucket`):** check, in order:
  `kubectl -n ate-system get pods -l app=rustfs`;
  `kubectl -n ate-system logs job/rustfs-bucket-init`;
  and the sidecar's logs:
  `kubectl -n ate-system logs ds/atelet -c objectstore-plugin`.
  `AccessDenied` usually means the Secret changed after RustFS started; restart
  RustFS. A timeout usually means the NetworkPolicy dropped the traffic: check
  the pods are labeled `app=ate-api-server` / `app=atelet`.
- **`ErrImagePull` on worker pods:** the cluster can't pull from the ACR. Run
  `az aks check-acr -g "$RESOURCE_GROUP" -n "$CLUSTER" --acr "$ACR_NAME.azurecr.io"`.
- **Golden snapshot fails with an image pull error for the counter image:**
  atelet can't pull it anonymously. Check
  `az acr show -n "$ACR_NAME" --query anonymousPullEnabled` is `true`, and that
  the SKU isn't Basic.
- **Worker pods rejected at admission:** an Azure Policy assignment or
  deployment safeguards blocks privileged pods, `hostPath`, or `Unconfined`
  seccomp. Exempt `ate-system` and the worker namespaces, or use a cluster
  without them.
- **`403` from the router:** the client's SPIFFE ID isn't allowlisted. Each
  `deploy atenet` / `deploy ate-system` **replaces** the list, so pass the full
  list every time.
- **Actor `CRASHED`:** you can't resume it.
  `kubectl ate revert actor <a> -a <atespace>` returns it to its last external
  snapshot.

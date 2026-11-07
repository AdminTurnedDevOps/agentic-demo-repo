# Agent Substrate v1.0.0 setup checklist (GKE)

## Pre-flight

- [ ] Two checkouts:
    - `ai-on-gke/substrate-gke`, for `tools/setup-gcp`, `teardown.sh`, and `cleanup-gcp`
    - `agent-substrate/substrate` at tag **`v1.0.0`**, a clean clone (`ate-setup`, manifests, demos)
- [ ] Go ≥ 1.27.3, `gcloud` + `gke-gcloud-auth-plugin`, `kubectl`, `git`. Also Docker with buildx, only for source or demo builds.
- [ ] `gcloud auth login`, `gcloud auth application-default login`, and `gcloud auth configure-docker <KO_DOCKER_REPO host>`.
- [ ] `.ate-dev-env.sh` copied from substrate-gke's `tools/setup-gcp/ate-dev-env.sh.example`, edited, and sourced. It needs:
    - `PROJECT_ID`, `PROJECT_NUMBER`, `GCE_REGION`, `CLUSTER_LOCATION`, `CLUSTER_NAME`
    - `BUCKET_NAME` (56 characters or fewer)
    - `SNAPSHOT_LOCATION=gs://${BUCKET_NAME}/` (required on GKE)
    - `SNAPSHOT_TRANSFER_GSA_NAME=ate-snapshot-transfer` (required on GKE)
    - `KO_DOCKER_REPO`
    - `ATE_CREDENTIAL_PROVIDER` (required): `{"name":"k8s.io"}` or `{"enabled":false}`
    - `ATE_INGRESS_ALLOWED_SPIFFE_IDS`. Empty means no ingress to actors. `kubectl ate proxy` needs `spiffe://cluster.local/ns/ate-system/sa/atenet-client`
    - `ATE_INSTALL_SANDBOX_CLASSES`: `gvisor`, or the default `gvisor,microvm`

## Cluster

- [ ] GKE **Standard**, not Autopilot. atelet and the workers are privileged and use `hostPath`.
- [ ] GKE **1.37+** on the control plane **and every node pool**. PodCertificateRequest and ClusterTrustBundle are served as `v1` by default, so the `--enable-kubernetes-unstable-apis` step is gone.
- [ ] Workload Identity enabled (`${PROJECT_ID}.svc.id.goog`).
- [ ] GKE Metadata Server (`GKE_METADATA`) on every pool Substrate pods can land on.
- [ ] Node auto-upgrade **off** on worker pools, and no spot or preemptible nodes for workers.
- [ ] Optional: dedicated `ate-system-infra` and `ate-postgres` pools, tainted `ate.dev/workloadType=<pool>:NoSchedule`. Then install with `--cordon-system-infra-components` (formerly `--cordon-control-plane`).
- [ ] microVM only: a pool with nested virtualization (`/dev/kvm`) on a non-`e2` machine type. Optional taint `ate.dev/sandboxClass=microvm:NoSchedule`.

## GCP resources (`go -C tools/setup-gcp run . bootstrap --create-repository --atelet-snapshot-access=false`)

- [ ] Snapshot bucket `${BUCKET_NAME}`, with uniform bucket-level access.
- [ ] Asset bucket `${BUCKET_NAME}-assets`, for microVM guest assets.
- [ ] Snapshot transfer SA `ate-snapshot-transfer@${PROJECT_ID}.iam.gserviceaccount.com`.
- [ ] `ate-system/ate-api-server` WI principal:
    - `storage.objectAdmin` and `storage.bucketViewer` on the snapshot bucket
    - `iam.serviceAccountTokenCreator` on the transfer SA
- [ ] Transfer SA: `storage.objectAdmin` and `storage.bucketViewer` on the snapshot bucket.
- [ ] `ate-system/atelet` WI principal:
    - `storage.objectViewer` on the **asset** bucket only. atelet gets **no** snapshot bucket access in v1.0.0.
    - `artifactregistry.reader` on the Substrate image repo, plus each actor image repo
- [ ] Node SA: `container.defaultNodeServiceAccount` on the project, plus `artifactregistry.reader` on the image repo. No storage roles.
- [ ] Artifact Registry repo for `KO_DOCKER_REPO`. The demo images are always built from source.
- [ ] Coming from the pre-1.0 install? Remove the old **project-level** atelet and default-compute-SA grants:
    - `teardown.sh --revoke-atelet-permissions`
    - `teardown.sh --revoke-gke-node-permissions`
    - the bucket-scoped atelet grants, after v1.0.0 is up

## Install (from the `v1.0.0` checkout)

- [ ] `go run ./cmd/ate-setup deploy ate-system --image-repo ghcr.io/agent-substrate/substrate --image-tag v1.0.0 --storage-bucket-name=$BUCKET_NAME --credential-provider=... --ingress-allowed-spiffe-ids=...`
- [ ] Read the settings report it prints (each value and where it came from).
- [ ] Install record written to `~/Library/Caches/ate-setup/installs/<context>.yaml`. Keep it for `--config` on later deploys and upgrades.

`deploy ate-system` does all of the following, so none of it is a manual step anymore:

- [ ] CRDs `ate.dev/v1`: `WorkerPool`, `SandboxConfig`, `CSIDriverConfig`. **ActorTemplate is no longer a CRD.**
- [ ] Namespaces `ate-system` and `podcertificate-controller-system`.
- [ ] CA pools and secrets:
    - pod certificate controller CAs
    - the actor identity CA (ECDSA P-256)
    - the JWT authority pool
    - the egress MITM CA
    - (The Session identity CA is **gone**.)
- [ ] `podcertificate-controller` and the ClusterTrustBundles.
- [ ] Bundled **PostgreSQL**, which replaces valkey. It uses pod-certificate auth with no passwords. For an external DB or Cloud SQL, use `ATE_API_POSTGRES_*`.
- [ ] `ate-api-server`, `ate-idp-server`, and `ate-controller`, with the API config, authentication config, and env ConfigMaps.
- [ ] `atenet-router` (Envoy by default) and `atenet-egress`.
- [ ] `k8s-credential-provider`, when the provider is `{"name":"k8s.io"}`.
- [ ] `atelet` DaemonSet.
- [ ] `SandboxConfig/gvisor-default`, plus `SandboxConfig/microvm` with its assets staged to `gs://${BUCKET_NAME}-assets` when microVM is enabled.

## Verify

- [ ] `kubectl get pods -n ate-system`. Ready:
    - Deployments: `ate-api-server`, `ate-controller`, `ate-idp-server`, `atenet-router`, `atenet-egress`, `k8s-credential-provider`
    - StatefulSet: `postgres`
    - DaemonSet: `atelet`, one per node
- [ ] `kubectl get pods -n podcertificate-controller-system`. `podcertificate-controller` is Ready.
- [ ] `kubectl get crd | grep ate.dev`. The three CRDs exist, served at `v1`.
- [ ] `kubectl get sandboxconfig`. `gvisor-default` exists, plus `microvm` if enabled.
- [ ] `kubectl ate --help` works. Use the v1.0.0 release binary or `go install ./cmd/kubectl-ate` from the tag.
- [ ] `go run ./cmd/ate-setup deploy demo counter`, run **without** `--image-repo` (no demo images are published).
- [ ] `kubectl ate get actor-templates -a ate-demo-counter`. `GOLDEN TAG` is set and `ERROR` is empty.
- [ ] `kubectl ate create actor my-counter-1 -a ate-demo-counter --template counter`
- [ ] `kubectl ate proxy actor my-counter-1 -a ate-demo-counter`, then `curl -X POST -i http://localhost:8000/` increments.
- [ ] `kubectl ate suspend actor my-counter-1 -a ate-demo-counter --mode=sync`, then `curl` again. The count continues.

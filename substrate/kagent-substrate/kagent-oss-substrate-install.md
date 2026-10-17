# kagent OSS on Agent Substrate: Install

In kagent 1.0, Substrate is no longer an optional add-on. Every agent runs as a Substrate actor. No agent gets a Deployment. kagent stores sessions, A2A history, and lifecycle state in PostgreSQL. kagent, Substrate, and PostgreSQL authenticate to each other with Kubernetes Pod Certificates.

The `kagent install` CLI command sets all of this up in one step. This guide covers that command, lists what it runs, shows how to check the result, and explains how to remove everything afterwards.

---

## Versions used

| Component | Version | Source |
| --- | --- | --- |
| kagent CLI | `v1.0.0-alpha14` | `https://github.com/kagent-dev/kagent/releases/tag/v1.0.0-alpha14` |
| kagent charts (`kagent`, `kagent-crds`) | `1.0.0-alpha14` | `oci://ghcr.io/kagent-dev/kagent/helm/` |
| Substrate charts (`substrate`, `substrate-crds`, `substrate-podcert`) | `0.5.0-alpha2` | `oci://ghcr.io/kagent-dev/substrate/helm/` |
| Worker image | `ghcr.io/kagent-dev/substrate/ateom-gvisor:v0.5.0-alpha2` | GHCR |
| Development PostgreSQL | `postgres:18-alpine` (digest-pinned by the CLI) | Docker Hub |

The kagent release pins the Substrate version: `go.mod` replaces `github.com/agent-substrate/substrate` with `github.com/kagent-dev/substrate v0.5.0-alpha2`. The Substrate Helm charts come from the **kagent-dev** fork. The upstream `agent-substrate/substrate` repo does not publish them.

> Both projects are pre-1.0 and their APIs change between alphas. Check these versions again before you upgrade.

---

## Prerequisites

### Tools

- `kubectl`, matching your cluster's minor version.
- `helm` with OCI registry support (v3.8 or later). `kagent install` runs `helm` to install the charts. The charts in this guide were rendered with helm v4.2.0.
- The `kagent` CLI at **v1.0.0-alpha14**. Older CLIs (for example the Homebrew 0.8.x build) install the pre-1.0 architecture. A locally built `dev` CLI refuses to install with `installation requires a released version of kagent`.

### Model provider API key

The CLI reads the provider key from the environment, not from a flag. It refuses to install if the key for the selected provider is not set.

| `install.defaultModelProvider` | Environment variable |
| --- | --- |
| `OpenAI` (default) | `OPENAI_API_KEY` |
| `Anthropic` | `ANTHROPIC_API_KEY` |
| `AzureOpenAI` | `AZURE_OPENAI_API_KEY` |
| `Gemini` | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| `Ollama` | `OLLAMA_API_KEY` |

### An existing Substrate install

`kagent install` runs `helm upgrade --install substrate` (and `substrate-crds`) in `ate-system`. Plan for one of these cases before you run it:

- **A Substrate install from upstream manifests** (`hack/install-ate*.sh`, `manifests/ate-install/`) is not a Helm release and will conflict. Remove it first, or use a clean cluster.
- **A Helm release of an older `substrate` chart** in `ate-system` is upgraded to 0.5.0-alpha2. Upgrading from 0.0.x or 0.4.x requires PostgreSQL (see below) and recreates the ActorTemplates. Treat this as a reinstall, not an in-place upgrade.
- **kagent CRDs left from a pre-1.0 install** (`kagent.dev/v1alpha2`) stop the install with `Kagent CRDs from a previous installation exist outside Helm`. Run `kagent uninstall`, or delete those CRDs, before you install.

---

## Step 1: Install the kagent CLI

Download the release binary for your platform. Available assets: `darwin-arm64`, `darwin-amd64`, `linux-arm64`, `linux-amd64`, and `windows-amd64.exe`.

```bash
export KAGENT_VERSION=v1.0.0-alpha14
export KAGENT_ASSET=kagent-darwin-arm64

curl -fsSL -o kagent \
  "https://github.com/kagent-dev/kagent/releases/download/${KAGENT_VERSION}/${KAGENT_ASSET}"
curl -fsSL -o kagent.sha256 \
  "https://github.com/kagent-dev/kagent/releases/download/${KAGENT_VERSION}/${KAGENT_ASSET}.sha256"

# Compare the two hashes
shasum -a 256 kagent
cat kagent.sha256

chmod +x kagent
sudo mv kagent /usr/local/bin/kagent
```

If Homebrew already installed an older `kagent`, make sure `/usr/local/bin` comes before `/opt/homebrew/bin` on your `PATH`, or run `brew uninstall kagent`.

```bash
kagent version
```

The output should report `"kagent_version":"1.0.0-alpha14"`.

---

## Step 2: Install kagent and Substrate

```bash
export OPENAI_API_KEY=<your-key>        # or the variable for your provider

kagent install
# or, with a config file:
# kagent --config kagent-config.yaml install
```

To use your own PostgreSQL instead of the bundled development database, add `--skip-database-setup`. You then supply the connection Secrets through values files (see [Bring your own PostgreSQL](#bring-your-own-postgresql)).

### What `kagent install` runs

Each chart is installed with `helm upgrade --install --wait --wait-for-jobs --timeout 5m --history-max 2`, in this order:

| # | Step | Namespace | What it does |
| --- | --- | --- | --- |
| 1 | `kagent-crds` chart | `kagent` | Installs the `api.kagent.dev/v1alpha3` CRDs: Agent, AgentTemplate, Harness, ModelConfig, ModelProviderConfig, RemoteMCPServer, SandboxTemplate |
| 2 | `substrate-crds` chart | `ate-system` | Installs the `ate.dev/v1alpha1` CRDs: WorkerPool, SandboxConfig, CSIDriverConfig |
| 3 | Substrate prerequisites (Go code, no Helm) | `ate-system`, `podcertificate-controller-system` | Creates the namespaces, the CA pool Secrets (`actor-id-ca-pool`, `actor-id-ca-certs`, `egress-mitm-ca-pool`, `service-dns-ca-pool`, `pod-identity-ca-pool`, `postgres-ca-pool`), the `actor-id-jwt-pool` Secret, and the `ate-api-authentication` ConfigMap, which holds the cluster's OIDC issuer |
| 4 | `substrate-podcert` chart | `podcertificate-controller-system` | Installs the Pod Certificate controller, which issues mTLS certificates to kagent, Substrate, and PostgreSQL clients |
| 5 | Bundled PostgreSQL (`kubectl apply --server-side`) | `kagent` | Creates the `kagent-postgresql` ConfigMap, PVC, Deployment, and Service. Runs the kagent and Substrate setup SQL. Creates the Secrets `kagent-postgres-owner`, `kagent-postgres-readwrite`, `substrate-postgres-owner`, and `substrate-postgres-readwrite` |
| 6 | `substrate` chart | `ate-system` | Installs ate-api-server, ate-controller, atelet, atenet-router, atenet-egress, and RustFS (bucket `ate-snapshots`, created by a Job) |
| 7 | `kagent` chart | `kagent` | Installs the controller, UI, tool server, default ModelConfig, and **WorkerPool `kagent-default`** |

Row 3 creates Secrets in a serialized CA pool format using Go code in the CLI (`go/core/cli/internal/commands/substrate_init.go`). No `kubectl` or `helm` command does the same thing, so on 1.0.0-alpha10 and later, use `kagent install`. To install Substrate with plain Helm from the kagent charts, use the 0.10.x line described in [Helm-only install with the kagent charts](#helm-only-install-with-the-kagent-charts-kagent-0103--substrate-subchart).

The CLI adds these values to the `kagent` chart:

```yaml
controller:
  substrateClientCertificate:
    enabled: true
config:
  substrate:
    apiEndpoint: dns:///api.ate-system.svc:443
    routerUrl: http://atenet-router.ate-system.svc:80
substrateWorkerPool:
  create: true
  workerImage: "ghcr.io/kagent-dev/substrate/ateom-gvisor:v0.5.0-alpha2"
database:
  postgres:
    clientCertificate:
      enabled: true      # omitted with --skip-database-setup
providers:
  default: openAI        # from install.defaultModelProvider
```

It also adds a credential-provider grant to the `substrate` chart, so the `kagent` atespace can read Secrets in the `kagent` namespace. Without `--skip-database-setup`, it also sets `postgres.clientCertificates.enabled=true`.

```yaml
credentialProvider:
  namespacePolicies:
    - atespace: "kagent"
      allowedNamespaces: ["kagent"]
```

---

## Helm-only install with the kagent charts (kagent 0.10.3 + Substrate subchart)

The kagent Helm charts can install Substrate themselves. With `substrate.enabled=true`:

- `kagent-crds` pulls in the `substrate-crds` subchart.
- `kagent` pulls in the `substrate` subchart.

No CLI and no separate Substrate releases are needed. This works on kagent **v0.9.10 through v0.10.3** and **v1.0.0-alpha1 through alpha9**. It was removed in v1.0.0-alpha10 (kagent PR #2708).

The steps below pin the current stable release. The commands were checked with `helm template` against the published charts.

| Component | Version |
| --- | --- |
| kagent charts (`kagent`, `kagent-crds`) | `0.10.3` (`oci://ghcr.io/kagent-dev/kagent/helm/`) |
| Substrate subcharts (`substrate`, `substrate-crds`) | `0.0.9`, bundled in the kagent charts |
| Worker image | `ghcr.io/kagent-dev/substrate/ateom-gvisor:v0.0.9` |
| kagent API | `kagent.dev/v1alpha2`: `SandboxAgent`, `AgentHarness`, `Agent`, `ModelConfig`, and others |

How this differs from the 1.0.0-alpha14 path above:

- **No special cluster settings.** The 0.0.9 subchart defaults to `auth.mode=jwt`, which uses projected ServiceAccount tokens, so the Pod Certificate feature gates are not needed. The chart also generates its own TLS certificates and session signing keys.
- **Everything installs into the kagent namespace.** Substrate components go into the release namespace (`kagent`, not `ate-system`), with the release name as a prefix: `kagent-api`, `kagent-atenet-router`, `kagent-ate-controller`, `kagent-atelet`, `kagent-valkey-cluster`, `kagent-rustfs`, and `kagent-dns`. The `controller.substrate.*` endpoints below point at those names.
- **The chart includes PostgreSQL.** The `kagent` chart deploys PostgreSQL itself (`database.postgres.bundled.enabled=true`, default size `500Mi`).
- **The API server uses a self-signed certificate.** The ate-api server certificate is signed by a CA the chart generates, and the kagent controller does not mount that CA. Set `controller.substrate.ateApiInsecure=true`.

### Install the CRDs (kagent + Substrate)

```bash
export KAGENT_VERSION=0.10.3

helm upgrade --install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
  --version "${KAGENT_VERSION}" \
  --namespace kagent \
  --create-namespace \
  --wait \
  --timeout 5m \
  --set kmcp.enabled=true \
  --set substrate.enabled=true
```

This installs the `kagent.dev` CRDs, the kmcp CRDs, and the `ate.dev` CRDs: `ActorTemplate`, `SandboxConfig`, and `WorkerPool`.

### Install kagent with Substrate enabled

```bash
export OPENAI_API_KEY=<your-key>

helm upgrade --install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --version "${KAGENT_VERSION}" \
  --namespace kagent \
  --create-namespace \
  --wait \
  --timeout 15m \
  --set providers.default=openAI \
  --set providers.openAI.apiKey="${OPENAI_API_KEY}" \
  --set kmcp.enabled=true \
  --set substrate.enabled=true \
  --set controller.substrate.enabled=true \
  --set controller.substrate.ateApiEndpoint=dns:///kagent-api.kagent.svc:443 \
  --set controller.substrate.atenetRouterURL=http://kagent-atenet-router.kagent.svc:80 \
  --set controller.substrate.ateApiInsecure=true \
  --set controller.substrate.ateApiServer.namespace=kagent \
  --set controller.substrate.ateApiServer.serviceAccount=kagent-ate-api-server \
  --set substrateWorkerPool.create=true \
  --set substrateWorkerPool.replicas=2 \
  --set-string substrateWorkerPool.ateomImage=ghcr.io/kagent-dev/substrate/ateom-gvisor:v0.0.9
```

What each Substrate flag does:

| Flag | Why |
| --- | --- |
| `substrate.enabled=true` | Installs the bundled Substrate subchart: ate-api-server, ate-controller, atelet, atenet DNS and router, Valkey (6 replicas), RustFS (bucket `ate-snapshots`), and the `gvisor-default` SandboxConfig |
| `controller.substrate.enabled=true` | Turns on the controller's Substrate integration (it is off by default) |
| `controller.substrate.ateApiEndpoint` / `atenetRouterURL` | Points the controller at the subchart's Services in `kagent`. The defaults assume `ate-system` |
| `controller.substrate.ateApiInsecure=true` | Accepts the chart's self-signed ate-api certificate |
| `controller.substrate.ateApiServer.namespace` / `.serviceAccount` | Grants the subchart's ate-api ServiceAccount read access to Secrets and ConfigMaps. ActorTemplates use these as env sources. The defaults are `ate-system` / `ate-api-server` |
| `substrateWorkerPool.create=true` + `ateomImage` | Creates WorkerPool `kagent/kagent-default`. The chart fails with `substrateWorkerPool.ateomImage is required when substrateWorkerPool.create=true` if the image is empty. The controller uses this pool by default (`SUBSTRATE_DEFAULT_WORKERPOOL_NAME`) |

**GKE and other managed clusters:** the subchart's JWT issuer defaults to `https://kubernetes.default.svc.cluster.local`, which matches kind. On GKE, also pass the cluster's own issuer:

```bash
--set substrate.auth.jwt.issuer="$(kubectl get --raw /.well-known/openid-configuration | jq -r .issuer)"
```

**Substrate already running in `ate-system`:** set `substrate.enabled=false` on both charts and point the controller at the existing Services instead. Use `controller.substrate.ateApiEndpoint=dns:///api.ate-system.svc:443` and `controller.substrate.atenetRouterURL=http://atenet-router.ate-system.svc:80`, and leave the `ateApiServer.*` defaults as they are.

### Verify

```bash
helm list -n kagent
kubectl get pods -n kagent
kubectl get workerpool -n kagent
kubectl get sandboxconfig
```

You should see:

- the `kagent` and `kagent-crds` releases
- these pods `Running`: `kagent-controller`, `kagent-ui`, `kagent-postgresql`, `kagent-ate-api-server-deployment-*`, `kagent-ate-controller-*`, `kagent-atelet-*`, `kagent-atenet-router-*`, `kagent-dns-*`, `kagent-valkey-cluster-*`, and `kagent-rustfs-*`
- two `kagent-default` worker pods
- a `gvisor-default` SandboxConfig

### Uninstall

```bash
helm uninstall kagent -n kagent
helm uninstall kagent-crds -n kagent   # deletes all kagent.dev and ate.dev custom resources cluster-wide
```

---

## Step 4: Verify the platform

```bash
helm list -A
```

The output should list five releases: `kagent` and `kagent-crds` in `kagent`, `substrate` and `substrate-crds` in `ate-system`, and `substrate-podcert` in `podcertificate-controller-system`.

```bash
kubectl get pods -n podcertificate-controller-system
kubectl get pods -n ate-system
kubectl get pods -n kagent
```

All pods should be `Running`, and the RustFS bucket-init Job should be `Completed`. In `kagent` you should see the `kagent-controller`, `kagent-ui`, `kagent-tools`, `kagent-grafana-mcp`, and `kagent-postgresql` Deployments, plus the `kagent-default` worker pod.

```bash
kubectl get workerpool -n kagent
kubectl get sandboxconfig
kubectl get modelconfig -n kagent
```

You should see `kagent-default` with 1 replica, a `gvisor-default` SandboxConfig, and `default-model-config`.

---

## Step 5: WorkerPool

The `kagent` chart creates one WorkerPool, because the CLI sets `substrateWorkerPool.create=true`:

- WorkerPool: `kagent/kagent-default` (`ate.dev/v1alpha1`)
- Workers: **1** replica (the chart default) using `ateom-gvisor:v0.5.0-alpha2`
- Sandbox class: `gvisor`
- ServiceAccount: `kagent-default`

The kagent controller and UI do not need the WorkerPool. Agents do: every Harness has a required `spec.substrate.workerPoolRef` that names a WorkerPool **in the same namespace**.

Sizing guidance:

- Each running session actor uses one worker slot until it is suspended.
- Overlapping conversations need more workers.

To scale **temporarily** (the CRD has a `scale` subresource):

```bash
kubectl scale workerpool kagent-default -n kagent --replicas=2
```

A later `kagent install` or `helm upgrade` resets the replica count. To make the change **durable**, re-run `kagent install` with a kagent values file (`install.kagent.valuesFiles`) that contains:

```yaml
substrateWorkerPool:
  replicas: 2
```

For micro-VM workers, set `substrateWorkerPool.sandboxClass: microvm` and a matching `ateom-microvm` `workerImage`. You also need a `microvm` SandboxConfig, the runtime assets, and nodes with KVM. kagent does not install these. See [`../microvm/`](../microvm/).

---

## Next step

To create a Harness, AgentTemplate, and Agent and run them on Substrate, see [Create an agent](create-an-agent.md).

---

## Bring your own PostgreSQL

`kagent install --skip-database-setup` skips row 5 of the install table (bundled PostgreSQL). For this path:

1. As a database admin, run kagent's `go/core/pkg/postgressetup/setup.sql` and Substrate's `pkg/postgressetup/setup.sql` (kagent-dev/substrate `v0.5.0-alpha2`). The kagent `helm/README.md` lists the exact `psql` variables.
2. Create the connection Secrets:
   - in `kagent`: `kagent-postgres-owner` (key `ownerConnectionString`) and `kagent-postgres-readwrite` (key `readWriteConnectionString`)
   - in `ate-system`: the Substrate owner and read/write Secrets, named by `postgres.ownerConnectionStringSecretRef` and `postgres.readWriteConnectionStringSecretRef`
3. If your Secrets use other names, point each chart at them with `install.kagent.valuesFiles` and `install.substrate.valuesFiles`.

Leave `database.postgres.clientCertificate.enabled` and `postgres.clientCertificates.enabled` set to `false`, unless your database trusts the Substrate `postgres-ca-pool` CA.

---

## Certificate authority lifetime

`kagent install` creates the Substrate CAs once, and they **expire one year later**. Nothing renews them, and running `kagent install` again keeps the existing CAs. To rotate them:

```bash
kubectl delete secret -n ate-system actor-id-ca-pool actor-id-ca-certs egress-mitm-ca-pool
kubectl delete secret -n podcertificate-controller-system service-dns-ca-pool pod-identity-ca-pool postgres-ca-pool
kagent install
# then restart the Substrate and kagent workloads
```

---

## Cleanup

`kagent uninstall` removes **only** the `kagent` and `kagent-crds` releases. The commands below remove everything else that `kagent install` created.

> Uninstalling `kagent-crds` and `substrate-crds` deletes every Agent, Harness, WorkerPool, and other custom resource of those types in **all** namespaces.

```bash
kagent uninstall

helm uninstall substrate      -n ate-system
helm uninstall substrate-crds -n ate-system
helm uninstall substrate-podcert -n podcertificate-controller-system

# Bundled PostgreSQL (deletes all kagent and Substrate data)
kubectl delete -n kagent deployment/kagent-postgresql service/kagent-postgresql \
  configmap/kagent-postgresql pvc/kagent-postgresql \
  secret/kagent-postgres-owner secret/kagent-postgres-readwrite \
  secret/substrate-postgres-owner secret/substrate-postgres-readwrite

# CA pools and auth config created by the CLI
kubectl delete secret -n ate-system actor-id-jwt-pool actor-id-ca-pool actor-id-ca-certs egress-mitm-ca-pool
kubectl delete configmap -n ate-system ate-api-authentication
kubectl delete secret -n podcertificate-controller-system service-dns-ca-pool pod-identity-ca-pool postgres-ca-pool

kubectl delete namespace kagent ate-system podcertificate-controller-system
```

On kind, you can delete the whole cluster instead: `kind delete cluster --name kagent`.

---

## What changed since the previous version of this guide

| Previous guide | Now (kagent 1.0.0-alpha14) |
| --- | --- |
| Substrate was an optional subchart; `substrate.enabled=false` reused an existing install | From 1.0.0-alpha10 on, the kagent chart no longer bundles Substrate. Substrate is installed as its own releases (`substrate-crds`, `substrate-podcert`, `substrate`) at a pinned version. The subchart is still available on 0.10.x (see [Helm-only install](#helm-only-install-with-the-kagent-charts-kagent-0103--substrate-subchart)) |
| `kmcp.enabled=true` | Removed. Not a chart value |
| `database.postgres.bundled.storage` | The kagent chart no longer deploys PostgreSQL. `kagent install` deploys a development PostgreSQL, or you supply `database.postgres.{owner,readWrite}ConnectionStringSecretRef` |
| `controller.substrate.enabled`, `.ateApiEndpoint`, `.atenetRouterURL`, `.defaultWorkerPool.name` | `config.substrate.apiEndpoint` and `config.substrate.routerUrl`. Each Harness names its WorkerPool through `spec.substrate.workerPoolRef` (there is no controller-wide default) |
| `controller.substrate.ateApiInsecure=true` | Replaced by mTLS: `controller.substrateClientCertificate.enabled=true` plus the Pod Certificate controller |
| `substrateWorkerPool.ateomImage` / `workerImage` `v0.0.26` | `substrateWorkerPool.workerImage` `ghcr.io/kagent-dev/substrate/ateom-gvisor:v0.5.0-alpha2`. The chart fails to render if `create=true` and `workerImage` is empty |
| WorkerPool with 2 replicas | Chart default is 1 replica |
| `kagent.dev/v1alpha2` `SandboxAgent` / `AgentHarness` | `api.kagent.dev/v1alpha3` `Agent` + `AgentTemplate` + `Harness` (`kagent`, `claude`, `codex`, or `byo`). Every agent runs on Substrate |
| Harness `allowedAgentTemplates.selector` + `kagent.dev/harness` label on the AgentTemplate | Removed. An `Agent` pairs one template (`spec.template.ref` or inline) with one Harness (`spec.harnessRef`) |
| `AgentInstance` created by `kagent create agent-instance --harness --agent-template` | `Session`: `kagent agent session create --agent <name>`, then `kagent agent invoke --session <id> --task "..."` |
| `ActorTemplate` was a Kubernetes CRD | ActorTemplates are ate-api records that the kagent controller registers. `substrate-crds` ships only WorkerPool, SandboxConfig, and CSIDriverConfig |
| No cluster requirements | Pod Certificate feature gates and the `certificates.k8s.io/v1beta1` API are required |

---

## References

- kagent repo: `helm/README.md` (PostgreSQL, sandbox class, upgrade and uninstall) and `docs/architecture/README.md` (resource ownership and the end-to-end flow)
- kagent CLI install code: `go/core/cli/internal/commands/install.go`, `substrate_init.go`, and `bundled_postgres.go`
- Substrate chart README: `oci://ghcr.io/kagent-dev/substrate/helm/substrate` `0.5.0-alpha2`
- [kagent docs](https://kagent.dev/docs/kagent)

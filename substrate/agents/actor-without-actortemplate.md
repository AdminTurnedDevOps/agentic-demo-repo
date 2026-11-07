# Deploy an Actor Without the ActorTemplate CRD

Tldr; `kubectl apply -f ActorTemplate` is gone. The *idea* of an ActorTemplate
is not. Templates are now a Substrate control-plane resource in an **atespace**,
created with `kubectl ate create actor-template`. This lab deploys a counter
actor on that path and proves `kubectl get actortemplate` is the wrong API.

---

## Why

### Why Did The ActorTemplate CRD Go Away

ActorTemplate left the Kubernetes API because the team decided substrate-plane objects should be ateapi resources, not CRDs. Kubernetes leaked the wrong identity, naming, lifecycle, and auth into the public API (kubectl apply, namespaces, CRD conventions), so CLI, SaaS, and gRPC clients could not share one surface and the schema could not evolve independently of kube. Templates belong with actors in the control-plane store; kube stays behind the scenes for capacity (WorkerPools → Deployments). After golden-snapshot reconcile moved into ate-api-server, the CRD was unused dual state, so they deleted it on 2026-09-02.


### When the CRD went away

The `ActorTemplate` **Kubernetes CRD** (`actortemplates.ate.dev`) was **deleted
on 2026-09-02** in
[agent-substrate/substrate#1376](https://github.com/agent-substrate/substrate/pull/1376)
(`120a5196`, *Delete ActorTemplate CRD*).

The API cutover landed the day before, **2026-09-01**, in
[agent-substrate/substrate#1353](https://github.com/agent-substrate/substrate/pull/1353)
(*Full cutover: Drop the k8s CRD ActorTemplate fields in the ate apiserver*).
After that PR, `ate-api-server` no longer reads templates from etcd. Demos
were switched the same day in
[#1355](https://github.com/agent-substrate/substrate/pull/1355). Docs that still
called the template a CRD were cleaned up on **2026-09-04** in
[#1404](https://github.com/agent-substrate/substrate/pull/1404).

If you `kubectl apply` an `apiVersion: ate.dev/v1alpha1` `kind: ActorTemplate`
manifest against a cluster installed from Substrate **v1.0.0**, Kubernetes
rejects it: that CRD is not installed. (v1.0.0 also stopped serving
`ate.dev/v1alpha1` altogether; the remaining CRDs are `ate.dev/v1`.)

### What replaces it

**The same object, a different store and a different CLI.**

| CRD era (before 2026-09-02) | v1.0.0 |
|---|---|
| `kind: ActorTemplate` Kubernetes CRD in a **namespace** | `substrate.ateapi.v1.ActorTemplate` ate-API resource in an **atespace** |
| Stored in etcd | Stored in the control-plane **PostgreSQL** database |
| `kubectl apply -f template.yaml` | `kubectl ate create actor-template -f template.yaml` |
| `kubectl get actortemplate -n <ns>` | `kubectl ate get actor-templates -a <atespace>` |
| `kubectl wait --for=condition=Ready actortemplate/...` | Poll `kubectl ate get actor-template` until `GOLDEN TAG` is set |
| `--template <namespace>/<name>` | `--template <name>` plus `--atespace` / `-a` (the name resolves in the actor's atespace) |
| Host `<actor>.actors.resources.substrate.ate.dev` | No Host/DNS routing. `atenet-router` routes on the `ate-target-actor: <atespace>/<actor>` header over mTLS; from a workstation, `kubectl ate proxy actor <actor> -a <atespace>` |

The replacement is still called **ActorTemplate**. Creating one still triggers
the golden snapshot. Actors still derive from it. What changed is *where it
lives* and *which binary you talk to*.

`ate-api-server` owns templates through `substrate.ateapi.v1.Control`:
`CreateActorTemplate`, `GetActorTemplate`, `ListActorTemplates`,
`DeleteActorTemplate`. `kubectl-ate` is the client. The manifest is
**protojson** (the same shape `kubectl ate get actor-template -o yaml`
prints), not a Kubernetes object. Unknown fields are an error.

Templates are **immutable**. There is no update. New version = new template
name (or delete and recreate). A **suspended** actor can be repointed to the
new template with `kubectl ate update actor <actor> --template=<new> -a <atespace>`.

There is **no `sandboxConfig`** on a v1.0.0 template. The sandbox class lives
on the `WorkerPool` (`spec.sandboxClasses`, `gvisor` or `microvm`); the
template's `workerSelector` picks which pools its actors may run on.

### What is still a Kubernetes CRD

Do not throw out `kubectl apply` for the whole platform. These three are still CRDs:

| Resource | API | Tool |
|---|---|---|
| `WorkerPool` | `ate.dev/v1` CRD | `kubectl apply` / `kubectl get workerpool` |
| `SandboxConfig` | cluster-scoped `ate.dev/v1` CRD | `kubectl get sandboxconfig` |
| `CSIDriverConfig` | cluster-scoped `ate.dev/v1` CRD | `kubectl get csidriverconfig` |

Capacity is still a Kubernetes Deployment. The workload blueprint is not.

### What is now ate API

| Resource | API | Tool |
|---|---|---|
| `ActorTemplate` | ate API (Postgres) | `kubectl ate … actor-template` |
| `Atespace` | ate API (Postgres) | `kubectl ate … atespace` |
| `Actor` | ate API (Postgres) | `kubectl ate … actor` |
| `Worker` (assignment record) | ate API (Postgres) | `kubectl ate get workers` |

---

## What this lab proves

| Beat | Proof |
|---|---|
| The CRD is gone | `kubectl get crd actortemplates.ate.dev` fails; `kubectl get actortemplate` returns nothing useful |
| The replacement exists | `kubectl ate get actor-templates -a ate-demo-counter` shows `counter` with a golden tag |
| Deploy an actor on the new path | `kubectl ate create actor … --template counter -a ate-demo-counter` |
| Routing includes the atespace | `kubectl ate proxy actor my-counter-1 -a ate-demo-counter` addresses the actor as `ate-demo-counter/my-counter-1` |
| State still survives suspend | Counter continues after suspend → resume |

---

## What Substrate pieces this uses

| Concept | Where it lives |
|---|---|
| `WorkerPool` `counter` | Kubernetes CRD (`ate.dev/v1`) in namespace `ate-demo-counter`. Warm pods. Still `kubectl apply`. |
| `Atespace` `ate-demo-counter` | Ate API. Must exist before the template. Same name as the pool namespace by convention, not by requirement. |
| `ActorTemplate` `counter` | Ate API in that atespace. Protojson manifest. Golden snapshot owned by a golden **tag** in object storage. |
| `Actor` `my-counter-1` | Ate API record. Starts `SUSPENDED`. Hydrates from the golden snapshot on first resume. |
| Ingress | `atenet-router` (TLS + client mTLS, SPIFFE allowlist), routed by `ate-target-actor: ate-demo-counter/my-counter-1`. `kubectl ate proxy actor` sets this up for you. |

---

## Prerequisites

- A cluster with the Substrate **v1.0.0** control plane installed. The
  [setup lab](../install-and-setup/setup-gke.md) through
  `go run ./cmd/ate-setup deploy ate-system ...` is enough for the system
  pods. The install **must** include
  `--ingress-allowed-spiffe-ids=spiffe://cluster.local/ns/ate-system/sa/atenet-client`;
  that is the identity `kubectl ate proxy actor` presents, and without it no
  client can reach actors.
- A Substrate checkout of the **v1.0.0** tag:

  ```bash
  git clone --branch v1.0.0 https://github.com/agent-substrate/substrate.git
  ```

  The overlay's nested clone at `substrate/substrate` is **too old** (it
  still has `actortemplate_types.go`). Run every `go run ./cmd/ate-setup`
  command below from the v1.0.0 checkout root.
- `kubectl-ate` **rebuilt from that checkout**. An older plugin may still
  have `--template-ref`, Host-based routing, or no `proxy actor`. Confirm:

  ```bash
  go install ./cmd/kubectl-ate
  kubectl ate --version
  kubectl ate create actor --help | grep -- --template
  kubectl ate create actor-template --help | grep filename
  kubectl ate proxy actor --help | head -3
  ```

  All must match. If `--template-ref` shows up instead of `--template`,
  another `kubectl-ate` is earlier on `PATH`.
- `KO_DOCKER_REPO` set (and `.ate-dev-env.sh` at the checkout root if you
  use one; `ate-setup` reads it unless `--no-dev-env`). Releases don't
  publish demo images, so `deploy demo counter` builds the counter image
  with `ko`. On kind, `export ATE_INSTALL_KIND=true`.
- Local tools: `kubectl`, `curl`, `jq`.

Confirm the control plane and the default sandbox config:

```bash
kubectl get pods -n ate-system
kubectl get sandboxconfig gvisor-default
kubectl get crd workerpools.ate.dev sandboxconfigs.ate.dev
```

`actortemplates.ate.dev` must **not** appear in that CRD list.

---

## Step 1 — Deploy capacity and the replacement template

From the **v1.0.0** Substrate checkout root:

```bash
go run ./cmd/ate-setup deploy demo counter
```

This command does **not** `kubectl apply` an ActorTemplate. It:

1. Builds the counter image with `ko`.
2. `kubectl apply`s `demos/counter/counter.yaml.tmpl`: the
   `ate-demo-counter` namespace and the `counter` `WorkerPool` (still a CRD),
   and waits for the worker rollout.
3. Creates the `ate-demo-counter` atespace.
4. Creates the `counter` actor template through the Substrate API from
   `demos/counter/counter-template.yaml.tmpl`.
5. Waits until the template's golden snapshot is ready.

Check the pool:

```bash
kubectl -n ate-demo-counter rollout status deployment/counter --timeout=5m
kubectl get workerpool counter -n ate-demo-counter
```

Check the golden snapshot (the replacement for
`kubectl wait --for=condition=Ready actortemplate/...`):

```bash
# GOLDEN TAG column fills in when the template is usable.
kubectl ate get actor-template counter -a ate-demo-counter
```

If you created the template yourself, poll until it is set:

```bash
until kubectl ate get actor-template counter -a ate-demo-counter -o json \
  | jq -e '.status.goldenSnapshotStatus.goldenTag.name' >/dev/null; do
  kubectl ate get actor-template counter -a ate-demo-counter
  sleep 5
done
```

If `ERROR` is set, `-o yaml` has the message
(`status.goldenSnapshotStatus.errorMessage`). Typical causes: snapshot
bucket IAM, missing `gvisor-default` `SandboxConfig`, WorkerPool not Ready.

### What the new template manifest looks like

The Actor Template is no longer a k8s object/manifest. It is protojson
for `substrate.ateapi.v1.ActorTemplate`. Enums are the proto names. There is
no `sandboxConfig` field; the sandbox class comes from the pools the
`workerSelector` matches. The atespace must already exist.

```yaml
metadata:
  atespace: ate-demo-counter
  name: counter
workerSelector:
  matchLabels:
    workload: counter
containers:
- name: counter
  image: <digest-pinned image>
  command:
  - /ko-app/counter
  wakeupProbe:
    httpGet:
      path: /readyz
      port: 80
  volumeMounts:
  - name: data
    mountPath: /home/counter
resources:
  limits:
    cpuMillicores: 1000
    memoryBytes: 536870912 # 512Mi
snapshotConfig:
  preferredFidelity: SNAPSHOT_FIDELITY_MEMORY
volumes:
- name: data
  durableDir: {}
```

Snapshots go under ate-api-server's `--snapshot-location` by default.
A per-template `snapshotConfig.storageLocation` exists but requires the
`PerTemplateSnapshotLocation` preview gate.

You would then save the above in a file called something like `counter-template.yaml`.

If you went with the `counter-template.yaml` naming convention, you would create the actor template like in the example below:

```bash
kubectl ate create atespace ate-demo-counter
kubectl ate create actor-template -f counter-template.yaml
```

And then create the Actor like so:

```bash
kubectl ate create actor my-counter-1 \
  -a ate-demo-counter \
  --template counter
```

Keep in mind that the `--template` is the name of the template that you gave within the YAML, not the name of the file (e.g., - `counter-template.yaml`)

---

## Step 2 — Create the actor

The actor name is a DNS-1123 label. `--template` is the template **name**,
resolved in `--atespace`. (`--template <atespace>/<name>` also parses, but
the old `<namespace>/<name>` meaning is gone: the prefix is an atespace.)

```bash
kubectl ate create actor my-counter-1 \
  --atespace ate-demo-counter \
  --template counter
```

```bash
kubectl ate get actor my-counter-1 -a ate-demo-counter
```

Expected: `ACTOR_STATE_SUSPENDED`, `WORKER POD` `<none>`. No worker consumed.
The record is in Postgres, not etcd.

`kubectl get actor my-counter-1` will not work. Actors were never a CRD.

---

## Step 3 — Wake it through the router

The router no longer routes on a Host name. It takes TLS with a client
certificate from an allowlisted SPIFFE ID and routes on the
`ate-target-actor: <atespace>/<actor>` header, so the atespace is still part
of the address. `kubectl ate proxy actor` presents the `atenet-client`
certificate and sets that header for you:

```bash
kubectl ate proxy actor my-counter-1 -a ate-demo-counter
```

It forwards `127.0.0.1:8000` to the actor's port 80. In a second terminal:

```bash
curl -X POST http://localhost:8000
```

First request is the resume: router ext_proc → `ResumeActor` → restore from
the golden snapshot onto a free worker → forward. Repeat a few times. The
in-memory, durable-file, and rootfs counts all increment (this template's
`preferredFidelity` is `SNAPSHOT_FIDELITY_MEMORY`).

```bash
kubectl ate get actor my-counter-1 -a ate-demo-counter
kubectl ate get workers
```

`STATE` is `ACTOR_STATE_RUNNING`. `WORKER POD` names the worker.

---

## Step 4 — Suspend and resume on the new path

```bash
kubectl ate suspend actor my-counter-1 -a ate-demo-counter
kubectl ate get actor my-counter-1 -a ate-demo-counter
```

`SUSPENDED`, no worker. The snapshot upload finishes in the background;
add `--mode=sync` to wait for it. Send the same `curl` through the proxy
again. The count continues.

```bash
kubectl ate logs actor my-counter-1 -a ate-demo-counter
```

---

## Cleanup

`DeleteActor` removes an actor in any state, so there is no separate
suspend step (and no `--any-state` flag):

```bash
kubectl ate delete actor my-counter-1 -a ate-demo-counter
```

Remove the demo pool, template, golden snapshot, and atespace:

```bash
go run ./cmd/ate-setup delete demo counter
```

Leave `ate-system` alone.

---

## Command cheat sheet

| Intent | Dead (pre-2026-09-02) | v1.0.0 |
|---|---|---|
| Install template | `kubectl apply -f actortemplate.yaml` | `kubectl ate create actor-template -f template.yaml` |
| List templates | `kubectl get actortemplate -n <ns>` | `kubectl ate get actor-templates -a <atespace>` |
| Wait for golden | `kubectl wait --for=condition=Ready actortemplate/<name> -n <ns>` | Poll `kubectl ate get actor-template <name> -a <atespace>` until `GOLDEN TAG` is set |
| Create actor | `kubectl ate create actor <id> --template <ns>/<name>` | `kubectl ate create actor <id> -a <atespace> --template <name>` |
| Get actor | `kubectl ate get actor <id>` (implicit default) | `kubectl ate get actor <id> -a <atespace>` (no default atespace) |
| Reach actor | Host `<id>.actors.resources.substrate.ate.dev` | `kubectl ate proxy actor <id> -a <atespace>` (router header `ate-target-actor: <atespace>/<id>`) |
| Delete template | `kubectl delete actortemplate <name> -n <ns>` | `kubectl ate delete actor-template <name> -a <atespace>` |

---

## Troubleshooting

- **`unknown flag: --template` / no `create actor-template` / no `proxy actor`**
  — `kubectl-ate` is older than v1.0.0. `go install ./cmd/kubectl-ate` from
  the v1.0.0 checkout and make sure that binary is first on `PATH`.
- **`the server doesn't have a resource type "actortemplate"`** — expected
  for `kubectl get` / `kubectl apply`. Use `kubectl ate`.
- **`FailedPrecondition` on create actor / create template** — the atespace
  does not exist. `kubectl ate create atespace <name>` first.
- **`no free workers available`** — WorkerPool is a CRD; check
  `kubectl get workerpool -n ate-demo-counter` and `kubectl ate get workers`.
- **Proxy connects but requests are rejected / actor never resumes** — the
  install's `--ingress-allowed-spiffe-ids` does not list
  `spiffe://cluster.local/ns/ate-system/sa/atenet-client`, or the actor was
  created in a different atespace than the `-a` you passed to `proxy actor`.
- **Template create rejects the YAML** — protojson is strict. No
  `apiVersion`/`kind`, no `sandboxConfig`. Enums are proto names such as
  `SNAPSHOT_FIDELITY_MEMORY`. Resources are `cpuMillicores` / `memoryBytes`.
- **Golden never appears** — atelet snapshot IAM, bucket, or sandbox
  assets. `kubectl ate get actor-template counter -a ate-demo-counter -o yaml`
  and the golden actor under `kubectl ate get actors -A`.

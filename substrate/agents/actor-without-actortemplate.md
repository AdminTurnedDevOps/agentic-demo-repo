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
manifest against a cluster installed from current `main`, Kubernetes rejects
it: that CRD is not installed.

### What replaces it

**The same object, a different store and a different CLI.**

| Before 2026-09-02 | After 2026-09-02 |
|---|---|
| `kind: ActorTemplate` Kubernetes CRD in a **namespace** | `ateapipb.ActorTemplate` ate-API resource in an **atespace** |
| Stored in etcd | Stored in the control-plane **PostgreSQL** database |
| `kubectl apply -f template.yaml` | `kubectl ate create actor-template -f template.yaml` |
| `kubectl get actortemplate -n <ns>` | `kubectl ate get actor-templates -a <atespace>` |
| `kubectl wait --for=condition=Ready actortemplate/...` | Poll `kubectl ate get actor-template` until `GOLDEN SNAPSHOT` is set |
| `--template <namespace>/<name>` | `--template-ref <name>` plus `--atespace` / `-a` |
| Host `<actor>.actors.resources.substrate.ate.dev` | Host `<actor>.<atespace>.actors.resources.substrate.ate.dev` |

The replacement is still called **ActorTemplate**. Creating one still triggers
the golden snapshot. Actors still derive from it. What changed is *where it
lives* and *which binary you talk to*.

`ate-api-server` owns templates through `ateapi.Control`:
`CreateActorTemplate`, `GetActorTemplate`, `ListActorTemplates`,
`DeleteActorTemplate`. `kubectl-ate` is the client. The manifest is
**protojson** (the same shape `kubectl ate get actor-template -o yaml`
prints), not a Kubernetes object. Unknown fields are an error.

Templates are **immutable**. There is no update. New version = new template
name (or delete and recreate).

`sandboxConfig` is **required** on every template: `sandboxClass`
(`SANDBOX_CLASS_GVISOR` or `SANDBOX_CLASS_MICROVM`) plus `configName` (the
cluster-scoped `SandboxConfig` CR, usually `gvisor-default`).

### What is still a Kubernetes CRD

Do not throw out `kubectl apply` for the whole platform. These three are still CRDs:

| Resource | API | Tool |
|---|---|---|
| `WorkerPool` | `ate.dev/v1alpha1` CRD | `kubectl apply` / `kubectl get workerpool` |
| `SandboxConfig` | cluster-scoped `ate.dev/v1alpha1` CRD | `kubectl get sandboxconfig` |
| `CSIDriverConfig` | cluster-scoped `ate.dev/v1alpha1` CRD | `kubectl get csidriverconfig` |

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
| The replacement exists | `kubectl ate get actor-templates -a ate-demo-counter` shows `counter` with a golden snapshot |
| Deploy an actor on the new path | `kubectl ate create actor … --template-ref counter -a ate-demo-counter` |
| DNS includes the atespace | Traffic uses `Host: <actor>.<atespace>.actors.resources.substrate.ate.dev` |
| State still survives suspend | Counter continues after suspend → resume |

---

## What Substrate pieces this uses

| Concept | Where it lives |
|---|---|
| `WorkerPool` `counter` | Kubernetes CRD in namespace `ate-demo-counter`. Warm pods. Still `kubectl apply`. |
| `Atespace` `ate-demo-counter` | Ate API. Must exist before the template. Same name as the pool namespace by convention, not by requirement. |
| `ActorTemplate` `counter` | Ate API in that atespace. Protojson manifest. Golden snapshot in GCS. |
| `Actor` `my-counter-1` | Ate API record. Starts `SUSPENDED`. Hydrates from the golden snapshot on first resume. |
| DNS mesh | `my-counter-1.ate-demo-counter.actors.resources.substrate.ate.dev` through `atenet-router`. |

---

## Prerequisites

- A GKE Standard cluster with the Substrate **control plane** installed.
  The [setup lab](../setup.md) through
  `./hack/install-ate.sh --deploy-ate-system` is enough for the system
  pods. Do **not** use that lab's `--deploy-demo-counter` / `kubectl wait
  actortemplate` steps here — those are the CRD-era commands this lab
  replaces.
- A Substrate git checkout at **2026-09-02 or later** (`main` after
  `120a5196` / PR #1376). The overlay's nested clone at
  `substrate/substrate` is **too old** (it still has
  `actortemplate_types.go`). Work from a current clone, for example
  `/Users/michael/gitrepos/substrate`.
- `kubectl-ate` **rebuilt from that checkout**. An older plugin still has
  `--template <namespace>/<name>` and no `create actor-template`. Confirm:

  ```bash
  go install ./cmd/kubectl-ate
  kubectl ate create actor --help | grep template-ref
  kubectl ate create actor-template --help | grep filename
  ```

  Both must match. If `template-ref` is missing, another `kubectl-ate` is
  earlier on `PATH`.
- Env file sourced (`BUCKET_NAME`, `KO_DOCKER_REPO`) from the current
  checkout.
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

From the **current** Substrate repo root, with the env file sourced:

```bash
source .ate-dev-env.sh
./hack/install-ate.sh --deploy-demo-counter
```

On current `main` this script does **not** `kubectl apply` an ActorTemplate.
It:

1. `kubectl apply`s the `ate-demo-counter` namespace and the `counter`
   `WorkerPool` (still a CRD).
2. `kubectl ate create atespace ate-demo-counter`.
3. `ko resolve`s `demos/counter/counter-template.yaml.tmpl` and pipes it to
   `kubectl ate create actor-template -f -`.
4. Polls `kubectl ate get actor-template counter -a ate-demo-counter` until
   `status.goldenSnapshotStatus.goldenSnapshot.snapshotUri` is set.

Wait for the pool:

```bash
kubectl -n ate-demo-counter rollout status deployment/counter --timeout=5m
kubectl get workerpool counter -n ate-demo-counter
```

Wait for the golden snapshot (the replacement for
`kubectl wait --for=condition=Ready actortemplate/...`):

```bash
# GOLDEN SNAPSHOT column fills in when the template is usable.
kubectl ate get actor-template counter -a ate-demo-counter
```

Poll until it is set:

```bash
until kubectl ate get actor-template counter -a ate-demo-counter -o json \
  | jq -e '.actorTemplates[0].status.goldenSnapshotStatus.goldenSnapshot.snapshotUri
           | type == "string" and length > 0' >/dev/null; do
  kubectl ate get actor-template counter -a ate-demo-counter
  sleep 5
done
```

If `ERROR` is set, `-o yaml` has the message. Typical causes: snapshot
bucket IAM, missing `gvisor-default` `SandboxConfig`, WorkerPool not Ready.

### What the new template manifest looks like

The Actor Template is no longer a k8s object/manifest. It is protojson
for `ateapipb.ActorTemplate`. Enums are the proto names. `sandboxConfig` is
required. The atespace must already exist.

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
  readyz:
    httpGet:
      path: /readyz
      port: 80
  volumeMounts:
  - name: data
    mountPath: /home/counter
resources:
  limits:
  - name: cpu
    quantity: "1"
  - name: memory
    quantity: 512Mi
snapshotsConfig:
  onPause: SNAPSHOT_CONTENT_SCOPE_FULL
  onCommit: SNAPSHOT_CONTENT_SCOPE_FULL
  storageLocation: gs://${BUCKET_NAME}/ate-demo-counter/
sandboxConfig:
  sandboxClass: SANDBOX_CLASS_GVISOR
  configName: gvisor-default
volumes:
- name: data
  durableDir: {}
```

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
  --template-ref counter
```

Keep in mind that the `--template-ref` is the name of the template that you gave within the YAML, not the name of the file (e.g., - `counter-template.yaml`)

---

## Step 2 — Create the actor

The actor ID is a DNS-1123 label. `--template-ref` is the template **name**,
resolved in `--atespace`. There is no `<namespace>/<name>` form.

```bash
kubectl ate create actor my-counter-1 \
  --atespace ate-demo-counter \
  --template-ref counter
```

```bash
kubectl ate get actor my-counter-1 -a ate-demo-counter
```

Expected: `ACTOR_STATE_SUSPENDED`, empty `ATEOM POD`. No worker consumed.
The record is in Postgres, not etcd.

`kubectl get actor my-counter-1` will not work. Actors were never a CRD.

---

## Step 3 — Wake it through the DNS mesh

The atespace is a required DNS label. A Host without it does not resume this
actor.

```bash
kubectl -n ate-system port-forward svc/atenet-router 8000:80
```

In a second terminal:

```bash
curl -X POST \
  -H "Host: my-counter-1.ate-demo-counter.actors.resources.substrate.ate.dev" \
  http://localhost:8000
```

First request is the resume: router ext_proc → `ResumeActor` → restore from
the golden snapshot onto a free worker → forward. Repeat a few times. The
in-memory count and the durable-file count both increment (this template's
`onCommit` is `SNAPSHOT_CONTENT_SCOPE_FULL`).

```bash
kubectl ate get actor my-counter-1 -a ate-demo-counter
kubectl ate get workers
```

`STATE` is `ACTOR_STATE_RUNNING`. `ATEOM POD` names the worker.

---

## Step 4 — Suspend and resume on the new path

```bash
kubectl ate suspend actor my-counter-1 -a ate-demo-counter
kubectl ate get actor my-counter-1 -a ate-demo-counter
```

`SUSPENDED`, no worker. Hit the same Host again. The count continues.

```bash
kubectl ate logs actors my-counter-1 -a ate-demo-counter
```

---

## Cleanup

```bash
kubectl ate suspend actor my-counter-1 -a ate-demo-counter 2>/dev/null || true
kubectl ate delete actor my-counter-1 -a ate-demo-counter
```

`--any-state` deletes a `RUNNING` actor without the suspend step:

```bash
kubectl ate delete actor my-counter-1 -a ate-demo-counter --any-state
```

Remove the demo pool, template, golden snapshot, and atespace:

```bash
./hack/install-ate.sh --delete-demo-counter
```

Leave `ate-system` and `ate-golden` alone.

---

## Command cheat sheet

| Intent | Dead (pre-2026-09-02) | Current |
|---|---|---|
| Install template | `kubectl apply -f actortemplate.yaml` | `kubectl ate create actor-template -f template.yaml` |
| List templates | `kubectl get actortemplate -n <ns>` | `kubectl ate get actor-templates -a <atespace>` |
| Wait for golden | `kubectl wait --for=condition=Ready actortemplate/<name> -n <ns>` | Poll `kubectl ate get actor-template <name> -a <atespace>` |
| Create actor | `kubectl ate create actor <id> --template <ns>/<name>` | `kubectl ate create actor <id> -a <atespace> --template-ref <name>` |
| Get actor | `kubectl ate get actor <id>` (implicit default) | `kubectl ate get actor <id> -a <atespace>` (no default atespace) |
| Host header | `<id>.actors.resources.substrate.ate.dev` | `<id>.<atespace>.actors.resources.substrate.ate.dev` |
| Delete template | `kubectl delete actortemplate <name> -n <ns>` | `kubectl ate delete actor-template <name> -a <atespace>` |

---

## Troubleshooting

- **`unknown flag: --template-ref` / no `create actor-template`** — `kubectl-ate`
  is older than the CRD deletion. `go install ./cmd/kubectl-ate` from a
  checkout at or after 2026-09-02 and make sure that binary is first on
  `PATH`.
- **`the server doesn't have a resource type "actortemplate"`** — expected
  for `kubectl get` / `kubectl apply`. Use `kubectl ate`.
- **`FailedPrecondition` on create actor / create template** — the atespace
  does not exist. `kubectl ate create atespace <name>` first.
- **`no free workers available`** — WorkerPool is a CRD; check
  `kubectl get workerpool -n ate-demo-counter` and `kubectl ate get workers`.
- **Host 404 / actor never resumes** — Host missing the atespace label, or
  `kubectl-ate` created the actor in a different atespace than the Host.
- **Template create rejects the YAML** — protojson is strict. No
  `apiVersion`/`kind`. Enums are `SANDBOX_CLASS_GVISOR`,
  `SNAPSHOT_CONTENT_SCOPE_FULL`. `sandboxConfig.configName` must name a
  real `SandboxConfig`.
- **Golden never appears** — atelet snapshot IAM, bucket, or sandbox
  assets. `kubectl ate get actor-template counter -a ate-demo-counter -o yaml`
  and the golden actor under `kubectl ate get actors -A`.

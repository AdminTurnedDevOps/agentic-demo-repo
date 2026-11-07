---
title: "Agent Substrate: Actor State Teleport and Atespace Multi-Tenancy"
date: 2026-07-09
description: >
  A hands-on lab proving two Agent Substrate isolation guarantees: Atespaces
  keep same-named actors in different tenants fully separate, and a suspended
  actor's state follows it onto a different worker pod when it resumes.
tags: [agent-substrate, kubernetes, actors, suspend-resume, checkpoint-restore, multi-tenancy, atespaces]
author: Michael Levan
---

# The Teleporting Actor

Tldr; Moving an actors "state" from one pod to another via a restore/checkpoint.

This lab demonstrates two things:

1. **Atespace multi-tenancy**: two tenants each run an actor with the *same
   name* (`agent-1`), and Substrate keeps their state, identity, access, and
   snapshots completely separate.
2. **State teleport**: an actor is suspended (checkpointed to object storage,
   worker released) and then resumed onto a **different worker pod**, and its
   state continues exactly where it left off. The pod is cattle; the actor's
   state is the stable thing.

## What Substrate pieces this uses

| Concept | Where it lives |
|---|---|
| `Atespace` | Tenancy/addressing boundary for actors, independent of Kubernetes namespaces. An actor is named `<atespace>/<name>`; the name is only unique within its atespace. |
| Access policies | One `default` access policy per atespace (plus one global) binds principals to `owner`, `editor`, or `viewer`. `ate-api-server` checks every API call against them, so a tenant's people can manage their atespace and nothing else. |
| Actor identity | Substrate-issued identities name the atespace: actor JWTs carry `sub: actor/<atespace>/<name>`, and the worker's certificate for an actor is `spiffe://<trust-domain>/worker-for-actor/<atespace>/<name>`. Same name in two atespaces, two different identities. |
| `ate-target-actor` routing | The `atenet-router` picks the actor from the `ate-target-actor: <atespace>/<name>` header, resuming it first if it is suspended. `kubectl ate proxy actor` sets it for you on an mTLS CONNECT tunnel. The atespace is **required** - a name alone is ambiguous. |
| Suspend / resume | Suspend checkpoints the actor's sandbox and uploads the snapshot under `<snapshot-location>/atespaces/<atespace>/...`; resume restores it into a free worker. The actor is never in two places, and between the two it exists only as a snapshot. |
| Counter demo workload | Reused as the actor. Its response prints an in-memory count, a durable-file count, and a root-filesystem count - the state-survival proof across suspend. Worker assignment is read from `kubectl ate get actors`. |
---

## Prerequisites

- A GKE cluster with the Substrate **v1.0.0** control plane installed and the
  **counter demo** deployed. Follow the main [setup lab](../install-and-setup/setup-gke.md), then
  run `go run ./cmd/ate-setup deploy demo counter` from the same v1.0.0
  checkout. The install needs
  `--ingress-allowed-spiffe-ids=spiffe://cluster.local/ns/ate-system/sa/atenet-client`,
  the client certificate `kubectl ate proxy` presents; without it the router
  lets no client reach actors.
- The `kubectl-ate` plugin installed (`go install ./cmd/kubectl-ate` from the
  same Substrate checkout) and reachable on your `PATH` (kubectl discovers
  plugins by scanning `PATH` for `kubectl-*` binaries).
- Local tools: `curl`, `kubectl`.

Confirm the control plane and template are healthy before starting:

```bash
kubectl get pods -n ate-system
kubectl ate get actor-templates -a ate-demo-counter
kubectl ate get workers -n ate-demo-counter
```

The `counter` ActorTemplate should have its `GOLDEN TAG` filled in, which means
its golden snapshot exists in your snapshot bucket. The counter pool has
**3** workers, all `FREE`; the teleport step below counts on that, so make
sure no other lab's actors are running on it.

---

## Step 1 - Two tenants, one agent name

An `atespace` is to Actors as `namespace` is to Pods.

Create two Atespaces and an actor named `agent-1` in **each**. The
`kubectl-ate` CLI auto-port-forwards to the `ate-api-server`, so these run
directly from your terminal. Both actors use the counter template, which lives
in the `ate-demo-counter` atespace, so it's referenced as
`<atespace>/<template>`:

```bash
kubectl ate create atespace tenant-a
kubectl ate create atespace tenant-b

kubectl ate create actor agent-1 --template=ate-demo-counter/counter --atespace=tenant-a
kubectl ate create actor agent-1 --template=ate-demo-counter/counter --atespace=tenant-b
```

You can now list the Actors running.

Note: there is no "default" atespace, so listing always takes `--atespace` or `-A` for all:

```bash
kubectl ate get actors -A
```

You'll see both `agent-1` entries with their atespace, template, state,
assigned worker (`WORKER POD`, as `<namespace>/<pod>`), and worker IP columns.

Now drive traffic through the router. There is no plaintext router port in
v1.0.0: `kubectl ate proxy actor` opens a local port, tunnels each connection
to the router over mTLS, and sets `ate-target-actor` to the actor's
**atespace and name**. One proxy per tenant:

```bash
kubectl ate proxy actor agent-1 8001:80 -a tenant-a &
kubectl ate proxy actor agent-1 8002:80 -a tenant-b &

# Hit tenant-a's agent-1 three times
for i in 1 2 3; do
  curl -s http://localhost:8001/
done

# Hit tenant-b's agent-1 once
curl -s http://localhost:8002/
```

The last two lines of output:

```
preserved memory count: 3 | preserved file counter: 3 | preserved rootfs counter: 3
preserved memory count: 1 | preserved file counter: 1 | preserved rootfs counter: 1
```

**That's the tenancy proof.** You gave the Actors the same name, same template, same WorkerPool, but tenant-a's count is 3 and tenant-b's is 1. Different `ate-target-actor` values, different actor identities (`actor/tenant-a/agent-1` vs `actor/tenant-b/agent-1`), different snapshot paths in the bucket. (First requests may take a moment; a newly created actor starts `ACTOR_STATE_SUSPENDED`, and the router resumes it from the golden snapshot before forwarding.)

> Worker identity comes from the `WORKER POD` column, not from anything the
> counter prints:

```bash
kubectl ate get actors --atespace=tenant-a
```

Record tenant-a's `WORKER POD` value (e.g.
`ate-demo-counter/counter-xxxxx-yyyyy`). You'll compare it after the
teleport.

### Who can manage which tenant: access policies

Separate state is half of tenancy. The other half is that tenant-a's people
can't touch tenant-b. In v1.0.0 that is an **access policy** per atespace,
checked by `ate-api-server` on every call.

So far you've been acting as the shared `ate-client` ServiceAccount, which
`ate-setup` makes a bootstrap owner (global `owner`). Create a ServiceAccount
for a tenant-a user, make it an `editor` of tenant-a, and act as it:

```bash
kubectl create namespace ate-users
kubectl -n ate-users create serviceaccount tenant-a-dev

cat > tenant-a-policy.yaml <<'EOF'
bindings:
- role: editor
  members:
  - user:system:serviceaccount:ate-users:tenant-a-dev
EOF
kubectl ate create access-policy -a tenant-a -f tenant-a-policy.yaml

kubectl create token -n ate-users tenant-a-dev --audience api.ate-system.svc > tenant-a-dev.token
```

```bash
kubectl ate --token-file tenant-a-dev.token get actors -a tenant-a   # allowed
kubectl ate --token-file tenant-a-dev.token get actors -a tenant-b   # PermissionDenied
kubectl ate --token-file tenant-a-dev.token suspend actor agent-1 -a tenant-b   # PermissionDenied
```

The denied calls name the principal in the error. An editor can create,
suspend, resume, and delete actors in its atespace, but not change the access
policy (that's `owner`) or see workers (that's a global role).

> **Where the boundary ends.** Access policies govern the **API**. The router
> is one shared ingress: any client on `--ingress-allowed-spiffe-ids` can reach
> any actor in any atespace (that's how your `kubectl ate proxy` reached both).
> Substrate v1.0.0 doesn't yet enforce per-atespace network policy or quotas,
> and the atespace is the only grant scope (no per-actor grants). If tenants
> must not reach each other's actors, put your own authorizing gateway in front
> of the router (see the [OpenFGA lab](../policy-and-permission/openfga/openfga.md)).

---

## Step 2 - The teleport: suspend, move workers, state intact

Current state of tenant-a's agent:

```bash
kubectl ate get actors --atespace=tenant-a
curl -s http://localhost:8001/
# preserved memory count: 4 | preserved file counter: 4 | preserved rootfs counter: 4
```

Note the `WORKER POD` column value. Right now both `agent-1`s are running, so
two of the counter pool's three workers are taken.

**Occupy its old worker.** v1.0.0 resumes an actor on the node that holds its
local snapshot when it can, so left alone `agent-1` may well land back where it
was. Make that impossible: park one filler on the free worker now.

```bash
kubectl ate create actor filler-1 --template=ate-demo-counter/counter --atespace=tenant-b
kubectl ate resume actor filler-1 --atespace=tenant-b
```

Suspend the actor. `--mode=sync` returns only once the snapshot is in object
storage (the default, async, returns as soon as it's captured on the node and
uploads in the background):

```bash
kubectl ate suspend actor agent-1 --atespace=tenant-a --mode=sync
```

```bash
kubectl ate get actors --atespace=tenant-a

# STATE: ACTOR_STATE_SUSPENDED, WORKER POD: <none>
```

Its old worker is now the only free one. Take it with a second filler, then
free a *different* worker by suspending tenant-b's `agent-1`:

```bash
kubectl ate create actor filler-2 --template=ate-demo-counter/counter --atespace=tenant-b
kubectl ate resume actor filler-2 --atespace=tenant-b
kubectl ate suspend actor agent-1 --atespace=tenant-b
kubectl ate get workers -n ate-demo-counter
```

Exactly one worker is `FREE`, and it isn't the one you recorded.

> If the wake-up curl below returns `no worker has room for the actor`, the
> pool is genuinely full - every worker is assigned to a running actor
> (`kubectl ate get workers` shows who's holding each slot). That's an honest
> capacity signal from an oversubscribed system, and the fix is to free a
> slot: suspend a filler (`kubectl ate suspend actor filler-1
> --atespace=tenant-b`) and retry. v1.0.0 does not suspend idle actors for you;
> whatever drives the actor has to.

Wake `agent-1` by sending traffic to it. The router sees the suspended actor and resumes it before forwarding the request:

```bash
curl -s http://localhost:8001/
```

```bash
# preserved memory count: 5 | preserved file counter: 5 | preserved rootfs counter: 5
kubectl ate get actors --atespace=tenant-a
```

Read the response and the `WORKER POD` column together:

- **`WORKER POD` shows a different worker pod** than the one you recorded
  before the suspend → the actor physically moved.
- **`preserved file counter: 5`** → the actor's durable volume survived the
  move (it was 4 before suspend; this request made it 5). Not re-initialized.
  Restored from the snapshot onto a different pod.
- **`preserved memory count: 5`** → the in-RAM count survived too. The
  process resumed where it left off, which is this **template's** snapshot
  fidelity, and it's worth explaining on stage:

> **Snapshot fidelity (`preferredFidelity`).** v1.0.0 replaced the old
> `onPause`/`onCommit` tiering with one per-template ceiling,
> `snapshotConfig.preferredFidelity`: `SNAPSHOT_FIDELITY_VOLUMES` keeps only
> durable volumes (the file counter survives; memory and rootfs counters
> restart), `SNAPSHOT_FIDELITY_ROOTFS` adds root-filesystem writes, and
> `SNAPSHOT_FIDELITY_MEMORY` (the default, and what the stock counter template
> sets) adds process memory, so all three counters continue. It's a ceiling,
> not a guarantee: Substrate may package less, for example under memory
> pressure. Either way the file counter is the state-survival proof, and the
> fidelity is a good talking point: you choose per template how much state is
> worth persisting.

---

## Cleanup

```bash
# Actors, then atespaces. DeleteActor removes an actor in any state, and an
# atespace can only be deleted once it's empty. Deleting it also deletes its
# access policy.
kubectl ate delete actor filler-1 --atespace=tenant-b
kubectl ate delete actor filler-2 --atespace=tenant-b
kubectl ate delete actor agent-1 --atespace=tenant-a
kubectl ate delete actor agent-1 --atespace=tenant-b
kubectl ate delete atespace tenant-a
kubectl ate delete atespace tenant-b

# The tenant user
kubectl delete namespace ate-users
rm -f tenant-a-policy.yaml tenant-a-dev.token

# Stop the actor proxies
kill %1 %2 2>/dev/null
```

> Pick new atespace names if you run the lab again. Grants are keyed by
> atespace name, so v1.0.0 asks you not to recreate a deleted atespace under
> the same name.

The Substrate control plane, counter demo, and cluster are untouched - tear
those down via the main [setup lab](../install-and-setup/setup-gke.md) if you're done with them.

---

## Recap

| Beat | What was proven |
|---|---|
| Same actor name, two Atespaces | Tenants can't collide: separate state, identities, routing targets, and snapshots - with zero coordination between them. |
| Access policy per Atespace | tenant-a's editor can manage tenant-a and is denied on tenant-b. The router itself is shared, so data-plane isolation between tenants is yours to add. |
| Suspend → resume across workers | State followed the actor onto a different worker pod: durable volume, rootfs, and (with `MEMORY` fidelity) process memory. Snapshot fidelity is a per-template cost/fidelity dial. |

The talk line: **"The pod died. The actor didn't. State follows the actor,
not the worker."**

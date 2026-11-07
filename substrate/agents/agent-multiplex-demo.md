---
title: "Agent Substrate: Multiplexing Claude Code Agents Onto Fewer Pods"
description: >
  A hands-on lab running real Claude Code agents as Substrate actors: three
  agents share a two-pod WorkerPool, an explicit suspend frees capacity for
  the third, proving that actor count can exceed worker count.
tags: [agent-substrate, kubernetes, actors, claude-code, suspend-resume, multiplexing, oversubscription]
author: Michael Levan
---

# More Agents Than Pods

Tldr; Three Claude Code actors, two worker pods. An operator explicitly
suspends an idle actor to free a slot for another. The cluster is
oversubscribed on purpose, and capacity remains an honest, visible constraint.

This demo runs **real AI agent workload**: each actor is a container running the actual
`@anthropic-ai/claude-code` CLI in a loop. Wake, send a task to Claude,
print the answer, and idle. An operator or higher-level system can use those idle
windows to suspend actors and multiplex a smaller worker pool across them.
Substrate provides the lifecycle and scheduling primitives; this demo drives
the policy explicitly with `kubectl ate`.

This exercises the same density primitive as the upstream demo, at walkthrough
scale:

1. **Density**: 3 Claude Code actors on a 2-replica `WorkerPool`. The third
   actor cannot run until a slot frees - and you'll see the honest capacity
   signal when it can't.
2. **Real workload**: each running actor makes genuine Claude API calls and
   streams the results through actor logs.

## What Substrate pieces this uses

| Concept | Where it lives |
|---|---|
| Claude Code workload | `demos/claude-code-multiplex/workload/` - a `node:20-slim` image with the Claude Code CLI and a `run.sh` loop: run `claude --print "$TASK"`, sleep `INTERVAL_SECONDS`, repeat. |
| `WorkerPool` (2 replicas) | `claude-workerpool` (`ate.dev/v1`, `sandboxClasses: [gvisor]`) in namespace `claude-multiplex-demo`, labeled `workload: claude-multiplex`. Each worker's `template.resources.limits` (1 CPU) is its capacity, so each holds one 1-CPU agent. The templates bind to it via `workerSelector.matchLabels`. |
| `ActorTemplate` x3 | `agent-luna`, `agent-mars`, `agent-orion` - Substrate API records (not CRDs) in the `claude-multiplex-demo` **atespace**. Same image, different `TASK` prompt. `ANTHROPIC_API_KEY` is substituted into each template as a literal `env` value at deploy time; there is no Secret. |
| Actors x3 + egress | `luna`, `mars`, `orion`, created by the deploy step in the same atespace, each with an egress policy that passes TLS through to `api.anthropic.com:443`. Egress is default-deny, so an actor without a policy can't reach Claude. |
| Explicit resume | These agents serve no HTTP, so there's no traffic to wake them through the `atenet-router`. Resume is `kubectl ate resume actor` (the same `substrate.ateapi.v1.Control/ResumeActor` RPC the router would call). |
| Full-state snapshots | The templates set `snapshotConfig.preferredFidelity: SNAPSHOT_FIDELITY_MEMORY`, so a suspend captures the full sandbox (RAM included). |

---

## Prerequisites

- A cluster with the Substrate **v1.0.0** control plane installed. Follow the
  main [setup lab](../install-and-setup/setup-gke.md) through
  `go run ./cmd/ate-setup deploy ate-system ...`, with a snapshot location
  (`SNAPSHOT_LOCATION` / `--snapshot-location`) set; the agents' snapshots
  are stored there. (The counter demo is *not* required for this lab.)
- A checkout of the v1.0.0 tag
  (`git clone --branch v1.0.0 https://github.com/agent-substrate/substrate.git`).
- The `kubectl-ate` plugin installed from that checkout
  (`go install ./cmd/kubectl-ate`) and on your `PATH`. It auto-port-forwards to the
  `ate-api-server`, so no manual port-forward is needed for the CLI steps.
- An **Anthropic API key**. The agents make real Claude API calls.
- `KO_DOCKER_REPO` set to a registry your cluster can pull from. Releases
  don't publish demo images, so the deploy step builds and pushes the
  workload image there.
- Local tools beyond the setup lab's list:

| Tool | Why |
|---|---|
| `docker` with `buildx` | The workload is a Dockerfile image (Node + Claude Code CLI), not a Go binary - `ko` doesn't apply, so the deploy step builds and pushes it with `docker buildx`. The Docker daemon must be running. |

Verify Docker before deploying:

```bash
docker info
docker buildx version
```

> **This lab costs real money in two ways**: each RUNNING agent calls the
> Anthropic API every few seconds (`INTERVAL_SECONDS` is `5` in the v1.0.0
> templates), and the workload image build pushes to your registry. Suspend
> the actors when you're not actively demoing, and don't leave the demo
> running overnight.

> **Use a dedicated, short-lived Anthropic key.** In v1.0.0 the key is written
> into each ActorTemplate as a literal `env` value, so it is stored in the
> template record in the control-plane PostgreSQL database. This demo also
> intentionally takes full-memory snapshots, so the key is present in golden
> and actor snapshots in object storage. Revoke the key when you're done.

> **Build reproducibility:** the upstream workload Dockerfile currently
> installs `@anthropic-ai/claude-code@latest`. The resulting image is pinned by
> digest for one deployment, but a later rebuild may contain a different Claude
> Code version. Pin a tested package version in the Dockerfile for repeatable
> runs.

Run everything from the root of your v1.0.0 Substrate checkout, with
`KO_DOCKER_REPO` exported (or in your `.ate-dev-env.sh`, which `ate-setup`
reads from the checkout root).

Confirm the control plane is healthy before starting:

```bash
kubectl get pods -n ate-system
```

---

## Step 1 - Deploy the demo (pool, templates, agents)

Export your Anthropic key:

```bash
export ANTHROPIC_API_KEY=
```

ActorTemplates in v1.0.0 have no `secretKeyRef`: env values are literals. So
there is no Secret to create and no RBAC to grant `ate-api-server`. Deploy:

```bash
go run ./cmd/ate-setup deploy demo claude-code-multiplex
```

This builds the workload image with `docker buildx`, pushes it to
`${KO_DOCKER_REPO}/claude-multiplex-demo-workload`, resolves the digest, and
then:

- applies the `claude-multiplex-demo` namespace and the 2-replica
  `WorkerPool` `claude-workerpool`,
- creates the `claude-multiplex-demo` atespace,
- creates three actor templates in it: `agent-luna`, `agent-mars`,
  `agent-orion` (digest-pinned image and `ANTHROPIC_API_KEY` substituted in),
- waits for each template's golden snapshot,
- creates the three actors `luna`, `mars`, `orion` (suspended), each with an
  egress policy allowing `api.anthropic.com:443`.

Ensure the resources were created. The pool is a CRD; the templates are not:

```bash
kubectl get workerpool -n claude-multiplex-demo
kubectl ate get actor-templates -a claude-multiplex-demo
```

All three templates show a `GOLDEN TAG` and no `ERROR` (the deploy already
waited for them, so there is no `kubectl wait` step).

You see two Pods because the goal is to see multiple Agents across only two
Workers (Pods).

---

## Step 2 - Meet the three agents

Actors live in an atespace (the tenancy boundary; see the
[multi-tenancy lab](../isolation/session-identity-multi-tenancy.md)). An
actor's `--template` resolves in its own atespace, so the agents live in
`claude-multiplex-demo` next to their templates. The deploy step already
created them; for reference, the equivalent commands are:

```bash
# Already done by deploy demo; shown for reference.
kubectl ate create actor luna  --template agent-luna  --atespace claude-multiplex-demo
kubectl ate create actor mars  --template agent-mars  --atespace claude-multiplex-demo
kubectl ate create actor orion --template agent-orion --atespace claude-multiplex-demo
```

```bash
kubectl ate get actors --atespace claude-multiplex-demo
kubectl ate get egress-policy luna --atespace claude-multiplex-demo -o yaml
```

All three show `ACTOR_STATE_SUSPENDED` with `WORKER POD` `<none>`. **Three
agents exist and hold zero worker assignments.** The two WorkerPool pods
remain running and ready; suspended actors consume none of those slots. The
same pool could hold records and snapshots for many more suspended actors.

---

## Step 3 - Wake two agents and watch real Claude output

Resume two of the three (the pool has exactly two slots):

```bash
kubectl ate resume actor luna --atespace claude-multiplex-demo
kubectl ate resume actor mars --atespace claude-multiplex-demo

kubectl ate get actors --atespace claude-multiplex-demo
```

`luna` and `mars` go `ACTOR_STATE_RESUMING` → `ACTOR_STATE_RUNNING`, each
bound to a different worker in the `WORKER POD` column. Stream **Mars's** logs
because Mars is the actor Step 4 will suspend:

```bash
kubectl ate logs actor mars --atespace claude-multiplex-demo -f
```

`kubectl ate logs` preserves the structured log envelope, so each workload line
appears as JSON with `time` and `message` fields. You'll see the loop ticking:

```
{"time":"2026-07-16T14:22:07Z","message":"[demo-actor:mars] === tick 3 at 14:22:07Z ==="}
{"time":"2026-07-16T14:22:07Z","message":"[demo-actor:mars] running: Give me one concise tip for learning a new programming language. One sentence."}
{"time":"2026-07-16T14:22:09Z","message":"Build one small project immediately and learn concepts as you need them."}
{"time":"2026-07-16T14:22:09Z","message":"[demo-actor:mars] tick 3 done; sleeping 5s"}
```

> **TODO (v1.0.0):** re-capture this sample against a v1.0.0 cluster; the
> JSON envelope shape of `kubectl ate logs` was not re-verified. Add
> `--source containers` to drop lifecycle events from the stream.

That's a genuine one-shot Claude API round-trip from inside a gVisor-sandboxed
actor. Press `Ctrl-C` after you see a completed tick.

> Don't expect the ticks to start at 1. The golden snapshot was captured
> after the workload had already started (that's the point - actors hydrate
> from a warm checkpoint, not a cold boot), so the loop resumes wherever the
> snapshot left it.

---

## Step 4 - The density squeeze: three agents, two slots

Try to wake the third agent while both workers are held:

```bash
kubectl ate resume actor orion --atespace claude-multiplex-demo
```

If both slots are still occupied, this fails with `ResourceExhausted`:
`no worker has room for the actor`. **That error is the demo, not a bug** -
it's an oversubscribed system telling you the truth about capacity. Confirm
who's holding the slots:

```bash
kubectl ate get workers -a claude-multiplex-demo
```

Both workers show `1/…` in `ACTORS`. Apply the multiplexing policy explicitly:
suspend Mars to free a slot, then retry Orion:

```bash
kubectl ate suspend actor mars --atespace claude-multiplex-demo
kubectl ate resume actor orion --atespace claude-multiplex-demo

kubectl ate get actors --atespace claude-multiplex-demo
```

`orion` is `ACTOR_STATE_RUNNING`, `mars` is `ACTOR_STATE_SUSPENDED`
(checkpointed, slot released; the upload to object storage finishes in the
background unless you pass `--mode=sync`). Wait for Orion to complete at
least one Claude call before moving on:

```bash
kubectl ate logs actor orion --atespace claude-multiplex-demo -f
```

After you see `tick ... done`, press `Ctrl-C`. All three agents have now done
real work; at no point did a third worker pod exist.

> Substrate does not infer idleness from the workload's `sleep`. Production
> rotation requires the actor, an operator, or a higher-level policy system to
> call `SuspendActor`. This walkthrough uses explicit CLI calls so the policy
> boundary is visible.

---

## Step 5 - Optional: the dashboard

The demo ships a small Go dashboard that renders workers, actors, and pod
logs from the `substrate.ateapi.v1.Control` gRPC service. With `ATEAPI_ADDR`
unset it port-forwards to `svc/api` in `ate-system` by itself, so one
terminal is enough:

```bash
# From the Substrate repo root
cd demos/claude-code-multiplex/ui
PORT=8090 go run .
```

Open `http://localhost:8090`. The pods and agents panels are live cluster
state (via `ListWorkers` / `ListActors`, scoped to the
`claude-multiplex-demo` atespace); the logs pane reads real pod logs via
`client-go`.

> **Honesty note for the stage:** in v1.0.0 the dashboard is a lifecycle
> driver. "Give a task" picks an idle agent, **resumes** it, and **suspends**
> it when the task's fixed time is up. The task and its timing live only in
> the dashboard (see `ui/server.go`'s `computeState`); the agent itself just
> keeps running its `claude --print` loop. Don't run the dashboard while you
> are walking Steps 3-4 by hand, or it will suspend and resume agents under
> you.
>
> Unassigned workers from other pools may still appear. Cross-check
> `kubectl ate get actors --atespace claude-multiplex-demo` and
> `kubectl ate get workers -n claude-multiplex-demo` before making density
> claims.

---

## Cleanup

Remove the demo's actors, templates, atespace, and the
`claude-multiplex-demo` namespace (WorkerPool included):

```bash
go run ./cmd/ate-setup delete demo claude-code-multiplex
```

In v1.0.0, deleting an actor deletes the external snapshot it owns, and
deleting a template deletes its golden actor and golden snapshot. Confirm
nothing for the atespace is left under your snapshot location, since those
snapshots captured the Anthropic key:

```bash
gcloud storage ls --recursive \
  "${SNAPSHOT_LOCATION%/}/atespaces/claude-multiplex-demo/"
```

Delete anything left there only after checking the path. The Substrate
control plane and cluster are untouched - tear those down via the main
[setup lab](../install-and-setup/setup-gke.md) if you're done with them. The workload image
remains in your registry; delete it there if you want it gone. Unset the key
from your shell and revoke the dedicated key in Anthropic when finished:
`unset ANTHROPIC_API_KEY`.

---

## Troubleshooting

- **`no worker has room for the actor` (`ResourceExhausted`) on resume** -
  expected whenever both slots are held (Step 4). `kubectl ate get workers`
  shows who's holding them; suspend one and retry.
- **Deploy fails with `ANTHROPIC_API_KEY must be set` /
  `KO_DOCKER_REPO must be set`** - `deploy demo claude-code-multiplex`
  hard-requires both in the environment (or `.ate-dev-env.sh`).
- **Deploy fails before creating anything, pointing at `ate-controller`** -
  deploy the control plane first (`go run ./cmd/ate-setup deploy ate-system ...`).
- **`Docker is not reachable` / `docker.sock: connect: no such file or
  directory`** - the Docker client is installed but its daemon is not running.
  Start Docker Desktop (or your alternative daemon), wait until it is ready,
  and confirm `docker info` succeeds before rerunning the deploy.
- **`docker buildx` push fails** - your Docker credential helper isn't
  configured for the registry. Re-run
  `gcloud auth configure-docker gcr.io` (or your Artifact Registry host).
- **Agent logs show `claude exited non-zero` on every tick** - check the
  actor's egress policy (`kubectl ate get egress-policy <agent> -a
  claude-multiplex-demo -o yaml`). An actor without one has all egress denied.

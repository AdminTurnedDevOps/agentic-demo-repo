# Create an agent on Agent Substrate

This guide creates a Harness, an AgentTemplate, and an Agent with the kagent `api.kagent.dev/v1alpha3` API, then talks to the agent. Each conversation runs as a Substrate actor.

## Prerequisites

- kagent `1.0.0-alpha14` and Substrate `0.5.0-alpha2` installed with `kagent install`. See [kagent OSS on Agent Substrate: Install](kagent-oss-substrate-install.md).
- WorkerPool `kagent/kagent-default` and ModelConfig `kagent/default-model-config`, both created by that install.

> The Helm-only 0.10.x install path uses the older `kagent.dev/v1alpha2` API (`SandboxAgent`, `AgentHarness`). The manifests below do not apply to it.

## Create the Harness, AgentTemplate, and Agent
kagent does **not** create Harnesses for you. The manifests below match kagent's own e2e fixtures (`go/core/test/e2e/manifests/lifecycle.yaml.tmpl`):

- `spec.kagent: {}` uses the digest-pinned built-in kagent runtime image packaged with the release, so the Harness needs no `workload.image`.
- `snapshotPolicy.location` points at the `ate-snapshots` bucket that the Substrate chart's RustFS creates. Substrate's storage layer uses only the bucket and path from this URL. The storage backend comes from atelet's `storageBackend` setting (`s3`, backed by RustFS by default).

```yaml
# smoke-agent.yaml
apiVersion: api.kagent.dev/v1alpha3
kind: Harness
metadata:
  name: kagent
  namespace: kagent
spec:
  kagent: {}
  substrate:
    workerPoolRef:
      name: kagent-default
    snapshotPolicy:
      location: gs://ate-snapshots/kagent/
---
apiVersion: api.kagent.dev/v1alpha3
kind: AgentTemplate
metadata:
  name: smoke
  namespace: kagent
spec:
  description: Minimal Session lifecycle smoke test
  modelConfig:
    name: default-model-config
  systemPrompt: Reply briefly.
---
apiVersion: api.kagent.dev/v1alpha3
kind: Agent
metadata:
  name: smoke
  namespace: kagent
spec:
  template:
    ref:
      name: smoke
  harnessRef:
    name: kagent
```

```bash
kubectl apply --dry-run=server -f smoke-agent.yaml
kubectl apply -f smoke-agent.yaml

kubectl wait --for=condition=Ready harness/kagent -n kagent --timeout=5m
kubectl wait --for=condition=Ready agent/smoke   -n kagent --timeout=5m
kubectl get agents,agenttemplates,harnesses -n kagent
```

When the Agent becomes `Ready`, the controller has compiled a revision, registered its ActorTemplate with ate-api, and built the golden snapshot. ActorTemplates are now ate-api records, not Kubernetes objects. The `substrate-crds` chart has no ActorTemplate CRD, so `kubectl get actortemplates` will not find them.

How the resources relate:

```text
AgentTemplate (behavior: model, prompt, tools, skills)
      + Harness (execution: runtime, WorkerPool, snapshot location)
      = Agent
        ↓ kagent compiler
immutable revision → ateapi ActorTemplate → golden snapshot
        ↓ per conversation
Session → Substrate Actor
```

The Harness above uses the `kagent` runtime. A Harness can instead use `claude`, `codex`, or `byo`. A `byo` Harness must set `workload.image`.

- **To use a mirrored image** (for example, an Artifact Registry copy of `golang-adk`), set `spec.workload.image`. The image must be pinned by `@sha256:` digest, or the controller rejects it with `Harness image must be pinned by sha256 digest`.
- **To use your own bucket** (for example, a GCS bucket on GKE), set `snapshotPolicy.location` to that bucket and prefix.

## Test the agent

No Actor exists until a conversation starts. Each conversation is a **Session**. Sessions replace the pre-1.0 `AgentInstance`. A Session lives in PostgreSQL and is served over gRPC; it is not a Kubernetes resource. Every Session gets its own Substrate Actor, which is restored from the golden snapshot and suspended again when idle.

**From the UI:**

```bash
kagent dashboard
# or
kubectl -n kagent port-forward service/kagent-ui 8080:8080   # then open http://localhost:8080
```

Select the `smoke` agent and send a message. The first message creates the Session and its Actor.

**From the CLI** (the CLI opens its own port-forward to `kagent-controller:8083`):

```bash
kagent agent session create --agent smoke
# copy the Session ID from the output

kagent agent invoke --session <session-id> --task "Say hello"
```

The controller API (native gRPC, gRPC-Web, A2A, MCP, and health) runs on port `8083`:

```bash
kubectl -n kagent port-forward service/kagent-controller 8083:8083
```

## Clean up

```bash
kubectl delete -f smoke-agent.yaml --ignore-not-found
```

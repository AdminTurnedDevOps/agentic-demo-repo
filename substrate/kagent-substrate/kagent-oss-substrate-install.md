## Install

### Helm Charts

The charts below were generated from kagent commit `ab39f4d5`:

```bash
make helm-version VERSION=0.0.0-main.ab39f4d5
```

> **Important:** `substrate.enabled=false` prevents the kagent charts from installing bundled Substrate components if Substrate is already running in `ate-system`. Kagent connects to that existing installation instead, avoiding a duplicate or conflicting Substrate control plane.

Install the CRDs without installing the bundled Substrate CRDs:

```bash
helm upgrade --install kagent-crds
  --namespace kagent \
  --create-namespace \
  --wait \
  --timeout 5m \
  --set kmcp.enabled=true \
  --set substrate.enabled=false
```

Install kagent using the images built from the same commit. The bundled Substrate chart remains disabled, while the controller connects to the existing Substrate services:

```bash
helm upgrade --install kagent \
  --namespace kagent \
  --create-namespace \
  --wait \
  --timeout 10m \
  --set kmcp.enabled=true \
  --set substrate.enabled=false \
  --set database.postgres.bundled.storage=1Gi \
  --set controller.substrate.enabled=true \
  --set controller.substrate.ateApiEndpoint=dns:///api.ate-system.svc:443 \
  --set controller.substrate.atenetRouterURL=http://atenet-router.ate-system.svc:80 \
  --set controller.substrate.defaultWorkerPool.name=kagent-default \
  --set substrateWorkerPool.create=true \
  --set substrateWorkerPool.replicas=2 \
  --set-string substrateWorkerPool.workerImage=ghcr.io/kagent-dev/substrate/ateom-gvisor:v0.0.26 \
  --set substrateWorkerPool.sandboxClass=gvisor
```

### WorkerPool

You'll notice that with the Helm Installation of kagent, one `WorkerPool` gets created with two Workers (Replicas/Pods)

- WorkerPool: kagent/kagent-default
- Deployment: kagent-default
- Pods: two ateom-gvisor:v0.0.26 workers

The `WorkerPool` gets created by the `substrateWorkerPool.create=true` setting in the Helm Chart.

It is not required for the kagent controller or UI to run. It is, however, required when running Substrate-backed agents (a Harness must reference an existing same-namespace WorkerPool).

## Substrate Agentic Resources

These resources exercise the kagent-to-Substrate path by creating a Substrate-backed `Harness` and an `AgentTemplate` admitted by that Harness.

Current flow:
```
AgentTemplate + Harness
        ↓ kagent compiler
ateapi.ActorTemplate
        ↓
Substrate API/PostgreSQL
```

- AgentTemplate describes agent behavior: model, prompt, tools and skills.
- Harness describes execution: image, WorkerPool and snapshot location. The Harness is the reusable runtime (the framework and the Worker Pool thats used)
- The Agent that you'll see in the UI after running the below is the prepared harness + AgentTemplate pair

After you run the below, you'll see a new Template/Actor Template in the **substrate** tab via the UI and a new Agent in the **Agents** tab

1. Deploy the resources to create a template
```yaml
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha3
kind: Harness
metadata:
  name: kagent
  namespace: kagent
spec:
  kagent: {}
  workload:
    image: northamerica-northeast1-docker.pkg.dev/field-engineering-us/mlevan-images/kagent-dev/kagent/golang-adk@sha256:8de1c97bbd3fb75ececb5a82bdfa56ddb0eac393346baf8ca137ca3b91a830c5
  substrate:
    workerPoolRef:
      name: kagent-default
    snapshotPolicy:
      location: gs://ate-snapshots-field-engineering-us-substrate-mlevan/kagent/kagent
  allowedAgentTemplates:
    selector:
      matchLabels:
        kagent.dev/harness: kagent
---
apiVersion: kagent.dev/v1alpha3
kind: AgentTemplate
metadata:
  name: assistant
  namespace: kagent
  labels:
    kagent.dev/harness: kagent
spec:
  modelConfig:
    name: default-model-config
  description: A substrate-backed assistant used to verify this main build.
  systemPrompt: You are a helpful assistant running on kagent.
EOF
```

`AgentTemplate` is not the Substrate template replacement. Kagent combines an `AgentTemplate` with a Harness, compiles that pair into an `immutable ateapi.ActorTemplate`, and sends it to Substrate’s API. One AgentTemplate can produce multiple ateapi.ActorTemplate revisions or one per matching Harness.

The above `Harness` object example is using kagent, but you can also use `claude`, `codex`, and `byo`.

### Test The Actor In The UI

Create the Actor Instance

- In the UI, select the agent
- Send the first chat message, which performs the `CreateAgentInstance` operation.

Once you send the first conversation/chat an `AgentInstance` is created. The `AgentInstance` (not to be confused with the Agents in the UI under the **Agents** tab, corresponds to an Actor. Each new conversation creates another `AgentInstance` and underlying Actor.

The Harness/AgentTemplate pair must first have a successful prepared revision. Applying them prepares the backend ActorTemplate and golden snapshot, but does not create the user’s running Actor until an AgentInstance is created.

### Test The Actor Programmatically

kagent create agent-instance \
  --namespace kagent \
  --harness kagent \
  --agent-template assistant

That operation:

1. Selects the prepared revision for the Harness + AgentTemplate pair.
2. Creates an AgentInstance in kagent’s database.
3. Calls `ateapi.CreateActor`.
4. Creates an underlying Actor named `ai-<AgentInstance UUID>`.

The underlying Actor can remain suspended until invoked.
# Using Agent Substrate With kagent

This guide shows how to use Agent Substrate support in kagent `AgentHarness` resources.

It assumes kagent is already installed, running, and configured with Agent Substrate support. It does not cover kagent installation or upgrade steps.

For the current demo cluster, those prerequisites are already complete:

- kagent is running in the `kagent` namespace.
- Agent Substrate is running in the `ate-system` namespace.
- The kagent controller has Agent Substrate enabled.
- The default WorkerPool is `kagent/kagent-default`.
- The snapshot bucket is `gs://ate-snapshots-field-engineering-us-kagent-oss-felevan/`.

If you are using the current demo cluster, start at [4. Create a Gateway Token Secret](#4-create-a-gateway-token-secret).

## What kagent Provides

kagent supports `runtime: substrate` on `kagent.dev/v1alpha2` `AgentHarness` resources.

When enabled, kagent:

- Watches `AgentHarness` resources with `spec.runtime: substrate`
- References an existing Agent Substrate `WorkerPool`
- Generates one `ActorTemplate` per substrate `AgentHarness`
- Uses `ate-api` to create, resume, and delete actors
- Exposes a browser/API gateway path through the kagent controller

kagent does not install Agent Substrate and does not own `WorkerPool` capacity.

## Prerequisites

You need the following before creating a substrate-backed `AgentHarness`:

- kagent installed and running
- kagent controller configured with Agent Substrate support enabled
- Agent Substrate installed in the cluster
- Agent Substrate CRDs installed, including `WorkerPool` and `ActorTemplate`
- An `ate-api` service reachable from the kagent controller
- An `atenet-router` service reachable from the kagent controller
- At least one `WorkerPool`

Current demo values:

| Setting | Value |
|---|---|
| kagent namespace | `kagent` |
| Substrate namespace | `ate-system` |
| ate-api service | `api.ate-system.svc:443` |
| atenet router | `http://atenet-router.ate-system.svc:80` |
| Default WorkerPool | `kagent/kagent-default` |
| Snapshot bucket | `gs://ate-snapshots-field-engineering-us-kagent-oss-felevan/` |

Verify the required Agent Substrate CRDs:

```bash
kubectl get crd actortemplates.ate.dev workerpools.ate.dev
```

Verify Agent Substrate pods and services:

```bash
kubectl get pods -n ate-system
kubectl get svc -n ate-system
```

Expected services should include something like:

```text
api
atenet-router
```

Verify the kagent substrate API sees the integration:

```bash
kubectl run substrate-status-check -n kagent --rm -i --restart=Never \
  --image=curlimages/curl:8.10.1 -- \
  http://kagent-controller:8083/api/substrate/status
```

Expected response includes:

```json
"enabled": true
```

## 1. Verify kagent Has the Substrate Schema

Check that the `AgentHarness` CRD supports `runtime: substrate`:

```bash
kubectl get crd agentharnesses.kagent.dev \
  -o jsonpath='{.spec.versions[?(@.name=="v1alpha2")].schema.openAPIV3Schema.properties.spec.properties.runtime.enum}'
```

Expected output:

```text
["openshell","substrate"]
```

## 2. Find a WorkerPool

List existing WorkerPools:

```bash
kubectl get workerpools.ate.dev -A
```

Use the WorkerPool name in each `AgentHarness` unless your kagent controller has a default WorkerPool configured.

For the current demo cluster, the default WorkerPool is already configured:

```text
kagent/kagent-default
```

You can either set this explicitly in `spec.substrate.workerPoolRef.name` or omit `workerPoolRef` and let the controller default it.

## 3. Open the Substrate UI

After substrate is enabled, the kagent UI includes a substrate page:

```text
/substrate
```

Port-forward the UI if needed:

```bash
kubectl -n kagent port-forward service/kagent-ui 8080:8080
```

Open:

```text
http://localhost:8080/substrate
```

## 4. Create a Gateway Token Secret

Create a Secret for the OpenClaw gateway bearer token.

```yaml
kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: my-substrate-gateway-token
  namespace: kagent
type: Opaque
stringData:
  token: "replace-with-a-strong-token"
EOF
```

Apply it:

```bash
kubectl apply -f gateway-token.yaml
```

## 5. Create a Substrate AgentHarness

Example `AgentHarness` using `runtime: substrate`:

```yaml
apiVersion: kagent.dev/v1alpha2
kind: AgentHarness
metadata:
  name: openclaw-substrate-demo
  namespace: kagent
spec:
  backend: openclaw
  runtime: substrate
  description: OpenClaw harness running on Agent Substrate
  modelConfigRef: default-model-config
  substrate:
    workerPoolRef:
      name: kagent-default
    gatewayTokenSecretRef:
      name: my-substrate-gateway-token
    snapshotsConfig:
      location: gs://ate-snapshots-field-engineering-us-kagent-oss-felevan/kagent/openclaw-substrate-demo/
```

Apply it:

```bash
kubectl apply -f agentharness-substrate.yaml
```

If the kagent controller has `controller.substrate.defaultWorkerPool.name` configured, `workerPoolRef` can be omitted from the `AgentHarness`.

For the current demo cluster, this shorter form is also valid:

```yaml
apiVersion: kagent.dev/v1alpha2
kind: AgentHarness
metadata:
  name: openclaw-substrate-demo
  namespace: kagent
spec:
  backend: openclaw
  runtime: substrate
  description: OpenClaw harness running on Agent Substrate
  modelConfigRef: default-model-config
  substrate:
    gatewayTokenSecretRef:
      name: my-substrate-gateway-token
    snapshotsConfig:
      location: gs://ate-snapshots-field-engineering-us-kagent-oss-felevan/kagent/openclaw-substrate-demo/
```

## 6. Watch Readiness

Watch the harness:

```bash
kubectl get agentharness openclaw-substrate-demo -n kagent -w
```

Inspect full status:

```bash
kubectl get agentharness openclaw-substrate-demo -n kagent -o yaml
```

Expected condition progression:

```text
Accepted
ActorTemplateReady
ActorReady
Ready
```

## 7. Inspect Generated Substrate Resources

List WorkerPools and generated ActorTemplates:

```bash
kubectl get workerpools.ate.dev -A
kubectl get actortemplates.ate.dev -A
kubectl get agentharnesses.kagent.dev -n kagent
```

kagent owns the generated `ActorTemplate` through an owner reference on the `AgentHarness`. The `WorkerPool` remains externally owned.

## 8. Use the Harness Gateway

Once the `AgentHarness` is `Ready=True`, kagent exposes a gateway path:

```text
/api/agentharnesses/kagent/openclaw-substrate-demo/gateway/
```

Port-forward the controller if needed:

```bash
kubectl -n kagent port-forward service/kagent-controller 8083:8083
```

Open:

```text
http://localhost:8083/api/agentharnesses/kagent/openclaw-substrate-demo/gateway/
```

## Troubleshooting

Check the controller rollout:

```bash
kubectl rollout status deploy/kagent-controller -n kagent
kubectl logs -n kagent deploy/kagent-controller
```

Check AgentHarness status:

```bash
kubectl get agentharnesses.kagent.dev -n kagent
kubectl describe agentharness openclaw-substrate-demo -n kagent
```

Check Agent Substrate resources:

```bash
kubectl get workerpools.ate.dev -A
kubectl get actortemplates.ate.dev -A
kubectl get pods -n ate-system
```

Check the kagent substrate status API:

```bash
kubectl run substrate-status-check -n kagent --rm -i --restart=Never \
  --image=curlimages/curl:8.10.1 -- \
  http://kagent-controller:8083/api/substrate/status
```

Common issues:

- Missing `actortemplates.ate.dev` or `workerpools.ate.dev`: Agent Substrate is not installed.
- `spec.substrate.workerPoolRef is required`: configure a default WorkerPool for the controller or set `spec.substrate.workerPoolRef.name`.
- `ActorTemplateReady=False`: the generated `ActorTemplate` has not completed the golden snapshot process.
- `ActorReady=False`: kagent created the template, but `ate-api` has not created or resumed the actor yet.
- Gateway returns unavailable: check `controller.substrate.atenetRouterURL`, actor status, and the gateway token Secret.

## Notes

- Substrate support is for `AgentHarness`, not the regular `Agent` CRD.
- Supported substrate harness backends in this code path are `openclaw` and `nemoclaw`.
- `gatewayTokenSecretRef` is preferred over inline `gatewayToken`.
- `snapshotsConfig.location` must be a `gs://` URI.
- For this demo cluster, use `gs://ate-snapshots-field-engineering-us-kagent-oss-felevan/...` for snapshot locations.
- kagent deletes the actor on `AgentHarness` deletion and lets Kubernetes garbage collection remove the generated `ActorTemplate`.

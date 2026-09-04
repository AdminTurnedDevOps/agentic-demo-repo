# AgentHarness: Hermes Backend on Agent Substrate

An `AgentHarness` is a generic remote execution environment with **no agent runtime baked in**  The backend (`hermes` here) is the sandbox control plane that provisions the environment, and **Agent Substrate is the required compute layer underneath**: kagent generates a per-harness `ActorTemplate` and creates an `Actor` from it, scheduled onto an `ate.dev` `WorkerPool`.

The layering looks like this:

```
Hermes          -> sandbox control plane (provisions/manages the environment)
Hermes sandbox  -> the actual sandbox image (default when spec.image is empty)
Agent Substrate -> compute layer underneath (WorkerPool -> ActorTemplate -> Actor)
```

## Minimal example

The smallest valid Hermes harness. Leaving `spec.image` empty pins the workload to the Hermes sandbox base image, and omitting `substrate.workerPoolRef` uses the controller's default WorkerPool. Snapshots default to `gs://ate-snapshots/<namespace>/<agentharness-name>` when `snapshotsConfig` is unset.

```yaml
apiVersion: kagent.dev/v1alpha3
kind: AgentHarness
metadata:
  name: hermes-sandbox
  namespace: kagent
spec:
  backend: hermes
  substrate: {}
```

## Full example

A Hermes harness with an explicit WorkerPool, GCS snapshot location, model config, environment variables, and a Slack channel binding using Hermes-specific settings.

```yaml
apiVersion: kagent.dev/v1alpha3
kind: AgentHarness
metadata:
  name: hermes-sandbox
  namespace: kagent
spec:
  # Selects the sandbox control plane. Valid values: openclaw | hermes
  backend: hermes

  description: "Hermes remote execution environment running on Agent Substrate"

  # Agent Substrate provisioning stack (WorkerPool + ActorTemplate + Actor).
  # Required. The controller generates a per-harness ActorTemplate and creates
  # an Actor from it; the WorkerPool must already exist (kagent does not create it).
  substrate:
    # References an existing ate.dev WorkerPool in this namespace.
    # Omit to use the controller's configured default WorkerPool.
    workerPoolRef:
      name: default-worker-pool
    # GCS URI prefix for golden and incremental actor memory snapshots.
    # Must start with gs://. Defaults to gs://ate-snapshots/<namespace>/<name> when unset.
    snapshotsConfig:
      location: gs://ate-snapshots/kagent/hermes-sandbox/

  # Optional. Empty pins the workload to the Hermes sandbox base image.
  # image: ghcr.io/example/custom-hermes-sandbox:v0.1.0

  # ModelConfig used to configure the harness. The controller registers the
  # gateway provider once the harness is Ready.
  modelConfigRef: default-model-config

  # Environment variables injected into the harness workload (Kubernetes EnvVar shape).
  env:
    - name: LOG_LEVEL
      value: info
    - name: GITHUB_TOKEN
      valueFrom:
        secretKeyRef:
          name: harness-secrets
          key: github-token

  # Messenger integrations inside the harness VM.
  # For backend: hermes, Slack channels must set slack.hermes (not slack.openclaw) —
  # enforced by CEL validation on the CRD.
  channels:
    - name: slack-ops
      type: slack
      slack:
        # Exactly one of value or valueFrom per credential.
        botToken:
          valueFrom:
            type: Secret
            name: hermes-slack-credentials
            key: bot-token
        appToken:
          valueFrom:
            type: Secret
            name: hermes-slack-credentials
            key: app-token
        # Hermes-specific Slack settings (become env vars in the sandbox).
        hermes:
          # Restricts which Slack member IDs may interact with the bot (SLACK_ALLOWED_USERS).
          # Mutually exclusive with allowedUserIDsFrom.
          allowedUserIDs:
            - U0123456789
            - U0987654321
          # Default Slack channel ID for cron/scheduled messages (SLACK_HOME_CHANNEL).
          homeChannel: C0123456789
          # Human-readable label for homeChannel (SLACK_HOME_CHANNEL_NAME).
          homeChannelName: "#kagent-ops"
```

Without Slack:
```yaml
apiVersion: kagent.dev/v1alpha3
kind: AgentHarness
metadata:
  name: hermes-sandbox
  namespace: kagent
spec:
  # Selects the sandbox control plane. Valid values: openclaw | hermes
  backend: hermes

  description: "Hermes remote execution environment running on Agent Substrate"

  # Agent Substrate provisioning stack (WorkerPool + ActorTemplate + Actor).
  # Required. The controller generates a per-harness ActorTemplate and creates
  # an Actor from it; the WorkerPool must already exist (kagent does not create it).
  substrate:
    # References an existing ate.dev WorkerPool in this namespace.
    # Omit to use the controller's configured default WorkerPool.
    workerPoolRef:
      name: default-worker-pool
    # GCS URI prefix for golden and incremental actor memory snapshots.
    # Must start with gs://. Defaults to gs://ate-snapshots/<namespace>/<name> when unset.
    snapshotsConfig:
      location: gs://ate-snapshots/kagent/hermes-sandbox/

  # Optional. Empty pins the workload to the Hermes sandbox base image.
  # image: ghcr.io/example/custom-hermes-sandbox:v0.1.0

  # ModelConfig used to configure the harness. The controller registers the
  # gateway provider once the harness is Ready.
  modelConfigRef: default-model-config

  # Environment variables injected into the harness workload (Kubernetes EnvVar shape).
  env:
    - name: LOG_LEVEL
      value: info
    - name: GITHUB_TOKEN
      valueFrom:
        secretKeyRef:
          name: harness-secrets
          key: github-token
```

Supporting Secret for the Slack credentials (create it before the harness):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: hermes-slack-credentials
  namespace: kagent
type: Opaque
stringData:
  bot-token: xoxb-REPLACE_ME
  app-token: xapp-REPLACE_ME
```

## Checking status

```bash
# Short name: ahr
kubectl get agentharnesses -n kagent
kubectl describe ahr hermes-sandbox -n kagent
```

Readiness progresses through these conditions: `Accepted` → `ActorTemplateReady` → `ActorReady` → `BootstrapReady` → `Ready`. Once ready, `status.connection.endpoint` holds the backend-specific address (gRPC target, SSH host:port) for reaching the harness, and `status.backendRef.id` identifies the instance on the Hermes control plane.

> **Agent Substrate v1.0.0 note (2026-11-06):** This guide targets kagent's pre-1.0 Substrate (`kagent.dev/v1alpha2` harness API), the Substrate fork that kagent installs and pins, not an upstream Agent Substrate v1.0.0 install. That Substrate predates v1.0.0: it uses `ate.dev/v1alpha1`, `ateom-gvisor` worker images, and the `ateapi.Control` gRPC service with `actor_id`. kagent OSS `v1.0.0-rc3` now pins `kagent-dev/substrate v1.0.0` (`ate.dev/v1`, `substrate.ateapi.v1.Control`), and this guide has not been re-tested against it. Don't run kagent's Substrate and an upstream `ate-setup` install ([setup-gke.md](../install-and-setup/setup-gke.md)) in the same cluster: both own `ate-system` and the `ate.dev` CRDs.

## Harness Agents (OpenClaw and Hermes)

```
kubectl apply -f - <<'EOF'
apiVersion: kagent.dev/v1alpha2
kind: AgentHarness
metadata:
  name: my-openclaw
  namespace: kagent
spec:
  backend: openclaw
  description: OpenClaw on Agent Substrate (kagent-ee-felevan)
  modelConfigRef: default-model-config
  substrate:
    workerPoolRef:
      name: kagent-default
    snapshotsConfig:
      location: gs://ate-snapshots-field-engineering-us-substrate-mlevan/kagent/my-openclaw
EOF
```

## Declarative/BYO Agents

```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: SandboxAgent
metadata:
  name: my-sandbox-agent
  namespace: kagent
spec:
  type: Declarative
  declarative:
    modelConfig: default-model-config
    # instructions, tools, etc.
  substrate:
    workerPoolRef:
      name: kagent-default
    snapshotsConfig:
      location: gs://ate-snapshots-field-engineering-us-substrate-mlevan/kagent/mysandbox
EOF
```

If there is no:

```
    snapshotsConfig:
      location: gs://ate-snapshots-field-engineering-us-substrate-mlevan/kagent/my-openclaw
```

Because its an optional field, by default, it will default to: `gs://ate-snapshots/<namespace>/<agentname>`.

On a GKE/field cluster, you need:

1. A bucket that already exists
2. Permission for the atelet identity to write it

**important note**: kagent only writes that string onto the generated `ActorTemplate`. It does not create the bucket, grant IAM, or check that it exists. The CRD even requires the gs:// scheme (pattern: ^gs://).
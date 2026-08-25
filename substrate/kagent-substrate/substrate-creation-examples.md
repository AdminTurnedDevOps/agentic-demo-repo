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
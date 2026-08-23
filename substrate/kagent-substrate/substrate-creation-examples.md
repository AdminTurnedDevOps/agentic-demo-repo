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
apiVersion: kagent.dev/v1alpha2
kind: SandboxAgent
metadata:
  name: my-sandbox-agent
  namespace: kagent
spec:
  type: Declarative
  declarative:
    modelConfig: my-model
    # instructions, tools, etc.
  substrate:
    workerPoolRef:
      name: kagent-default
```
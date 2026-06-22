# Prompt Quickstart

Prompts are agentregistry catalog assets. Manage them with `arctl`.

## List Prompts

```bash
arctl get prompts
```

If no prompts exist, you should see:

```text
No prompts found.
```

## Create A Prompt

```bash
arctl apply -f - <<EOF
apiVersion: ar.dev/v1alpha1
kind: Prompt
metadata:
  name: kubernetes-triage-system-prompt
  tag: "1.0.0"
spec:
  description: "System prompt for Kubernetes troubleshooting agents"
  content: |
    You are a Kubernetes troubleshooting assistant.
    Be concise, ask for missing context, and prioritize evidence from kubectl output.
    When diagnosing failures, check resource status, events, logs, and recent changes before recommending fixes.
EOF
```

Expected result:

```text
Prompt/kubernetes-triage-system-prompt (1.0.0) created
```

If approval workflows are enabled and you are not an admin, the expected result
may be `staged` instead of `created`.

## Verify The Prompt

```bash
arctl get prompts
```

```bash
arctl get prompt kubernetes-triage-system-prompt --tag "1.0.0" -o yaml
```

## Delete The Prompt

```bash
arctl delete prompt kubernetes-triage-system-prompt --tag "1.0.0"
```

## Use The Prompt

```yaml
kubectl apply -f - <<EOF
apiVersion: ar.dev/v1alpha1
kind: Agent
metadata:
  name: k8shelperanthropic
  tag: "1.0.0"
spec:
  title: k8shelperanthropic
  modelProvider: anthropic
  modelName: claude-sonnet-4-6
  source:
    image: ...
  prompts:
    - name: kubernetes-triage-system-prompt
      registryPromptName: kubernetes-triage-system-prompt
      registryPromptVersion: "1.0.0"
EOF
```
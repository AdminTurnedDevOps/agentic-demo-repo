Three primary objects to understand:

1. `ModelConfig`: This is where you specify your LLM that you will use within your Actor (Agent)
2. `AgentTemplate`: Think of this like the "golden image" for your Actors. When you create an Actor, you specify the template.
3. `Harness`: This is where your Agent runs as an Actor

## Creation

Deploy the resources to create a template
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


The identity of an Actor is (`atespace`, name). An `atespace` is Substrate's own isolation boundary, not a Kubernetes namespace. In kagent the `atespace` is the instance's namespace, and the actor name is derived from the `AgentInstance` id (ai- plus the lowercased id).

## Routing An Actor

A request arrives at the router with a`te-target-actor: <atespace>/<actor>`. If the Actor is suspended, the router assigns a free Worker, `atelet` restores the snapshot into it, and the request is forwarded. Resume on the access log is triggered (woke it), none (already warm), or joined (waited on someone else's wake-up).

## Observability

Substrate access logs and metrics flow into ClickHouse. Enterprise handlers expose actor-request, activation, and fleet-capacity reads from that data.
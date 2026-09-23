Three primary objects to understand:

1. `ModelConfig`: This is where you specify your LLM that you will use within your Actor (Agent)
2. `AgentTemplate`: Think of this like the "golden image" for your Actors. When you create an Actor, you specify the template.
3. `Harness`: This is where your Agent runs as an Actor

## Creation


The identity of an Actor is (`atespace`, name). An `atespace` is Substrate's own isolation boundary, not a Kubernetes namespace. In kagent the `atespace` is the instance's namespace, and the actor name is derived from the `AgentInstance` id (ai- plus the lowercased id).

## Routing An Actor

A request arrives at the router with a`te-target-actor: <atespace>/<actor>`. If the Actor is suspended, the router assigns a free Worker, `atelet` restores the snapshot into it, and the request is forwarded. Resume on the access log is triggered (woke it), none (already warm), or joined (waited on someone else's wake-up).

## Observability

Substrate access logs and metrics flow into ClickHouse. Enterprise handlers expose actor-request, activation, and fleet-capacity reads from that data.
# Demo: Use a kagent agent from an MCP client

This demo makes kagent the **MCP server**. An MCP client calls an existing kagent
AgentInstance; kagent routes the call through A2A to an Agent Substrate Actor. It
is the opposite direction from binding an external `RemoteMCPServer` as a tool
*inside* an agent.

The commands target kagent `1.0.0-alpha3` and Agent Substrate `v0.2.0-beta5`.
Start with a cluster where both are installed and healthy. You need `kubectl`,
`jq`, Node.js 22.19.0 or newer, and `npx` to run MCP Inspector. The kagent UI
creates the conversation; MCP Inspector sends the subsequent turns.

## Prerequisites

https://kagent.dev/docs/kagent/1.x/setup/installation/

## Create the agent

The Harness selects the pinned Go ADK runtime and the existing WorkerPool. The
AgentTemplate supplies the model, prompt, and one read-only Kubernetes tool from
the installed `kagent-tool-server`.

```sh
kubectl apply -f - <<'YAML'
apiVersion: kagent.dev/v1alpha3
kind: Harness
metadata:
  name: mcp-demo-harness
  namespace: kagent
spec:
  kagent: {}
  workload:
    image: ghcr.io/kagent-dev/kagent/golang-adk@sha256:699c7a36daa0050d5954f42ad3b614690d825664cf64ffe8871dbe20dc68464e
  substrate:
    workerPoolRef:
      name: kagent-default
    snapshotPolicy:
      location: s3://ate-snapshots/kagent
  allowedAgentTemplates:
    selector:
      matchLabels:
        kagent.dev/harness: mcp-demo-harness
---
apiVersion: kagent.dev/v1alpha3
kind: AgentTemplate
metadata:
  name: mcp-demo-agent
  namespace: kagent
  labels:
    kagent.dev/harness: mcp-demo-harness
spec:
  description: Read-only Kubernetes assistant for the MCP client demo
  modelConfig:
    name: default-model-config
  systemPrompt: |
    You are a concise Kubernetes assistant. Use k8s_get_resources for live
    cluster facts. Report what the tool returns and do not modify resources.
  tools:
    - mcp:
        server:
          kind: RemoteMCPServer
          name: kagent-tool-server
        tools:
          - k8s_get_resources
YAML

kubectl -n kagent get agenttemplate mcp-demo-agent -o json \
  | jq '.status.harnesses[]? | {harness, conditions}'
```

Continue when the `mcp-demo-harness` entry has `Ready=True`. If it does not,
read its `ResolvedRefs`, `Compatible`, and `Ready` condition messages.

## Create a conversation in kagent

In one terminal, forward the kagent UI and leave it running:

```sh
kubectl -n kagent port-forward svc/kagent-ui 8080:8080
```

Open `http://localhost:8080/agents`, select **mcp-demo-agent** on
**mcp-demo-harness**, and select **New chat**. Send a short starter message such
as `Say hello; I will continue this conversation from an MCP client.` Wait for
the reply. The address changes to `http://localhost:8080/agents/<instance-id>/chat`;
copy that AgentInstance ID for the Inspector calls.

## Connect MCP Inspector

In a second terminal, forward the controller's MCP endpoint:

```sh
kubectl -n kagent port-forward svc/kagent-controller 8083:8083
```

In a third terminal, start the Inspector's web UI. The first `npx` run may
download the package.

```sh
npx @modelcontextprotocol/inspector \
  --server-url http://127.0.0.1:8083/mcp \
  --transport http \
  --protocol-era modern
```

Open the local URL printed by Inspector, including its session token, and select
**Connect** if it does not connect automatically. The transport is **Streamable
HTTP**. Modern mode negotiates MCP `2026-07-28` with kagent's stateless `/mcp`
endpoint. With the default unsecured OSS authentication mode, both the kagent
UI and Inspector use the same default caller, `admin@kagent.dev`.

## Call the agent from Inspector

1. Open **Tools** and select **List Tools**. Find `list_agent_instances` and
   `invoke_agent_instance` among kagent's tools.
2. Select `list_agent_instances` and run it with no arguments. Find the copied
   AgentInstance ID in the result alongside `mcp-demo-agent` and
   `mcp-demo-harness`.
3. Select `invoke_agent_instance`. Enter the copied ID for
   `agent_instance_id` and this text for `message`:

   > Use the Kubernetes tool to list Pods in the kagent namespace. Name any that are not Ready.

   Run the tool and inspect its text, task ID, and state. If Inspector offers
   **Run as task**, leave it off for a synchronous result.
4. Run `invoke_agent_instance` again with the same `agent_instance_id` and this
   message:

   > Which namespace did I ask about in the previous turn?

The second call continues the same conversation. These alpha3 MCP tools take an
AgentInstance ID and do not take a namespace argument.

To show the substrate side, open `http://localhost:8080/substrate` and find
`kagent/ai-<instance-id>` in the **Actors** table. After a completed turn, the
Actor can suspend and release its Worker while the AgentInstance remains ready.

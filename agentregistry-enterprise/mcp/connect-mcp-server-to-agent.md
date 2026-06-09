# Connect an MCP Server to an Agent

This guide shows how to wire an MCP server that was deployed through Agentregistry to an Agent that is also deployed through Agentregistry (for example, the `k8shelper` BYO agent on the `kagent` runtime).

It uses `github-copilot-mcp-server` as the example MCP and `k8shelper` as the example agent.

## How AgentRegistry Wires MCPs to Agents

For Agentregistry-managed agents, the MCP wiring belongs on the Agentregistry resources, not on the kagent CRs:

- The `Agent` declares which MCPs it depends on under `spec.mcpServers`.
- The `Deployment` declares which MCP deployments to wire under `spec.deploymentRefs`.
- AgentRegistry resolves the MCP endpoint and injects it into the generated kagent workload.

Important constraints:

- The agent and the MCP deployment must run on the same Runtime (here, `kagent`).
- The MCP referenced in `spec.mcpServers` must match a target in the agent Deployment's `deploymentRefs`.

### Resource Naming

The same agent has three different resource names across the layers:

| Layer | Kind | Name in this guide |
|-------|------|--------------------|
| AgentRegistry Agent | `ar.dev/v1alpha1` `Agent` | `k8shelper` |
| AgentRegistry Deployment | `ar.dev/v1alpha1` `Deployment` | `k8shelper-kagent` |
| Generated kagent Agent CR | `kagent.dev/v1alpha2` `Agent` | `k8shelper` (in `kagent` namespace) |
| Generated Kubernetes Deployment | `apps/v1` `Deployment` | `k8shelper` (in `kagent` namespace) |

Use the AgentRegistry Deployment name (`k8shelper-kagent`) with `arctl` commands, and the kagent / Kubernetes name (`k8shelper`) with `kubectl` commands.

## Option 1: Agentregistry-Managed (Recommended)

This is the right path for AgentRegistry-deployed agents like `k8shelper`.

### 1. Reference the MCP on the Agent

Update `k8shelper.yaml` to include `spec.mcpServers`:

```yaml
apiVersion: ar.dev/v1alpha1
kind: Agent
metadata:
  name: k8shelper
  tag: "1.0.0"
spec:
  title: k8shelper
  description: "Kubernetes helper agent deployed through the kagent runtime"
  modelProvider: gemini
  modelName: gemini-3.5-flash
  source:
    image: ${K8SHELPER_IMAGE}
  mcpServers:
    - kind: MCPServer
      name: github-copilot-mcp-server
```

Apply it:

```bash
envsubst < k8shelper.yaml | arctl apply -f -
```

### 2. Reference the MCP Deployment in the Agent Deployment

Update `ardeploy.yaml` to add `deploymentRefs`:

```yaml
apiVersion: ar.dev/v1alpha1
kind: Deployment
metadata:
  name: k8shelper-kagent
spec:
  targetRef:
    kind: Agent
    name: k8shelper
    tag: "1.0.0"
  runtimeRef:
    kind: Runtime
    name: kagent
  deploymentRefs:
    - name: gith-kage-7ln8cmrm74khnmu
  env:
    MODEL_PROVIDER: gemini
    MODEL_NAME: gemini-3.5-flash
```

Replace `gith-kage-7ln8cmrm74khnmu` with the name of the MCP Deployment you created in Agentregistry.

Apply it:

```bash
arctl apply -f ardeploy.yaml
```

Agentregistry will update the generated kagent Agent so it can call the MCP. For BYO kagent agents, Agentregistry injects the resolved MCPs through `MCP_SERVERS_CONFIG` on the generated workload. The `k8shelper` image must include support for reading that environment variable, or it must have the same JSON mounted at `/config/mcp-servers.json`.

For in-cluster MCP workloads, the resolved endpoint looks like:

```text
http://github-copilot-mcp-server.kagent.svc.cluster.local:3000/mcp
```

For remote MCPs, the injected config can point directly at the remote endpoint, for example `https://api.githubcopilot.com/mcp`, with any required headers included in the server entry.

### 3. Verify

Check the Agentregistry Deployment row. Use the Agentregistry Deployment name, for example `k8shelper-kagent`:

```bash
arctl get deployment k8shelper-kagent -o yaml
```

Look for:

- `Ready=True`
- `RuntimeConfigured=True`
- Resolved MCP endpoint either on the related MCP deployment as `MCPServerURL=True` or as part of the agent runtime config.

You can also confirm the generated kagent workload references the MCP from inside the cluster. The generated kagent `Agent` CR and the Kubernetes Deployment are named `k8shelper`:

```bash
kubectl get agent k8shelper -n kagent -o yaml | grep -i mcp
kubectl get deploy k8shelper -n kagent -o yaml | grep -i mcp
```

For the current `k8shelper` image, also confirm the runtime config source is present:

```bash
kubectl get deploy k8shelper -n kagent -o yaml | grep -E 'MCP_SERVERS_CONFIG|MCP_SERVERS_CONFIG_PATH|mcp-servers.json'
```

### Existing `k8shelper` Images

Current `k8shelper` source reads `MCP_SERVERS_CONFIG` directly. If you are using an older already-built image that only reads `/config/mcp-servers.json`, mount the MCP config as a Secret:

```bash
kubectl create secret generic k8shelper-mcp-servers \
  -n kagent \
  --from-file=mcp-servers.json=./mcp-servers.json \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl patch agent k8shelper -n kagent --type merge -p '{
  "spec": {
    "byo": {
      "deployment": {
        "volumes": [
          {
            "name": "mcp-servers-config",
            "secret": {
              "secretName": "k8shelper-mcp-servers",
              "items": [
                {
                  "key": "mcp-servers.json",
                  "path": "mcp-servers.json"
                }
              ]
            }
          }
        ],
        "volumeMounts": [
          {
            "name": "mcp-servers-config",
            "mountPath": "/config",
            "readOnly": true
          }
        ]
      }
    }
  }
}'
```

The `mcp-servers.json` file should be a JSON list of server entries. For a remote GitHub Copilot MCP endpoint, the shape is:

```json
[
  {
    "name": "github-copilot-mcp-server",
    "type": "remote",
    "url": "https://api.githubcopilot.com/mcp",
    "headers": {
      "Authorization": "${GITHUB_COPILOT_MCP_TOKEN}"
    }
  }
]
```

## Option 2: Native kagent (Skip Agentregistry MCP Wiring)

Use this option only if you want to manage the agent's tool list directly on the kagent side and bypass Agentregistry's MCP resolution.

If Agentregistry exposed the MCP as a service inside the cluster, register that service URL as a kagent `RemoteMCPServer`:

```yaml
apiVersion: kagent.dev/v1alpha2
kind: RemoteMCPServer
metadata:
  name: github-copilot
  namespace: kagent
spec:
  protocol: STREAMABLE_HTTP
  url: http://github-copilot-mcp-server.kagent.svc.cluster.local:3000/mcp
```

If the MCP is a remote endpoint and no in-cluster Service exists, point the `RemoteMCPServer` at the remote URL instead and provide any required headers through `headersFrom`:

```yaml
apiVersion: kagent.dev/v1alpha2
kind: RemoteMCPServer
metadata:
  name: github-copilot
  namespace: kagent
spec:
  protocol: STREAMABLE_HTTP
  url: https://api.githubcopilot.com/mcp
  headersFrom:
    - name: Authorization
      valueFrom:
        type: Secret
        name: github-copilot-mcp-auth
        key: Authorization
```

For declarative kagent Agents, reference the tools under `spec.declarative.tools`:

```yaml
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: my-declarative-agent
  namespace: kagent
spec:
  type: Declarative
  declarative:
    modelConfig: my-model-config
    tools:
      - type: McpServer
        mcpServer:
          kind: RemoteMCPServer
          name: github-copilot
          toolNames: []
```

> **Note:** `k8shelper` is a BYO image-based agent managed by Agentregistry. Use Option 1 for it. Option 2 is for kagent-managed declarative agents.

## Troubleshooting

- The Agent Deployment must reference the MCP Deployment in `deploymentRefs`, and the Agent CR must list the MCP in `spec.mcpServers`. Agentregistry enforces this match for non-kagent targets and uses it to derive the MCP endpoint for kagent.
- The agent and the MCP Deployment must use the same Runtime. Cross-runtime MCP wiring is rejected.
- If the MCP endpoint is not resolved, check the MCP Deployment's status conditions for `MCPServerURL` and confirm the MCP workload is running in the kagent namespace.
- If a generated kagent `RemoteMCPServer` has `Accepted=False` with `unsupported protocol scheme ""`, its `spec.url` is missing an `http://` or `https://` scheme.
- If the Agentregistry Deployment is `deployed` but the BYO agent has no MCP tools, check whether the image reads `MCP_SERVERS_CONFIG`. Older `k8shelper` images only read `/config/mcp-servers.json` or `MCP_SERVERS_CONFIG_PATH`.
- After updating the Agent or Deployment, re-apply through Agentregistry. Direct edits to the kagent CR are reconciled away by Agentregistry on the next sync.

# Connect an MCP Server to an Agent

This guide shows a clean, repeatable flow for deploying the GitHub Copilot MCP server through Agentregistry Enterprise and wiring it to the `k8shelper` BYO agent on the `kagent` runtime.

Use this flow after deleting the Agentregistry Agent, MCP server, or Deployment records.

## Prerequisites

- Enterprise `arctl` is installed and authenticated.
- `ARCTL_API_BASE_URL` and `ARCTL_API_TOKEN` are set, or equivalent `--registry-url` / `--registry-token` flags are used.
- The `kagent` runtime exists in Agentregistry:

```bash
arctl get runtime kagent -o yaml
```

Expected runtime shape:

```yaml
spec:
  type: Kagent
  config:
    kagentUrl: http://kagent-controller.kagent.svc.cluster.local:8083
    namespace: kagent
```

- The `k8shelper` image is built from `agentregistry-enterprise/k8shelper`, including:
  - `k8shelper/mcp_tools.py`, which reads `MCP_SERVERS_CONFIG` and filters the incompatible `issue_write` tool by default.
  - `k8shelper/agent.py`, which includes `list_available_tools` and prompts the model to disclose GitHub MCP capabilities.

## Resource Names

| Layer | Kind | Example name |
|-------|------|--------------|
| Agentregistry MCP artifact | `ar.dev/v1alpha1` `MCPServer` | `github-copilot-mcp-server` |
| Agentregistry MCP deployment | `ar.dev/v1alpha1` `Deployment` | `github-copilot-mcp-kagent` |
| Agentregistry Agent artifact | `ar.dev/v1alpha1` `Agent` | `k8shelper` |
| Agentregistry Agent deployment | `ar.dev/v1alpha1` `Deployment` | `k8shelper-kagent` |
| Generated kagent Agent CR | `kagent.dev/v1alpha2` `Agent` | `k8shelper` in namespace `kagent` |
| Generated Kubernetes Deployment | `apps/v1` `Deployment` | `k8shelper` in namespace `kagent` |

Use Agentregistry names with `arctl`. Use generated kagent/Kubernetes names with `kubectl`.

## 1. Build k8shelper

From the root of `agentic-demo-repo`:

```bash
cd agentregistry-enterprise/k8shelper

export K8SHELPER_IMAGE="<your-registry>/k8shelper:github-mcp"
docker buildx build --platform linux/amd64 -t "${K8SHELPER_IMAGE}" --push .
```

Use a registry your cluster can pull from.

## 2. Register the GitHub Copilot MCP Artifact

Use `agentregistry-enterprise/mcp/github-copilot-mcpserver.yaml`:

```yaml
apiVersion: ar.dev/v1alpha1
kind: MCPServer
metadata:
  name: github-copilot-mcp-server
  tag: latest
spec:
  description: GitHub Copilot MCP Server to interact with GitHub repositories, issues, pull requests, and Copilot coding-agent tasks
  remote:
    type: streamable-http
    url: https://api.githubcopilot.com/mcp
    headers:
      - name: Authorization
        value: ${GITHUB_COPILOT_MCP_TOKEN}
```

Apply it:

```bash
envsubst < agentregistry-enterprise/mcp/github-copilot-mcpserver.yaml | arctl apply -f -
arctl get mcps
arctl get mcp github-copilot-mcp-server --tag latest -o yaml
```

For demos, the token can be rendered into the Agentregistry MCP artifact. For production-style flows, use the secret mechanism supported by your Agentregistry deployment instead of literal values.

## 3. Deploy the MCP to kagent

Use `agentregistry-enterprise/mcp/github-copilot-mcp-deploy.yaml`:

```yaml
apiVersion: ar.dev/v1alpha1
kind: Deployment
metadata:
  name: github-copilot-mcp-kagent
spec:
  runtimeRef:
    kind: Runtime
    name: kagent
  targetRef:
    kind: MCPServer
    name: github-copilot-mcp-server
    tag: latest
```

Apply it:

```bash
arctl apply -f agentregistry-enterprise/mcp/github-copilot-mcp-deploy.yaml
arctl get deployments
arctl get deployment github-copilot-mcp-kagent -o yaml
```

Look for:

- `phase: deployed`
- `Ready=True`
- `RuntimeConfigured=True`
- `MCPServerURL=True`

If you use a different MCP Deployment name, use that exact name in `deploymentRefs` when deploying `k8shelper`.

## 4. Register k8shelper

`agentregistry-enterprise/providers/kagent/k8shelper.yaml` should reference the image and MCP artifact:

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
cd agentregistry-enterprise/providers/kagent
envsubst < k8shelper.yaml | arctl apply -f -
arctl get agent k8shelper --tag 1.0.0 -o yaml
```

## 5. Deploy k8shelper and Wire the MCP

`agentregistry-enterprise/providers/kagent/ardeploy.yaml` should reference the MCP Deployment from step 3:

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
    - name: github-copilot-mcp-kagent
  env:
    MODEL_PROVIDER: gemini
    MODEL_NAME: gemini-3.5-flash
```

Apply it:

```bash
arctl apply -f ardeploy.yaml
arctl get deployment k8shelper-kagent -o yaml
```

Look for:

- `phase: deployed`
- `Ready=True`
- `RuntimeConfigured=True`
- runtime metadata pointing at namespace `kagent`

## 6. Configure Runtime Secrets

The generated kagent Agent needs the Gemini API key in the `kagent` namespace:

```bash
kubectl create secret generic k8shelper-google \
  -n kagent \
  --from-literal=GOOGLE_API_KEY="${GOOGLE_API_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Patch the generated kagent Agent CR to reference the Secret:

```bash
kubectl patch agent k8shelper -n kagent --type='json' -p='[
  {"op":"add","path":"/spec/byo/deployment/env/-","value":{"name":"GOOGLE_API_KEY","valueFrom":{"secretKeyRef":{"name":"k8shelper-google","key":"GOOGLE_API_KEY"}}}}
]'
```

Roll out and verify:

```bash
kubectl rollout status deployment/k8shelper -n kagent --timeout=5m
kubectl get agent k8shelper -n kagent -o yaml
kubectl get pods -n kagent -l kagent=k8shelper
```

## 7. Verify MCP Wiring

Check that Agentregistry injected MCP configuration into the generated kagent workload:

```bash
kubectl get agent k8shelper -n kagent -o yaml | grep -i mcp
kubectl get deploy k8shelper -n kagent -o yaml | grep -E 'MCP_SERVERS_CONFIG|MCP_SERVERS_CONFIG_PATH|mcp-servers.json'
```

Check the kagent-side RemoteMCPServer if one was created:

```bash
kubectl get remotemcpservers.kagent.dev -n kagent
kubectl get remotemcpserver github-copilot-mcp-server -n kagent -o yaml
```

A healthy RemoteMCPServer has:

- `Accepted=True`
- `spec.url` set to `https://api.githubcopilot.com/mcp` or another valid `http://` / `https://` URL
- populated `status.discoveredTools`

From inside the pod, confirm the agent sees the GitHub MCP tools:

```bash
kubectl exec -i -n kagent deploy/k8shelper -- python - <<'PY'
import asyncio
from k8shelper.agent import root_agent

async def main():
    all_tools = []
    for tool in root_agent.tools:
        if hasattr(tool, "get_tools"):
            all_tools.extend(await tool.get_tools())
        else:
            all_tools.append(tool)

    names = [getattr(tool, "name", getattr(tool, "__name__", type(tool).__name__)) for tool in all_tools]
    print("tool_count", len(names))
    print("has_list_available_tools", "list_available_tools" in names)
    print("has_github_tools", any(name in names for name in ["search_repositories", "create_pull_request", "get_me"]))
    print("has_issue_write", "issue_write" in names)

    for tool in root_agent.tools:
        if hasattr(tool, "close"):
            await tool.close()

asyncio.run(main())
PY
```

Expected output:

```text
has_list_available_tools True
has_github_tools True
has_issue_write False
```

`issue_write` is filtered out by default because the GitHub Copilot MCP schema includes a boolean-only enum that Gemini rejects when converting MCP tools to function declarations. Override `MCP_DISABLED_TOOLS` only if your model/runtime accepts that schema.

## Existing Image Workaround

Prefer rebuilding the image. Use this workaround only when you must run an older image that does not include the current `agent.py` and `mcp_tools.py`.

Create `/tmp/mcp-servers.json` with only the direct remote GitHub MCP endpoint:

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

Create the Secret:

```bash
envsubst < /tmp/mcp-servers.json > /tmp/mcp-servers.rendered.json

kubectl create secret generic k8shelper-mcp-servers \
  -n kagent \
  --from-file=mcp-servers.json=/tmp/mcp-servers.rendered.json \
  --dry-run=client -o yaml | kubectl apply -f -
```

Create a ConfigMap with the current source files:

```bash
kubectl create configmap k8shelper-code-override \
  -n kagent \
  --from-file=agent.py=agentregistry-enterprise/k8shelper/k8shelper/agent.py \
  --from-file=mcp_tools.py=agentregistry-enterprise/k8shelper/k8shelper/mcp_tools.py \
  --dry-run=client -o yaml | kubectl apply -f -
```

Patch the generated kagent Agent. The first patch adds `MCP_SERVERS_CONFIG_PATH` without replacing the existing environment variables. If that variable already exists, edit or replace the existing entry instead of adding a duplicate.

```bash
kubectl patch agent k8shelper -n kagent --type json -p='[
  {"op":"add","path":"/spec/byo/deployment/env/-","value":{"name":"MCP_SERVERS_CONFIG_PATH","value":"/config/mcp-servers.json"}}
]'

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
          },
          {
            "name": "k8shelper-code-override",
            "configMap": {
              "name": "k8shelper-code-override",
              "items": [
                {
                  "key": "mcp_tools.py",
                  "path": "mcp_tools.py"
                },
                {
                  "key": "agent.py",
                  "path": "agent.py"
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
          },
          {
            "name": "k8shelper-code-override",
            "mountPath": "/app/k8shelper/mcp_tools.py",
            "subPath": "mcp_tools.py",
            "readOnly": true
          },
          {
            "name": "k8shelper-code-override",
            "mountPath": "/app/k8shelper/agent.py",
            "subPath": "agent.py",
            "readOnly": true
          }
        ]
      }
    }
  }
}'

kubectl rollout status deployment/k8shelper -n kagent --timeout=5m
```

Direct patches to generated kagent resources can be overwritten by future Agentregistry redeploys.

## Troubleshooting

- `arctl get deployments` shows the MCP deployment as `deployed`, but k8shelper has no GitHub tools:
  - Confirm `k8shelper` was built from `agentregistry-enterprise/k8shelper`.
  - Confirm `MCP_SERVERS_CONFIG` or `MCP_SERVERS_CONFIG_PATH` is present in the generated Deployment.
  - Confirm `list_available_tools` is present in the live pod.

- `RemoteMCPServer` has `Accepted=False` with `unsupported protocol scheme ""`:
  - Its `spec.url` is missing `http://` or `https://`.
  - For GitHub Copilot MCP, use `https://api.githubcopilot.com/mcp`.

- Gemini returns `400 INVALID_ARGUMENT` for a function declaration enum:
  - Confirm `issue_write` is filtered out.
  - Check `MCP_DISABLED_TOOLS`; default should include `issue_write`.

- The model says it only has `roll_die` and `check_prime`:
  - Confirm you are running the current `agent.py` with `list_available_tools`.
  - Ask: `What tools do you have access to?` The agent should call `list_available_tools` and summarize local plus GitHub MCP categories.

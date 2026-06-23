# k8shelper

Kubernetes helper agent for kagent demos.

## Model Configuration

The agent uses ADK with LiteLLM for Anthropic so it calls Anthropic directly
with `ANTHROPIC_API_KEY`. It does not use Anthropic on Vertex. For
Anthropic/Claude set:

```bash
export MODEL_PROVIDER=anthropic
export MODEL_NAME=claude-sonnet-4-6
export ANTHROPIC_API_KEY=<your-anthropic-api-key>
```

When `MODEL_PROVIDER=anthropic`, the code prefixes `MODEL_NAME` with
`anthropic/` for LiteLLM if you provide a bare Claude model name.

## MCP Configuration

The agent loads runtime MCP servers from `MCP_SERVERS_CONFIG` when Agent Registry injects it. It also supports file-based config from `MCP_SERVERS_CONFIG_PATH` or `/config/mcp-servers.json`.

By default, `issue_write` is filtered out through `MCP_DISABLED_TOOLS` because the GitHub Copilot MCP schema includes a boolean-only enum that some models reject when converting MCP tools to function declarations. Override `MCP_DISABLED_TOOLS` if you are using a model/runtime that accepts that schema.

The agent includes `list_available_tools` so users can ask what local and GitHub MCP-backed tools are available.

Build (amd64) and push to Artifact Registry (field-engineering-us / mlevan-images):

From the repo root:

```bash
cd k8shelper-anthropic

# Build the linux/amd64 image locally (cross-compile on Apple Silicon etc.)
docker buildx build --platform linux/amd64 -t k8shelperanthropic:claude-sonnet-4-6 --load .

# Tag + push the specific version (and optionally :latest)
export K8SHELPER_IMAGE="northamerica-northeast1-docker.pkg.dev/field-engineering-us/mlevan-images/k8shelperanthropic:direct-anthropic-20260615105149"
docker tag k8shelperanthropic:claude-sonnet-4-6 "${K8SHELPER_IMAGE}"
docker push "${K8SHELPER_IMAGE}"

# Optional latest alias
docker tag "${K8SHELPER_IMAGE}" northamerica-northeast1-docker.pkg.dev/field-engineering-us/mlevan-images/k8shelperanthropic:latest
docker push northamerica-northeast1-docker.pkg.dev/field-engineering-us/mlevan-images/k8shelperanthropic:latest
```

The image is now available at:

```
northamerica-northeast1-docker.pkg.dev/field-engineering-us/mlevan-images/k8shelperanthropic:direct-anthropic-20260615105149
```

## Deploy to kagent

These steps assume you have already registered a `kagent` Runtime (see `providers/kagent/kagent-provider-setup.md` for the one-time runtime registration + `INSECURE_MODE` note if needed).

### 1. Apply the Agent

```bash
# From the root of agentregistry-enterprise. The image is set directly in the manifest.
arctl apply -f providers/kagent/anthropicagent/k8shelperanthropic.yaml
arctl get agents
```

### 2. Create the secret for the Anthropic key

Do **not** put the key directly in manifests.

```bash
kubectl create secret generic k8shelper-anthropic \
  -n kagent \
  --from-literal=ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 3. Apply the Deployment

```bash
arctl apply -f providers/kagent/anthropicagent/ardeploy.yaml
```

### 4. Patch the generated kagent Agent to inject the secret

```bash
kubectl patch agent k8shelperanthropic -n kagent --type='json' -p='[
  {"op":"add","path":"/spec/byo/deployment/env/-","value":{"name":"ANTHROPIC_API_KEY","valueFrom":{"secretKeyRef":{"name":"k8shelper-anthropic","key":"ANTHROPIC_API_KEY"}}}}
]'

kubectl rollout status deployment/k8shelperanthropic -n kagent --timeout=5m
```

The deployment should reach `Ready=True`.

### 5. Verify

```bash
kubectl get agents.kagent.dev -n kagent k8shelperanthropic -o yaml
kubectl get pods -n kagent -l kagent=k8shelperanthropic
kubectl get svc -n kagent -l kagent=k8shelperanthropic
kubectl get deploy k8shelperanthropic -n kagent -o yaml | grep -E 'MODEL_NAME|MODEL_PROVIDER|ANTHROPIC_API_KEY|image:'
```

### Troubleshooting

Common reference errors when applying `ardeploy.yaml`:

- `spec.targetRef: referenced resource not found` — You applied the Deployment before the corresponding Agent catalog item. The `k8shelperanthropic.yaml` (the `ar.dev/v1alpha1` `Agent`) **must** be applied first so it exists in the registry catalog.
- `spec.deploymentRefs[0]: referenced resource not found` (for `github-copilot-mcp-kagent`) — The MCP server Deployment to the runtime must also exist first. Apply it with:

  ```bash
  arctl apply -f mcp/github-copilot-mcp-deploy.yaml
  ```

Always follow this order:

1. Apply the Agent catalog item (`k8shelperanthropic.yaml`)
2. Apply any required `deploymentRefs` (e.g. the MCP deploy above)
3. Apply the Deployment (`ardeploy.yaml`)

```bash
arctl get deployment k8shelperanthropic-kagent -o yaml
```

See the main `providers/kagent/kagent-provider-setup.md` for additional troubleshooting around auth, image pull, and controller connectivity.

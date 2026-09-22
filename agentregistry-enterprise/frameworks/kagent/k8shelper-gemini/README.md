# k8shelper

Kubernetes helper agent for kagent demos.

## Model Configuration

The agent reads the Gemini model from `MODEL_NAME` and defaults to `gemini-3.5-flash`:

```bash
export MODEL_PROVIDER=gemini
export MODEL_NAME=gemini-3.5-flash
export GOOGLE_API_KEY=<your-google-api-key>
```

## MCP Configuration

The agent loads runtime MCP servers from `MCP_SERVERS_CONFIG` when Agent Registry injects it. It also supports file-based config from `MCP_SERVERS_CONFIG_PATH` or `/config/mcp-servers.json`.

By default, `issue_write` is filtered out through `MCP_DISABLED_TOOLS` because the GitHub Copilot MCP schema includes a boolean-only enum that Gemini rejects when converting MCP tools to function declarations. Override `MCP_DISABLED_TOOLS` if you are using a model/runtime that accepts that schema.

The agent includes `list_available_tools` so users can ask what local and GitHub MCP-backed tools are available.

## Build (amd64) and push to Artifact Registry (field-engineering-us / mlevan-images)

From the repo root:

```bash
cd k8shelper-gemini

# Build the linux/amd64 image locally (cross-compile on Apple Silicon etc.)
docker buildx build --platform linux/amd64 -t k8shelpergemini:gemini-3.5-flash --load .

# Tag + push the specific version (and optionally :latest)
export K8SHELPER_IMAGE="northamerica-northeast1-docker.pkg.dev/field-engineering-us/mlevan-images/k8shelpergemini:gemini-3.5-flash"
docker tag k8shelpergemini:gemini-3.5-flash "${K8SHELPER_IMAGE}"
docker push "${K8SHELPER_IMAGE}"

# Optional latest alias
docker tag "${K8SHELPER_IMAGE}" northamerica-northeast1-docker.pkg.dev/field-engineering-us/mlevan-images/k8shelpergemini:latest
docker push northamerica-northeast1-docker.pkg.dev/field-engineering-us/mlevan-images/k8shelpergemini:latest
```

The image is now available at:

```
northamerica-northeast1-docker.pkg.dev/field-engineering-us/mlevan-images/k8shelpergemini:gemini-3.5-flash
```

## Deploy to kagent

These steps assume you have already registered a `kagent` Runtime (see `providers/kagent/kagent-provider-setup.md` for the one-time runtime registration + `INSECURE_MODE` note if needed).

### 1. Set the image and apply the Agent

```bash
# From the root of agentregistry-enterprise
export K8SHELPER_IMAGE="northamerica-northeast1-docker.pkg.dev/field-engineering-us/mlevan-images/k8shelpergemini:gemini-3.5-flash"

envsubst < providers/kagent/geminiagent/k8shelpergemini.yaml | arctl apply -f -
arctl get agents
```

### 2. Create the secret for the Google/Gemini API key

Do **not** put the key directly in manifests.

```bash
kubectl create secret generic k8shelper-google \
  -n kagent \
  --from-literal=GOOGLE_API_KEY="${GOOGLE_API_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 3. Apply the Deployment

```bash
arctl apply -f providers/kagent/geminiagent/ardeploy.yaml
```

### 4. Patch the generated kagent Agent to inject the secret

```bash
kubectl patch agent k8shelper -n kagent --type='json' -p='[
  {"op":"add","path":"/spec/byo/deployment/env/-","value":{"name":"GOOGLE_API_KEY","valueFrom":{"secretKeyRef":{"name":"k8shelper-google","key":"GOOGLE_API_KEY"}}}}
]'

kubectl rollout status deployment/k8shelper -n kagent --timeout=5m
```

The deployment should reach `Ready=True`.

### 5. Verify

```bash
kubectl get agents.kagent.dev -n kagent k8shelper -o yaml
kubectl get pods -n kagent -l kagent=k8shelper
kubectl get svc -n kagent -l kagent=k8shelper
kubectl get deploy k8shelper -n kagent -o yaml | grep -E 'MODEL_NAME|MODEL_PROVIDER|GOOGLE_API_KEY|image:'
```

### Troubleshooting

```bash
arctl get deployment k8shelper-kagent -o yaml
```

See the main `providers/kagent/kagent-provider-setup.md` for additional troubleshooting around auth, image pull, and controller connectivity.

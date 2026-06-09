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

Build and push an amd64 image for Kubernetes nodes:

```bash
export K8SHELPER_IMAGE="<your-registry>/k8shelper:model-fix"
docker buildx build --platform linux/amd64 -t "${K8SHELPER_IMAGE}" --push .
```

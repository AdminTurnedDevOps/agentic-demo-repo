# Claude Code with AgentGateway

Route Claude Code CLI/Desktop LLM traffic through agentgateway for security, observability, and rate limiting.

## Prerequisites

- Claude Code CLI installed (`npm install -g @anthropic-ai/claude-code`)
- AgentGateway deployed and running (see [agentgateway-enterprise/setup.md](../../agentgateway-enterprise/setup.md))
- Anthropic API key

## Create Anthropic API Key Secret

Store your Anthropic API key in a Kubernetes secret:

```bash
kubectl create secret generic anthropic-api-key \
  --from-literal=api-key=YOUR_ANTHROPIC_API_KEY \
  -n gloo-system
```

## Gateway/Backend Setup

1. Create a Gateway (or reuse existing):
```bash
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: agentgateway-llm
  namespace: gloo-system
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
  - name: http
    port: 8080
    protocol: HTTP
    allowedRoutes:
      namespaces:
        from: Same
EOF
```

2. Create an LLM Backend for Anthropic:
```bash
kubectl apply -f - <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: anthropic-llm
  namespace: gloo-system
spec:
  llm:
    targets:
      - name: anthropic
        anthropic:
          apiKeySecretRef:
            name: anthropic-api-key
            key: api-key
EOF
```

3. Create the HTTPRoute:
```bash
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: llm-route
  namespace: gloo-system
spec:
  parentRefs:
  - name: agentgateway-llm
  rules:
  - backendRefs:
    - name: anthropic-llm
      namespace: gloo-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```

4. Get the Gateway IP:
```bash
export GATEWAY_IP=$(kubectl get svc agentgateway-llm -n gloo-system -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo $GATEWAY_IP
```

## Configure Claude Code CLI

### Option 1: Environment Variable (Recommended)

Set the base URL to point to your gateway:

```bash
export ANTHROPIC_BASE_URL=http://$GATEWAY_IP:8080
```

Add to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.) for persistence:

```bash
echo 'export ANTHROPIC_BASE_URL=http://YOUR_GATEWAY_IP:8080' >> ~/.zshrc
```

### Option 2: Per-Session

Run Claude Code with the environment variable:

```bash
ANTHROPIC_BASE_URL=http://YOUR_GATEWAY_IP:8080 claude
```

## Verify Connection

1. Start Claude Code:
```bash
claude
```

2. Send a test message and verify traffic flows through the gateway

3. Check gateway logs for the request:
```bash
kubectl logs -n gloo-system -l app=agentgateway-llm -f
```

## What This Enables

- **Centralized API Key Management**: API keys stored in Kubernetes secrets, not on developer machines
- **Observability**: Monitor and trace all LLM API calls
- **Rate Limiting**: Control usage and costs across teams
- **Access Control**: Implement policies on who can access the LLM
- **Audit Logging**: Track all interactions for compliance

## Advanced Configuration

### With JWT Authentication

If you've configured JWT auth on the gateway:

```bash
export ANTHROPIC_BASE_URL=http://YOUR_GATEWAY_IP:8080
export ANTHROPIC_AUTH_TOKEN=your-jwt-token
```

### Multiple LLM Providers

You can configure multiple LLM backends and route based on path or headers:

```yaml
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: openai-llm
  namespace: gloo-system
spec:
  llm:
    targets:
      - name: openai
        openai:
          apiKeySecretRef:
            name: openai-api-key
            key: api-key
```

## Troubleshooting

### Connection Refused
- Verify the gateway service has an external IP: `kubectl get svc -n gloo-system`
- Check firewall rules allow traffic on port 8080

### Authentication Errors
- Verify the secret exists: `kubectl get secret anthropic-api-key -n gloo-system`
- Check the API key is valid

### Timeout Errors
- LLM requests can take time; ensure gateway timeouts are configured appropriately
- Check gateway pod resources are sufficient

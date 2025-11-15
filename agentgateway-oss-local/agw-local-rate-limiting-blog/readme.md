# Provider Rate Limiting Blog Demo

Ensure to set your environment variables for API keys.

```
export ANTHROPIC_API_KEY=
export OPENAI_API_KEY=
```

## Local Rate Limiting

1. Save the below as `local-rate-limit.yaml` (you can also find it in the same directory as this readme)

```
binds:
- port: 3000
  listeners:
  - routes:
    - backends:
      - ai:
          name: openai
          provider:
            openAI:
              model: gpt-3.5-turbo
          routes:
            /v1/chat/completions: completions
            /v1/models: passthrough
            '*': passthrough
      policies:
        cors:
          allowOrigins:
          - "*"
          allowHeaders:
          - "*"
        backendAuth:
          key: $OPENAI_API_KEY
        localRateLimit:
          - maxTokens: 1
            tokensPerFill: 1
            fillInterval: 100s
            type: tokens
```

2. Run the following:
```
agentgateway -f local-rate-limiting.yaml
```

3. Test the route

```
curl http://localhost:3000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

4. Run it again immediately after and you'll see an out similar to the below:
```
rate limit exceeded%
```

You can try out the same thing with Anthropic
```
binds:
 - port: 3000
   listeners:
   - routes:
     - backends:
       - ai:
           name: anthropic
           provider:
             anthropic:
               model: claude-haiku-4-5-20251001
           routes:
             /v1/messages: messages
             /v1/chat/completions: completions
             /v1/models: passthrough
             '*': passthrough
       policies:
         backendAuth:
           key: $ANTHROPIC_API_KEY
```

## Metrics

1. Run the `mcp-endpoint.yaml` (you can find it in the same directory as this readme) with the `agentgateway` CLI

```
binds:
- port: 3001
  listeners:
  - routes:
    - backends:
      - mcp:
          targets:
          - name: kubernetes
            stdio:
              cmd: uvx
              args: ["cloud-native-architecture-mcp@latest"]
      policies:
        cors:
          allowOrigins:
          - '*'
          allowHeaders:
          - mcp-protocol-version
          - content-type
          - cache-control
          - accept
          allowMethods:
          - GET
          - POST
          - OPTIONS
```

2. Go to the agentgateway metrics endpoint in a browser
```
http://localhost:15020/metrics
```

3. Go to the Playground and run the connection to the MCP Server

4. Refresh the `/metrics` endpoint page in the web browser and you'll see the new metrics exposed

## Model Failover

1. Run the `model-failover.yaml` (you can find it in the same directory as this readme) with the `agentgateway` CLI

```
binds:
- port: 3000
  listeners:
  - routes:
    - name: failover-ai
      matches:
      - path:
          pathPrefix: /failover/ai
      policies:
        retry:
          attempts: 2        # Retry once (2 total attempts)
          codes: [400, 401, 403, 404, 429, 500, 502, 503, 504]  # Retry on auth, rate limit, and server errors
        urlRewrite:
          path:
            prefix: ""
      backends:
      - ai:
          groups:
          - providers:
              - name: primary-model
                provider:
                  anthropic:
                    model: "claude-3-5-haiku-latest"
                routes:
                  "/v1/chat/completions": completions
                backendAuth:
                  key: "$ANTHROPIC_API_KEY"
              - name: second-model
                provider:
                  openAI:
                    model: "gpt-5"
                routes:
                  "/v1/chat/completions": completions
                backendAuth:
                  key: "$OPENAI_API_KEY"

```

2. Export your Anthropic API key and make it incorrect
```
export ANTHROPIC_API_KEY=fdsfdsfsd
```

3. Run the `curl`
```
curl -X POST http://localhost:3000/failover/ai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Testing failover"}]
  }'
```

You should see the output fail over to ChatGPT.
```
curl -X POST http://localhost:3000/failover/ai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Testing failover"}]
  }'
{"model":"gpt-5-2025-08-07","usage"
```
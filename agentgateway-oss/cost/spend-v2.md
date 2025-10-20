1. Export your Anthropic key

```
export ANTHROPIC_API_KEY=

```

2. Create the config to reach out to Anthropic (no MCP/tools)
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
              model: claude-sonnet-4-5
      policies:
        backendAuth:
          key: "$ANTHROPIC_API_KEY"
        localRateLimit:
          - maxTokens: 10
            tokensPerFill: 1
            fillInterval: 60s
            type: tokens
        cors:
          allowOrigins:
            - "*"
          allowHeaders:
            - "*"
```

3. Run the config
```
agentgateway -f agentgateway-oss/cost/spend.yaml
```

4. Open a new terminal and hit the Anthropic LLM

```
curl 'http://0.0.0.0:3000/' \ -H content-type:application/json -H x-api-key:$ANTHROPIC_API_KEY -H "anthropic-version: 2023-06-01" -d '{
  "model": "claude-sonnet-4-5",
  "messages": [
    {
      "role": "system",
      "content": "You are a skilled cloud-native network engineer."
    },
    {
      "role": "user",
      "content": "Write me a paragraph containing the best way to think about Istio Ambient Mesh"
    }
  ]
}' | jq
```

5. Run it again and you'll see a terminal output that looks something like `jq: parse error: Invalid numeric literal at line 1, column 5`, but if you go to the other terminal where `agentgateway` CLI is running, you'll see the below indicating the rate limit.

```
2025-10-20T14:20:43.299213Z     info    request gateway=bind/3000 listener=listener0 route_rule=route0/default route=route0 endpoint=api.anthropic.com:443 src.addr=127.0.0.1:60309 http.method=POST http.host=0.0.0.0 http.path=/ http.version=HTTP/1.1 http.status=429 error=rate limit exceeded duration=0ms
```
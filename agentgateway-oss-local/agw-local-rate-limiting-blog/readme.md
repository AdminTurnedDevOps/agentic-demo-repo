# Provider Rate Limiting Blog Demo

## Local Rate Limiting

1. Save the below as `local-rate-limit.yaml`

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
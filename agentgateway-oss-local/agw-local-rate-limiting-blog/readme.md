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

2. Run the following:
```
agentgateway -f local-rate-limiting.yaml
```

3. Open the agentgateway UI.

```
http://localhost:15000/ui
```
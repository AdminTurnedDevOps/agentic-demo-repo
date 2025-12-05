ToDo:
- Create a `Gateway` object for agentgateway
- Create a `Backend object with the `ai` type pointing to bedrock
```
spec:
  ai:
    llm:
      bedrock:
        model: eu.anthropic.claude-sonnet-4-5-20250929-v1:0
        region: eu-west-1
  type: AI
```

- Create a `ModelConfig` object where the `url` points to the agentgateway proxy
```
spec:
  apiKeySecret: secret-bedrock
  apiKeySecretKey: api-key
  model: bedrock-default
  openAI:
    baseUrl: http://agentgateway-enterprise.core-gloogateway.svc.cluster.local:8080/llm/bedrock/default
```

export AWS_API_KEY=

kubectl create secret generic kagent-bedrock -n kagent --from-literal AWS_API_KEY=$AWS_API_KEY

kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: bedrock-config
  namespace: kagent
spec:
  apiKeySecret: kagent-bedrock
  apiKeySecretKey: AWS_API_KEY
  model: anthropic.claude-3-5-sonnet-20241022-v2:01
  provider: Anthropic
  anthropic:
    baseUrl: "https://bedrock-runtime.us-west-2.amazonaws.com/anthropic/v1"
EOF

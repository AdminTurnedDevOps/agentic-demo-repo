Architecture:
1. agentgateway running in EKS in a cluster running in `us-east-1`
2. Bedrock running in `ca-central-1`

## Part 1: Bedrock Setup

### Important Notes

- Bedrock's `/openai/v1` endpoint only supports OpenAI-oss and Titan models, **not Claude**
- To use Claude via Bedrock, we use litellm's native Bedrock provider which uses boto3/AWS SDK
- This requires injecting AWS credentials as environment variables into the Agent deployment
- Newer Claude models require **inference profile IDs** (e.g., `us.anthropic.claude-...`) instead of direct model IDs

### Step 1: Get AWS Credentials

You'll need AWS credentials with Bedrock access. For temporary credentials:

```bash
aws sts get-session-token
```

Or if using IAM user with permanent credentials

```
export AWS_ACCESS_KEY_ID=
export AWS_SECRET_ACCESS_KEY=
export AWS_REGION=ca-central-1
```

### Step 2: Find Available Claude Models

List inference profiles for Claude in your region:

```bash
aws bedrock list-inference-profiles --region ca-central-1 \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'claude')].{id:inferenceProfileId,name:inferenceProfileName}" \
  --output table
```

Example output:
```
--------------------------------------------------------------------------------------------
|                                   ListInferenceProfiles                                  |
+---------------------------------------------------+--------------------------------------+
|                        id                         |                name                  |
+---------------------------------------------------+--------------------------------------+
|  us.anthropic.claude-haiku-4-5-20251001-v1:0      |  US Anthropic Claude Haiku 4.5       |
|  global.anthropic.claude-haiku-4-5-20251001-v1:0  |  Global Anthropic Claude Haiku 4.5   |
|  us.anthropic.claude-opus-4-5-20251101-v1:0       |  US Anthropic Claude Opus 4.5        |
|  global.anthropic.claude-opus-4-5-20251101-v1:0   |  GLOBAL Anthropic Claude Opus 4.5    |
|  us.anthropic.claude-sonnet-4-5-20250929-v1:0     |  US Anthropic Claude Sonnet 4.5      |
|  us.anthropic.claude-opus-4-6-v1                  |  US Anthropic Claude Opus 4.6        |
|  us.anthropic.claude-sonnet-4-6                   |  US Anthropic Claude Sonnet 4.6      |
|  global.anthropic.claude-sonnet-4-6               |  Global Anthropic Claude Sonnet 4.6  |
|  global.anthropic.claude-sonnet-4-5-20250929-v1:0 |  Global Claude Sonnet 4.5            |
|  global.anthropic.claude-opus-4-6-v1              |  Global Anthropic Claude Opus 4.6    |
+---------------------------------------------------+--------------------------------------+
```

### Step 3: Create Kubernetes Secret with AWS Credentials and OpenAI API key

```
export BEDROCK_API_KEY=
```

```
kubectl create secret generic kagent-bedrock-aws -n agentgateway-system \
  --from-literal=accessKey="" \
  --from-literal=secretKey=""
```

## Gateway Creation
```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: agentgateway-route-bedrock
  namespace: agentgateway-system
  labels:
    app: agentgateway-route-bedrock
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
    - name: http
      port: 8082
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: bedrock
  namespace: agentgateway-system
spec:
  ai:
    provider:
      bedrock:
        region: ca-central-1
        model: global.anthropic.claude-sonnet-4-6
  policies:
    auth:
      aws:
        secretRef:
          name: kagent-bedrock-aws
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: bedrock-route
  namespace: agentgateway-system
  labels:
    app: agentgateway-route-bedrock
spec:
  parentRefs:
    - name: agentgateway-route-bedrock
      namespace: agentgateway-system
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /anthropic
    filters:
    - type: URLRewrite
      urlRewrite:
        path:
          type: ReplaceFullPath
          replaceFullPath: /v1/chat/completions
    backendRefs:
    - name: bedrock
      namespace: agentgateway-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```

```
kubectl get gateway agentgateway-route-bedrock -n agentgateway-system
```

```
curl http://YOUR_GATEWAY_ALB_FROM_OUTPUT_ABOVE:8082/anthropic \
-H "Content-Type: application/json" \
-d '{
    "model": "global.anthropic.claude-sonnet-4-6",
    "max_tokens": 50,
    "messages": [
    {"role": "user", "content": "Say hello in one sentence."}
    ]
}'
```

Example output:

```
{"model":"global.anthropic.claude-sonnet-4-6","usage":{"prompt_tokens":13,"completion_tokens":18,"total_tokens":31,"prompt_tokens_details":{"cached_tokens":0},"cache_read_input_tokens":0,"cache_creation_input_tokens":0},"choices":[{"message":{"content":"Hello there! I hope you're having a wonderful day! 😊","role":"assistant"},"index":0,"finish_reason":"stop"}],"id":"bedrock-1773848525660","created":1773848525,"object":"chat.completion"}% 
```
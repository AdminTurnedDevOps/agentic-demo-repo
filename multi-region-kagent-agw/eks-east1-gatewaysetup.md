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
export AWS_ACCESS_KEY_ID=<your-access-key-id>
export AWS_SECRET_ACCESS_KEY=<your-secret-access-key>
export AWS_REGION=us-west-1
```

### Step 2: Find Available Claude Models

List inference profiles for Claude in your region:

```bash
aws bedrock list-inference-profiles --region us-west-2 \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'claude')].{id:inferenceProfileId,name:inferenceProfileName}" \
  --output table
```

Example output:
```
-------------------------------------------------------------------------------------------
|                                  ListInferenceProfiles                                  |
+---------------------------------------------------+-------------------------------------+
|                        id                         |                name                 |
+---------------------------------------------------+-------------------------------------+
|  us.anthropic.claude-sonnet-4-20250514-v1:0       |  US Claude Sonnet 4                 |
|  global.anthropic.claude-sonnet-4-5-20250929-v1:0 |  Global Claude Sonnet 4.5           |
|  us.anthropic.claude-haiku-4-5-20251001-v1:0      |  US Anthropic Claude Haiku 4.5      |
|  global.anthropic.claude-haiku-4-5-20251001-v1:0  |  Global Anthropic Claude Haiku 4.5  |
|  us.anthropic.claude-opus-4-5-20251101-v1:0       |  US Anthropic Claude Opus 4.5       |
|  global.anthropic.claude-opus-4-5-20251101-v1:0   |  GLOBAL Anthropic Claude Opus 4.5   |
|  us.anthropic.claude-sonnet-4-5-20250929-v1:0     |  US Anthropic Claude Sonnet 4.5     |
+---------------------------------------------------+-------------------------------------+
```

### Step 3: Create Kubernetes Secret with AWS Credentials and OpenAI API key

```
export BEDROCK_API_KEY=
```

```
kubectl create secret generic kagent-bedrock-aws -n agentgateway-system \
  --from-literal=AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID \
  --from-literal=AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY \
  --from-literal=AWS_SESSION_TOKEN=$AWS_SESSION_TOKEN \
  --from-literal=BEDROCK_API_KEY=$BEDROCK_API_KEY \
  --from-literal=OPENAI_API_KEY=$OPENAI_API_KEY
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
        region: BEDROCK_REGION
        model: BEDROCK_MODEL_OR_INFERENCE_PROFILE_ID
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
        value: /v1/chat/completions
    backendRefs:
    - name: bedrock
      namespace: agentgateway-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```

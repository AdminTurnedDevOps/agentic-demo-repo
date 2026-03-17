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

# Or if using IAM user with permanent credentials
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
kubectl create secret generic kagent-bedrock-aws -n kagent \
  --from-literal=AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID \
  --from-literal=AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY \
  --from-literal=AWS_SESSION_TOKEN=$AWS_SESSION_TOKEN \
  --from-literal=BEDROCK_API_KEY=$BEDROCK_API_KEY \
  --from-literal=OPENAI_API_KEY=$OPENAI_API_KEY
```

## Part 2: Agent Setup

1. Create a ModelConfig. This is pointing your LLM Gateway (which is agentgateway) and agentgateways `AgentgatewayBackend` is using Bedrock (in `us-central-1`) as a static host
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: llm-bedrock-model-config
  namespace: kagent
spec:
  apiKeySecret: anthropic-secret
  apiKeySecretKey: Authorization
  model: claude-3-5-haiku-latest
  provider: OpenAI
  openAI:
    baseUrl: http://52.159.230.96:8082/ai
EOF
```

2. Create an Agent that uses the `ModelConfig` above for calling out to Bedrock via Agentgateway within `us-central-1`.
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: testing-agentgateway
  namespace: kagent
spec:
  description: This agent can use a single tool to expand it's Kubernetes knowledge for troubleshooting and deployment
  type: Declarative
  declarative:
    modelConfig: llm-bedrock-model-config
    systemMessage: |-
      You're a friendly and helpful agent that uses the Kubernetes tool to help troubleshooting and deploy environments
EOF
```
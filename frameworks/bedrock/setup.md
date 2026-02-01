# AWS Bedrock with Claude Models in kagent

This guide shows how to configure kagent to use Claude models via AWS Bedrock.

## Important Notes

- Bedrock's `/openai/v1` endpoint only supports OpenAI-oss and Titan models, **not Claude**
- To use Claude via Bedrock, we use litellm's native Bedrock provider which uses boto3/AWS SDK
- This requires injecting AWS credentials as environment variables into the Agent deployment
- Newer Claude models require **inference profile IDs** (e.g., `us.anthropic.claude-...`) instead of direct model IDs

## Step 1: Get AWS Credentials

You'll need AWS credentials with Bedrock access. For temporary credentials:

```bash
aws sts get-session-token

# Or if using IAM user with permanent credentials
export AWS_ACCESS_KEY_ID=<your-access-key-id>
export AWS_SECRET_ACCESS_KEY=<your-secret-access-key>
export AWS_REGION=us-west-1
```

## Step 2: Find Available Claude Models

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

## Step 3: Create Kubernetes Secret with AWS Credentials and OpenAI API key

```
export OPENAI_API_KEY=

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

## Step 4: Create ModelConfig

Create a ModelConfig for OpenAI GPT-OSS (the only models Bedrock's OpenAI-compatible endpoint supports):

For OpenAI
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: bedrock-model-config
  namespace: kagent
spec:
  apiKeySecret: kagent-bedrock-aws
  apiKeySecretKey: BEDROCK_API_KEY
  model: openai.gpt-oss-20b-1:0
  provider: OpenAI
  openAI:
    baseUrl: "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1"
EOF
```

For Bedrock
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: bedrock-model-config
  namespace: kagent
spec:
  apiKeySecret: kagent-bedrock-aws
  apiKeySecretKey: BEDROCK_API_KEY
  model: claude-opus-4-20250514-v1:0
  provider: Bedrock
  bedrock:
    baseUrl: "us.anthropic.claude-opus-4-20250514-v1:0"
EOF
```

Verify the ModelConfig is accepted:

```bash
kubectl get modelconfig bedrock-model-config -n kagent -o jsonpath='{.status.conditions}' | jq
```

Expected output:
```json
[
  {
    "lastTransitionTime": "...",
    "message": "",
    "reason": "ModelConfigReconciled",
    "status": "True",
    "type": "Accepted"
  }
]
```

## Step 5: Create Agent with AWS Credentials

The key is using `spec.declarative.deployment.env` to inject AWS credentials that litellm's Bedrock provider needs:

```bash
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: bedrock-agent-test
  namespace: kagent
spec:
  description: Kubernetes troubleshooting agent powered by Claude via Bedrock
  type: Declarative
  declarative:
    modelConfig: bedrock-model-config
    deployment:
      env:
        - name: AWS_ACCESS_KEY_ID
          valueFrom:
            secretKeyRef:
              name: kagent-bedrock-aws
              key: AWS_ACCESS_KEY_ID
        - name: AWS_SECRET_ACCESS_KEY
          valueFrom:
            secretKeyRef:
              name: kagent-bedrock-aws
              key: AWS_SECRET_ACCESS_KEY
        - name: AWS_SESSION_TOKEN
          valueFrom:
            secretKeyRef:
              name: kagent-bedrock-aws
              key: AWS_SESSION_TOKEN
    systemMessage: |
      You're a friendly and helpful agent that uses Kubernetes tools to help with troubleshooting and deployments.

      # Instructions
      - If user question is unclear, ask for clarification before running any tools
      - Always be helpful and friendly
      - If you don't know how to answer the question, respond with "Sorry, I don't know how to answer that"

      # Response format
      - ALWAYS format your response as Markdown
      - Include a summary of actions you took and an explanation of the result
    tools:
      - type: McpServer
        mcpServer:
          name: kagent-tool-server
          kind: RemoteMCPServer
          toolNames:
          - k8s_get_available_api_resources
          - k8s_get_cluster_configuration
          - k8s_get_events
          - k8s_get_pod_logs
          - k8s_get_resource_yaml
          - k8s_get_resources
          - k8s_check_service_connectivity
EOF
```

## Step 6: Verify Agent is Ready

```bash
kubectl get agent bedrock-agent-test -n kagent -o jsonpath='{.status.conditions}' | jq
```

Both conditions should show `status: "True"`:
- `type: Accepted` - Agent spec is valid
- `type: Ready` - Deployment is running


kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: bedrock-model-config
  namespace: kagent
spec:
  apiKeySecret: kagent-bedrock
  apiKeySecretKey: AWS_API_KEY
  model: amazon.nova-2-sonic-v1:0
  provider: OpenAI
  openAI:
    baseUrl: "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1"
EOF
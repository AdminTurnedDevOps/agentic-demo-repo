# AgentCore Runtime agent

A Strands agent that Agentregistry deploys to **AgentCore Runtime**. It is a real Bedrock chat agent with two local tools, `current_time` and `calculate`.

The container speaks the contract Agentregistry's chat UI already uses:

- `POST /invocations` with `{"prompt":"<user text>"}`
- response `{"output":"<reply text>"}`
- `GET /ping`

Nested `{"input":{"prompt":"..."}}` is also accepted.

## What you need before deploy

- An agentregistry `Runtime` configured for AWS. You can see how to set up the AWS runtime [here](https://github.com/solo-io/field-agentic-labs/blob/main/agentregistry-enterprise/010-aws-bedrock-runtime.md#iam-permissions)
- Amazon Bedrock model access in the runtime region for `global.anthropic.claude-sonnet-4-6` (override with `BEDROCK_MODEL_ID`).
- The AgentCore **execution role** that agentregistry creates already allows `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`. You do not put an Anthropic API key on this agent.
- Docker buildx and an ECR repository your AgentCore runtime can pull.

## Build and push

AgentCore requires a Linux ARM64 image.

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export ECR_REPOSITORY=agentregistry/runtime-agent
export IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}:0.1.0"

aws ecr describe-repositories --region "$AWS_REGION" \
  --repository-names "$ECR_REPOSITORY" >/dev/null 2>&1 || \
  aws ecr create-repository --region "$AWS_REGION" \
    --repository-name "$ECR_REPOSITORY"

aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin \
    "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

docker buildx build --platform linux/arm64 -t "$IMAGE_URI" --push .
```

Put that image URI into `agent.yaml` (`spec.source.image`), then:

```bash
arctl apply -f agent.yaml
arctl apply -f deploy.yaml
```

`deploy.yaml` targets `Runtime` `AWS`. Change `runtimeRef.name` if yours is different.

Chat from the AgentRegistry instance page. Ask "what time is it?" or "what is (12 + 8) / 4" to exercise the tools.

A warm AgentCore session keeps the Strands message history in memory. A new session, or a cold microVM, starts a new conversation.

## Local check

```bash
uv sync
uv run pytest
```

`/invocations` will call Bedrock if you run uvicorn locally with AWS credentials that can `bedrock:InvokeModel`.

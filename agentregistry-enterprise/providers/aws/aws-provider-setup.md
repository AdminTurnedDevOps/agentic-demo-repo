## 1. Set Up the AWS Provider

The AWS provider setup is a two-step process: create an IAM role in your AWS account, then register it with AgentRegistry.

### Step 1: Generate the CloudFormation Template

```bash
arctl provider setup aws --aws-account-id <YOUR_AWS_ACCOUNT_ID> > /tmp/agentregistry-cf.yaml
```

> **Note**: This command requires authentication. If running from the CLI, log in first with `arctl user login`. Alternatively, you can pass `--registry-token <token>`.

This outputs a CloudFormation template that creates an IAM role with permissions for:
- Bedrock AgentCore (create/manage agent runtimes)
- IAM (create execution roles for agents)
- S3 (upload agent code artifacts)
- CloudWatch Logs (agent logging)
- AppConfig (agentgateway configuration)
- Cognito (optional agent auth)
- EC2 (optional managed agentgateway instances)

Note the **External ID** and **Role Name** printed at the bottom of the template.

### Step 2: Deploy the CloudFormation Stack

```bash
aws cloudformation create-stack \
  --stack-name agentregistry-access-role \
  --template-body file:///tmp/agentregistry-cf.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

Wait for completion:

```bash
aws cloudformation wait stack-create-complete \
  --stack-name agentregistry-access-role \
  --region us-east-1
```

Retrieve the outputs:

```bash
aws cloudformation describe-stacks \
  --stack-name agentregistry-access-role \
  --region us-east-1 \
  --query 'Stacks[0].Outputs'
```

Save the `RoleArn` and `ExternalId` from the output.

### Step 3: Register the AWS Provider

Create the provider manifest:

```bash
export AWS_ROLE_ARN="<RoleArn from CloudFormation output>"
export AWS_EXTERNAL_ID="<ExternalId from CloudFormation output>"
export AWS_REGION="us-east-1"

cat > /tmp/aws-provider.yaml <<EOF
apiVersion: ar.dev/v1alpha1
kind: Runtime
metadata:
  name: AWS
spec:
  platform: aws
  config:
    roleArn: "${AWS_ROLE_ARN}"
    externalId: "${AWS_EXTERNAL_ID}"
    region: "${AWS_REGION}"
EOF
```

Apply it:

```bash
arctl apply -f /tmp/aws-provider.yaml
```

> **Note**: This requires an authenticated session. You can authenticate via:
> - `arctl user login` (device-code flow, opens browser)
> - `--registry-token <token>` flag
> - The AgentRegistry UI (navigate to Providers and add the AWS provider there)

## 2. Deploy an Agent to AWS

Once the AWS provider is registered, you can deploy agents to AWS Bedrock AgentCore.

### 1. Use the A2A-Compatible Demo Agent

AgentRegistry Enterprise deploys AWS agents through the A2A/kagent-adk AgentCore path. Use the `demochatbot-a2a/` example in this repo; it includes the ADK-style agent package, A2A agent card, registry manifest, and deployment manifest:

- `demochatbot/agent.py` — ADK-compatible agent implementation
- `demochatbot/agent-card.json` — A2A agent card consumed by the generated AgentCore wrapper
- `agent.yaml` — registers the agent in AgentRegistry
- `deploy.yaml` — deploys it to AWS via the registered provider

The agent manifest (`demochatbot-a2a/agent.yaml`):

```yaml
apiVersion: ar.dev/v1alpha1
kind: Agent
metadata:
  name: demochatbot
  version: "1.0.4"
spec:
  description: "A deterministic A2A/ADK-compatible chatbot for AWS Bedrock AgentCore"
  source:
    repository:
      url: "https://github.com/AdminTurnedDevOps/agentic-demo-repo"
      subfolder: "agentregistry-enterprise/demochatbot-a2a"
```

The deployment manifest (`demochatbot-a2a/deploy.yaml`):

```yaml
apiVersion: ar.dev/v1alpha1
kind: Deployment
metadata:
  name: demochatbot
spec:
  providerRef:
    kind: Provider
    name: AWS
  targetRef:
    kind: Agent
    name: demochatbot
    version: "1.0.4"
```

### Register and Deploy

```bash
cd demochatbot-a2a/

# Register the agent in the registry
arctl apply -f agent.yaml

# Deploy it to AWS Bedrock AgentCore
arctl apply -f deploy.yaml
```

### Check Deployment Status

```bash
arctl get deployments
```

The deployment will go through `deploying` -> `deployed` (or `failed` with an error message). To inspect the deployment record:

```bash
arctl get deployment demochatbot -o yaml
```

Runtime logs are written in AWS CloudWatch under the Bedrock AgentCore runtime log group, which follows the pattern `/aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT`.

### 2. Register an MCP Server

You can also register MCP servers in AgentRegistry. A minimal stdio MCP server is included in this repo under `demo-mcp/`.

### MCP Server Files

- `server.py` — a zero-dependency Python MCP server with 3 tools: `get_time`, `random_number`, `reverse_string`
- `mcpserver.yaml` — registers the MCP server in AgentRegistry

The MCP server manifest (`mcpserver.yaml`):

```yaml
apiVersion: ar.dev/v1alpha1
kind: MCPServer
metadata:
  name: demo-tools
  version: "1.0.0"
spec:
  description: "A minimal MCP server with simple tools: get_time, random_number, reverse_string"
  transport: stdio
  command: "python3 server.py"
  source:
    repository:
      url: "https://github.com/AdminTurnedDevOps/agentic-demo-repo"
      subfolder: "agentregistry-enterprise/demo-mcp"
  tools:
    - name: get_time
      description: "Get the current UTC time"
    - name: random_number
      description: "Generate a random number between min and max"
    - name: reverse_string
      description: "Reverse a string"
```

### Register the MCP Server

```bash
cd demo-mcp/
arctl apply -f mcpserver.yaml
```

### Verify

```bash
arctl get mcps
```

You should see:

```
NAME         VERSION   DESCRIPTION
demo-tools   1.0.0     A minimal MCP server with simple tools: get_time, random_...
```

## Updating AWS Credentials

If your AWS credentials change (e.g., key rotation), update the Helm values file and run:

```bash
helm upgrade agentregistry-enterprise \
  oci://us-docker.pkg.dev/solo-public/agentregistry-enterprise/helm/agentregistry-enterprise \
  --version 2026.5.3 \
  --namespace agentregistry-system \
  -f /tmp/are-values.yaml \
  --wait --timeout 5m
```

The server pod will roll automatically when the AWS secret changes.

## AccessPolicy Examples for Entra Groups

Because Entra emits group **object IDs** (GUIDs) in the `groups` claim, your AccessPolicies reference those GUIDs as the principal. For example:

```yaml
apiVersion: ar.dev/v1alpha1
kind: AccessPolicy
metadata:
  name: readers-policy
spec:
  principals:
    - "a1b2c3d4-e5f6-7890-abcd-000000000001"   # Object ID of are-readers group
  rules:
    - scopes: ["registry"]
      verbs: ["read"]
---
apiVersion: ar.dev/v1alpha1
kind: AccessPolicy
metadata:
  name: writers-policy
spec:
  principals:
    - "a1b2c3d4-e5f6-7890-abcd-000000000002"   # Object ID of are-writers group
  rules:
    - scopes: ["registry"]
      verbs: ["read", "publish", "edit", "deploy"]
```

Apply them:

```bash
arctl apply -f access-policies.yaml
```

> **Tip**: Use `arctl whoami` to see your mapped roles (group object IDs) and verify they match your AccessPolicy principals.

## Alternative: Use App Roles Instead of Groups

If you prefer human-readable role names or need to avoid the groups overage limit, you can use Entra **app roles** instead of security groups.

### Define App Roles

**Portal**: On the `are-backend` app registration, go to **App roles** > **Create app role** for each role below. Then assign users/groups via **Enterprise applications** > `are-backend` > **Users and groups** > **Add user/group**.

**CLI**:

```bash
# Define app roles on the are-backend app registration
ADMIN_ROLE_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
READER_ROLE_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
WRITER_ROLE_ID=$(python3 -c "import uuid; print(uuid.uuid4())")

az ad app update --id "$ARE_BACKEND_CLIENT_ID" \
  --app-roles "[
    {\"id\":\"$ADMIN_ROLE_ID\",\"displayName\":\"Admin\",\"description\":\"Full access\",\"value\":\"admin\",\"isEnabled\":true,\"allowedMemberTypes\":[\"User\"]},
    {\"id\":\"$READER_ROLE_ID\",\"displayName\":\"Reader\",\"description\":\"Read-only access\",\"value\":\"reader\",\"isEnabled\":true,\"allowedMemberTypes\":[\"User\"]},
    {\"id\":\"$WRITER_ROLE_ID\",\"displayName\":\"Writer\",\"description\":\"Read and write access\",\"value\":\"writer\",\"isEnabled\":true,\"allowedMemberTypes\":[\"User\"]}
  ]"

# Assign the current user to the admin role
ARE_BACKEND_SP_ID=$(az ad sp show --id "$ARE_BACKEND_CLIENT_ID" --query id -o tsv)
MY_USER_ID=$(az ad signed-in-user show --query id -o tsv)

az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$ARE_BACKEND_SP_ID/appRoleAssignments" \
  --body "{\"principalId\":\"$MY_USER_ID\",\"resourceId\":\"$ARE_BACKEND_SP_ID\",\"appRoleId\":\"$ADMIN_ROLE_ID\"}"
```

| Display Name | Value | Allowed member types |
|-------------|-------|---------------------|
| Admin | `admin` | Users/Groups |
| Reader | `reader` | Users/Groups |
| Writer | `writer` | Users/Groups |

### Update Helm Values

Change the `roleClaim` to `roles` and `superuserRole` to the app role value:

```yaml
oidc:
  issuer: "https://login.microsoftonline.com/<TENANT_ID>/v2.0"
  clientId: "<ARE_BACKEND_CLIENT_ID>"
  publicClientId: "<ARE_UI_CLIENT_ID>"
  clientSecret: "<ARE_BACKEND_CLIENT_SECRET>"
  roleClaim: "roles"              # Use Entra app roles instead of groups
  superuserRole: "admin"          # Human-readable app role value
  additionalScopes: "offline_access api://<ARE_BACKEND_CLIENT_ID>/agentregistry"
  insecureSkipVerify: false
```

With app roles, the `roles` claim contains human-readable strings (e.g., `["admin", "reader"]`), and your AccessPolicy principals use those same strings:

```yaml
apiVersion: ar.dev/v1alpha1
kind: AccessPolicy
metadata:
  name: readers-policy
spec:
  principals:
    - "reader"
  rules:
    - scopes: ["registry"]
      verbs: ["read"]
```
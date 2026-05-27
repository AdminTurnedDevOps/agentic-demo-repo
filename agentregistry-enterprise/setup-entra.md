# Agentregistry Enterprise - Setup Guide (Microsoft Entra ID)

This guide walks through installing AgentRegistry Enterprise on a Kubernetes cluster with Microsoft Entra ID (Azure AD) OIDC authentication and AWS Bedrock AgentCore integration.

## Prerequisites

- A running Kubernetes cluster (GKE, EKS, AKS, or Kind)
- `kubectl` configured and pointing at your cluster
- `helm` v3 installed
- `aws` CLI installed (for AWS provider setup)
- `az` CLI installed and authenticated (`az login`)
- A Microsoft Entra ID (Azure AD) tenant with admin access to create app registrations
- AWS IAM credentials (long-lived IAM user recommended over temporary session tokens)

## 1. Install the Enterprise arctl CLI

```bash
curl -sSL https://storage.googleapis.com/agentregistry-enterprise/install.sh | ARCTL_VERSION=v2026.5.3 sh
export PATH=$HOME/.arctl/bin:$PATH
```

Verify the installation:

```bash
arctl version --json
```

## 2. Create the Namespace

```bash
kubectl create namespace agentregistry-system
```

## 3. Register Entra ID App Registrations

You need three app registrations in Entra: one confidential backend client for server-side token validation, one public client for the CLI (device-code flow), and one public client for the browser UI (SPA).

Each step below shows both the **Azure Portal** instructions and the equivalent **`az` CLI** commands. You only need to follow one approach.

### Collect Your Tenant ID

**Portal**: Go to [Microsoft Entra ID](https://portal.azure.com) > **Overview** > copy the **Tenant ID**.

**CLI**:

```bash
export TENANT_ID=$(az account show --query tenantId -o tsv)
echo "Tenant ID: $TENANT_ID"
```

### 3a. Backend App Registration (are-backend)

This is a confidential client used by the AgentRegistry Enterprise server to validate tokens.

**Portal**:
1. Go to [App registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade) > **New registration**
2. Name: `are-backend`, Single tenant, no redirect URI > **Register**
3. Note the **Application (client) ID**
4. **Certificates & secrets** > **New client secret** > copy the **Value**
5. **Expose an API** > Set Application ID URI > **Add a scope** named `agentregistry` (Admins and users, enabled)

**CLI**:

```bash
# Create the app registration
ARE_BACKEND_CLIENT_ID=$(az ad app create \
  --display-name "are-backend" \
  --sign-in-audience "AzureADMyOrg" \
  --query appId -o tsv)
echo "ARE_BACKEND_CLIENT_ID: $ARE_BACKEND_CLIENT_ID"

# Create a client secret (1 year expiry)
ARE_BACKEND_CLIENT_SECRET=$(az ad app credential reset \
  --id "$ARE_BACKEND_CLIENT_ID" \
  --display-name "agentregistry-enterprise" \
  --years 1 \
  --query password -o tsv)
echo "ARE_BACKEND_CLIENT_SECRET: $ARE_BACKEND_CLIENT_SECRET"

# Set the Application ID URI
az ad app update --id "$ARE_BACKEND_CLIENT_ID" \
  --identifier-uris "api://$ARE_BACKEND_CLIENT_ID"

# Expose a delegated scope (agentregistry)
# Generate a stable GUID for the scope
SCOPE_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
az ad app update --id "$ARE_BACKEND_CLIENT_ID" \
  --set "api={\"oauth2PermissionScopes\":[{\"id\":\"$SCOPE_ID\",\"adminConsentDisplayName\":\"Access AgentRegistry Enterprise\",\"adminConsentDescription\":\"Allows the app to access AgentRegistry Enterprise on behalf of the signed-in user\",\"isEnabled\":true,\"type\":\"User\",\"userConsentDisplayName\":\"Access AgentRegistry Enterprise\",\"userConsentDescription\":\"Allows the app to access AgentRegistry Enterprise on behalf of the signed-in user\",\"value\":\"agentregistry\"}]}"

# Ensure a service principal exists for the backend app
az ad sp create --id "$ARE_BACKEND_CLIENT_ID" 2>/dev/null || true

# Set accessTokenAcceptedVersion to 2 so tokens use the v2.0 issuer
az ad app update --id "$ARE_BACKEND_CLIENT_ID" \
  --set "api.requestedAccessTokenVersion=2"
```

### 3b. CLI App Registration (are-cli)

This is a public client for the `arctl` CLI. It uses the OAuth 2.0 device authorization grant so you can authenticate from a terminal.

**Portal**:
1. **New registration** > Name: `are-cli`, Single tenant, Redirect URI: Public client `http://localhost` > **Register**
2. **Authentication** > **Allow public client flows** > **Yes** > **Save**
3. **API permissions** > **Add a permission** > **My APIs** > `are-backend` > select `agentregistry` > **Add permissions**
4. Click **Grant admin consent**

**CLI**:

```bash
# Create the app registration as a public client with device-code redirect
ARE_CLI_CLIENT_ID=$(az ad app create \
  --display-name "are-cli" \
  --sign-in-audience "AzureADMyOrg" \
  --public-client-redirect-uris "http://localhost" \
  --is-fallback-public-client true \
  --query appId -o tsv)
echo "ARE_CLI_CLIENT_ID: $ARE_CLI_CLIENT_ID"

# Add API permission for the are-backend scope
az ad app permission add \
  --id "$ARE_CLI_CLIENT_ID" \
  --api "$ARE_BACKEND_CLIENT_ID" \
  --api-permissions "$SCOPE_ID=Scope"

# Grant admin consent
az ad app permission admin-consent --id "$ARE_CLI_CLIENT_ID"
```

### 3c. UI App Registration (are-ui)

This is a public SPA client for the AgentRegistry Enterprise web UI. The redirect URI is set after deployment once the external IP is known (Step 7).

**Portal**:
1. **New registration** > Name: `are-ui`, Single tenant, Redirect URI: SPA (leave blank for now) > **Register**
2. **API permissions** > **Add a permission** > **My APIs** > `are-backend` > select `agentregistry` > **Add permissions**
3. Click **Grant admin consent**

**CLI**:

```bash
# Create the app registration (SPA redirect URI added after deployment)
ARE_UI_CLIENT_ID=$(az ad app create \
  --display-name "are-ui" \
  --sign-in-audience "AzureADMyOrg" \
  --query appId -o tsv)
echo "ARE_UI_CLIENT_ID: $ARE_UI_CLIENT_ID"

# Add API permission for the are-backend scope
az ad app permission add \
  --id "$ARE_UI_CLIENT_ID" \
  --api "$ARE_BACKEND_CLIENT_ID" \
  --api-permissions "$SCOPE_ID=Scope"

# Grant admin consent
az ad app permission admin-consent --id "$ARE_UI_CLIENT_ID"
```

> **Note**: After deployment (Step 7), you will expose the UI over HTTPS via a Gateway with a self-signed certificate, then add the HTTPS redirect URI:
> ```bash
> az ad app update --id "$ARE_UI_CLIENT_ID" \
>   --set "spa={\"redirectUris\":[\"https://<ARE_HTTPS_IP>/callback\"]}"
> ```
> Entra requires HTTPS for SPA redirect URIs on non-localhost addresses.

## 4. Configure Entra ID Groups

AgentRegistry Enterprise maps OIDC token claims to roles for RBAC. With Entra ID, the recommended approach is to use security groups and emit group memberships in the `groups` claim.

### Create Security Groups

**Portal**: Go to **Microsoft Entra ID** > **Groups** > **New group** and create each group below. Add users to the appropriate groups.

**CLI**:

```bash
# Get the current user's object ID (to add as a member/owner)
MY_USER_ID=$(az ad signed-in-user show --query id -o tsv)

# Create security groups
GROUP_ADMINS=$(az ad group create \
  --display-name "are-admins" \
  --mail-nickname "are-admins" \
  --description "AgentRegistry Enterprise superuser access" \
  --query id -o tsv)
echo "GROUP_ADMINS: $GROUP_ADMINS"

GROUP_READERS=$(az ad group create \
  --display-name "are-readers" \
  --mail-nickname "are-readers" \
  --description "AgentRegistry Enterprise read-only access" \
  --query id -o tsv)
echo "GROUP_READERS: $GROUP_READERS"

GROUP_WRITERS=$(az ad group create \
  --display-name "are-writers" \
  --mail-nickname "are-writers" \
  --description "AgentRegistry Enterprise read + write access" \
  --query id -o tsv)
echo "GROUP_WRITERS: $GROUP_WRITERS"

# Add the current user to the admins group
az ad group member add --group "$GROUP_ADMINS" --member-id "$MY_USER_ID"
```

| Group Name | Type | Purpose |
|------------|------|---------|
| `are-admins` | Security | Superuser access (full control) |
| `are-readers` | Security | Read-only access |
| `are-writers` | Security | Read + write access |

To add other users to groups:

```bash
# Look up a user by UPN or email
USER_ID=$(az ad user show --id "user@example.com" --query id -o tsv)
az ad group member add --group "$GROUP_READERS" --member-id "$USER_ID"
```

### Configure Token Group Claims

Entra must be configured to emit the `groups` claim in tokens. This is done via the `groupMembershipClaims` property on each app registration and by adding an `optionalClaims` entry.

**Portal**: For each app registration (`are-backend`, `are-cli`, `are-ui`):
1. **Token configuration** > **Add groups claim**
2. Select **Security groups**
3. For **ID** and **Access** tokens: select **Group ID**
4. Click **Add**

**CLI**:

```bash
# Enable security group claims on all three app registrations
for APP_ID in "$ARE_BACKEND_CLIENT_ID" "$ARE_CLI_CLIENT_ID" "$ARE_UI_CLIENT_ID"; do
  az ad app update --id "$APP_ID" \
    --set "groupMembershipClaims=\"SecurityGroup\"" \
    --set "optionalClaims={\"accessToken\":[{\"name\":\"groups\",\"source\":null,\"essential\":false,\"additionalProperties\":[]}],\"idToken\":[{\"name\":\"groups\",\"source\":null,\"essential\":false,\"additionalProperties\":[]}]}"
  echo "Configured group claims for app: $APP_ID"
done
```

This causes Entra to include the `groups` claim (an array of group object IDs) in issued tokens.

> **Important**: Entra emits group **object IDs** (GUIDs), not human-readable names. Your AccessPolicies must reference these GUIDs. See [Helm Values](#5-prepare-the-helm-values-file) and [AccessPolicy Examples](#accesspolicy-examples-for-entra-groups) below.

> **Groups overage warning**: If a user belongs to more than ~200 groups, Entra omits the `groups` claim entirely and returns a `_claim_names`/`_claim_sources` structure pointing to the Microsoft Graph API. AgentRegistry Enterprise does not resolve the Graph overage endpoint. Limit group membership or use Entra **app roles** instead (see [Alternative: Use App Roles Instead of Groups](#alternative-use-app-roles-instead-of-groups)).

## 5. Prepare the Helm Values File

Create a values file. **Do not commit this file** — it contains secrets.

```bash
cat > /tmp/are-values.yaml <<EOF
image:
  tag: v2026.5.3

# Git credentials for private repositories. Leave empty unless needed.
global:
  git:
    username: ""
    token: ""
    secretRef:
      name: ""
      key: GIT_TOKEN
      usernameKey: ""

service:
  type: LoadBalancer

# OIDC / Microsoft Entra ID
oidc:
  issuer: "https://login.microsoftonline.com/${TENANT_ID}/v2.0"
  clientId: "${ARE_BACKEND_CLIENT_ID}"
  publicClientId: "${ARE_UI_CLIENT_ID}"
  clientSecret: "${ARE_BACKEND_CLIENT_SECRET}"
  roleClaim: "groups"                         # Entra emits group object IDs here
  superuserRole: "${GROUP_ADMINS}"            # The Entra group object ID for admins
  additionalScopes: "offline_access api://${ARE_BACKEND_CLIENT_ID}/agentregistry"
  insecureSkipVerify: false

# AWS credentials (long-lived IAM user keys recommended)
aws:
  enabled: true
  accessKeyId: "<AWS_ACCESS_KEY_ID>"
  secretAccessKey: "<AWS_SECRET_ACCESS_KEY>"
  sessionToken: ""                            # Leave empty for IAM user keys
  region: "us-east-1"

# Bundled PostgreSQL (dev/eval only)
database:
  postgres:
    bundled:
      enabled: true

# ClickHouse (observability)
clickhouse:
  enabled: true

# OTel Collector
telemetry:
  enabled: true

# Enable tracing — send server traces to the bundled OTel Collector
extraEnvVars:
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://agentregistry-enterprise-telemetry-collector:4317"
  - name: OTEL_SERVICE_NAME
    value: "agentregistry-enterprise"
EOF
```

### Important Notes on Values

**OIDC `issuer`**: Use the Entra v2.0 endpoint: `https://login.microsoftonline.com/<TENANT_ID>/v2.0`. This is the issuer that appears in the `iss` claim of v2.0 tokens. Do **not** use the v1.0 endpoint (`https://sts.windows.net/<TENANT_ID>/`) — the OIDC discovery document at the v2.0 URL covers both.

**OIDC `roleClaim`**: Set to `groups`. Entra emits group memberships as an array of object IDs in the `groups` claim. If you use app roles instead, set this to `roles`.

**OIDC `superuserRole`**: This must be the **object ID** of your admin security group (e.g., `a1b2c3d4-e5f6-7890-abcd-ef1234567890`), not the display name. The server compares this value against the entries in the `groups` claim.

**OIDC `additionalScopes`**: Include `offline_access` (for refresh tokens) and the backend API scope you exposed (e.g., `api://<ARE_BACKEND_CLIENT_ID>/agentregistry`). Without the API scope, the access token audience may default to Microsoft Graph, which is not what the server expects.

**AWS Credentials**: Use long-lived IAM user credentials rather than temporary session tokens (STS). Session tokens expire (typically 1-12 hours) and require frequent Helm upgrades to rotate. If you must use temporary credentials, include the `sessionToken` field.

## 6. Install the Helm Chart

```bash
helm upgrade --install agentregistry-enterprise \
  oci://us-docker.pkg.dev/solo-public/agentregistry-enterprise/helm/agentregistry-enterprise \
  --version 2026.5.3 \
  --namespace agentregistry-system \
  -f /tmp/are-values.yaml \
  --wait --timeout 5m
```

## 7. Verify the Installation

Check that all pods are running:

```bash
kubectl get pods -n agentregistry-system
```

Expected output (all 1/1 Running):

```
NAME                                                            READY   STATUS
agentregistry-enterprise-<hash>                                 1/1     Running
agentregistry-enterprise-clickhouse-shard0-0                    1/1     Running
agentregistry-enterprise-postgresql-<hash>                      1/1     Running
agentregistry-enterprise-telemetry-collector-<hash>             1/1     Running
```

Check the services:

```bash
kubectl get svc -n agentregistry-system
```

The `agentregistry-enterprise` service will have an external IP (LoadBalancer) with ports:
- **8080** — HTTP (UI + API)
- **21212** — Agent Gateway gRPC
- **31313** — MCP server

Check the server logs for any errors:

```bash
kubectl logs -n agentregistry-system deployment/agentregistry-enterprise --tail=30
```

You should see:
- `all migrations applied successfully` (both OSS and enterprise migrations)
- `HTTP server starting` on `:8080`
- `MCP HTTP server starting` on `:31313`
- `using OIDC authentication`

Get the external IP for accessing the UI:

```bash
export AR_IP=$(kubectl get svc agentregistry-enterprise -n agentregistry-system -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "UI: http://$AR_IP:8080"
echo "API docs: http://$AR_IP:8080/docs"
```

### Expose the UI over HTTPS for Entra SPA Login

Microsoft Entra requires HTTPS for SPA redirect URIs on non-localhost addresses. The `agentregistry-enterprise` Service serves HTTP only, so you need to terminate TLS in front of it. The simplest approach is to create a Kubernetes Gateway with an HTTPS listener using a self-signed certificate and route traffic to the AgentRegistry service.

This requires the `enterprise-agentgateway` GatewayClass (or Istio, or any Gateway API-compatible controller with TLS support) to be installed on your cluster.

#### Create the HTTPS Gateway

```bash
kubectl apply -f - <<'EOF'
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: are-https-gateway
  namespace: agentregistry-system
  labels:
    app: agentregistry-enterprise
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
    - name: https
      port: 443
      protocol: HTTPS
      tls:
        mode: Terminate
        certificateRefs:
          - group: ""
            kind: Secret
            name: are-https-tls
      allowedRoutes:
        namespaces:
          from: Same
EOF
```

Wait for the Gateway to get an external IP:

```bash
kubectl get gateway are-https-gateway -n agentregistry-system -w
```

Once it shows an address:

```bash
export ARE_HTTPS_IP=$(kubectl get gateway are-https-gateway -n agentregistry-system -o jsonpath='{.status.addresses[0].value}')
echo "HTTPS Gateway IP: $ARE_HTTPS_IP"
```

#### Generate a Self-Signed Certificate

```bash
openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
  -keyout /tmp/are-https.key \
  -out /tmp/are-https.crt \
  -subj "/CN=${ARE_HTTPS_IP}" \
  -addext "subjectAltName = IP:${ARE_HTTPS_IP}"

kubectl create secret tls are-https-tls \
  -n agentregistry-system \
  --cert=/tmp/are-https.crt \
  --key=/tmp/are-https.key \
  --dry-run=client -o yaml | kubectl apply -f -
```

#### Create the HTTPRoute

Route HTTPS traffic from the Gateway to the AgentRegistry Enterprise service:

```bash
kubectl apply -f - <<'EOF'
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: are-https-route
  namespace: agentregistry-system
  labels:
    app: agentregistry-enterprise
spec:
  parentRefs:
    - name: are-https-gateway
      namespace: agentregistry-system
      sectionName: https
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - group: ""
          kind: Service
          name: agentregistry-enterprise
          port: 8080
EOF
```

#### Verify HTTPS

```bash
curl -k -I "https://${ARE_HTTPS_IP}/"
curl -k -I "https://${ARE_HTTPS_IP}/callback"
```

Both should return `HTTP/2 200`.

#### Update the UI App Registration Redirect URI

Now register the HTTPS callback URI on the `are-ui` app registration.

**Portal**: Go to `are-ui` > **Authentication** > **Single-page application** > Add `https://<ARE_HTTPS_IP>/callback` > **Save**.

**CLI**:

```bash
az ad app update --id "$ARE_UI_CLIENT_ID" \
  --set "spa={\"redirectUris\":[\"https://${ARE_HTTPS_IP}/callback\"]}"
```

The UI is now accessible at `https://<ARE_HTTPS_IP>`. Your browser will warn about the self-signed certificate — accept it to proceed. For production, use a proper CA-signed certificate or cert-manager.

## 8. Configure and Authenticate the arctl CLI

Point the CLI at the AgentRegistry Enterprise service. The CLI does not support `--insecure-skip-verify` for registry API calls, so use the direct HTTP service rather than the HTTPS gateway (which uses a self-signed certificate):

```bash
export ARCTL_API_BASE_URL=http://$AR_IP:8080
```

> **Note**: The HTTPS gateway (`https://$ARE_HTTPS_IP`) is for browser-based Entra SPA login only. The CLI connects directly to the service over HTTP. For production with a CA-signed certificate, you can point the CLI at the HTTPS endpoint instead.

Verify connectivity:

```bash
arctl version --json
```

The output should show both `arctl_version` and `server_version`.

### Log In

> **Known limitation**: The current `arctl user login` command does not pass a `scope` parameter in the device authorization request. Keycloak does not require this, but Microsoft Entra does — you will see `AADSTS900144: The request body must contain the following parameter: 'scope'`. Until a future `arctl` release adds a `--scope` flag, use the manual device-code flow below to obtain a token and pass it to `arctl` via `--registry-token` or the `ARCTL_API_TOKEN` environment variable.

#### Manual Device-Code Login

This flow uses three variables from the app registration steps above. Confirm they are set in your shell:

```bash
echo "TENANT_ID:            $TENANT_ID"
echo "ARE_CLI_CLIENT_ID:    $ARE_CLI_CLIENT_ID"
echo "ARE_BACKEND_CLIENT_ID: $ARE_BACKEND_CLIENT_ID"
```

If any are empty, re-export them (the values were printed during Steps 3a-3b).

Initiate the Entra device-code flow with the required scope:

```bash
DEVICE_RESPONSE=$(curl -s -X POST \
  "https://login.microsoftonline.com/$TENANT_ID/oauth2/v2.0/devicecode" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=$ARE_CLI_CLIENT_ID&scope=openid+api://$ARE_BACKEND_CLIENT_ID/agentregistry")

echo "$DEVICE_RESPONSE" | python3 -m json.tool
```

This prints a message like:

```
To sign in, use a web browser to open the page https://login.microsoft.com/device
and enter the code XXXXXXX to authenticate.
```

Open the URL in a browser, enter the code, and sign in with your Entra account. Then poll for the token:

```bash
DEVICE_CODE=$(echo "$DEVICE_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['device_code'])")

# Poll until authentication completes (typically 5-30 seconds)
while true; do
  TOKEN_RESPONSE=$(curl -s -X POST \
    "https://login.microsoftonline.com/$TENANT_ID/oauth2/v2.0/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=urn:ietf:params:oauth:grant-type:device_code&client_id=$ARE_CLI_CLIENT_ID&device_code=$DEVICE_CODE")

  ERROR=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error','none'))")
  if [ "$ERROR" = "none" ]; then
    export ARCTL_API_TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
    echo "Token obtained successfully"
    break
  elif [ "$ERROR" = "authorization_pending" ]; then
    sleep 5
  else
    echo "Error: $ERROR"
    echo "$TOKEN_RESPONSE" | python3 -m json.tool
    break
  fi
done
```

Verify authentication:

```bash
arctl get providers
```

You can also pass the token directly on any command:

```bash
arctl get providers --registry-token "$ARCTL_API_TOKEN"
```

> **Note**: The enterprise `arctl` installs to `$HOME/.arctl/bin/arctl`. If you also have the OSS `arctl` installed (e.g., at `/usr/local/bin/arctl`), make sure the enterprise one takes precedence in your PATH. The OSS CLI does not have `user login`, `apply`, `provider`, or other enterprise commands.

## 9. Set Up the AWS Provider

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

## 10. Deploy an Agent to AWS

Once the AWS provider is registered, you can deploy agents to AWS Bedrock AgentCore.

### Use the A2A-Compatible Demo Agent

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

## 11. Register an MCP Server

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

## 12. Updating AWS Credentials

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

## Troubleshooting

### "The logged in user does not have any mapped roles"

The OIDC token does not contain the expected role claim. Fix:

1. Get a token and decode it at [jwt.ms](https://jwt.ms) (Microsoft's token decoder) or [jwt.io](https://jwt.io)
2. Check whether the `groups` claim is present:
   - If **missing entirely**: The token groups claim was not configured. Go to each app registration > **Token configuration** > **Add groups claim** (Step 4)
   - If **`_claim_names` / `_claim_sources` is present instead**: The user has too many groups (overage). Reduce group memberships or switch to [app roles](#alternative-use-app-roles-instead-of-groups)
   - If **present but contains unexpected values**: Verify the object IDs match what you set in `oidc.superuserRole` and your AccessPolicies
3. If using app roles, check that `oidc.roleClaim` is set to `roles` (not `groups`)
4. Run `helm upgrade` to apply any changes
5. Log out and back in (`arctl user login`)

### "AADSTS900144: The request body must contain the following parameter: 'scope'"

The `arctl user login` command does not currently pass a `scope` parameter in the device authorization request. Entra requires this. Use the [manual device-code login](#manual-device-code-login) flow in Step 8 instead.

### "AADSTS7000218: The request body must contain ... 'client_assertion' or 'client_secret'"

The `are-cli` app registration is configured as a confidential client. The device-code flow requires a public client. Fix:

**Portal**: Go to `are-cli` > **Authentication** > **Allow public client flows** > **Yes** > **Save**.

**CLI**:

```bash
az ad app update --id "$ARE_CLI_CLIENT_ID" --is-fallback-public-client true
```

### "AADSTS50011: The redirect URI ... does not match the redirect URIs configured"

The redirect URI on the app registration does not match the one sent by the client. Fix:

- For `are-cli`: Ensure the redirect URI `http://localhost` is configured under **Mobile and desktop applications**
- For `are-ui`: Ensure the redirect URI `https://<ARE_HTTPS_IP>/callback` is configured under **Single-page application** (must be HTTPS)

### "AADSTS500117: The reply uri specified in the request isn't using a secure scheme"

Entra requires HTTPS for SPA redirect URIs on non-localhost addresses. You cannot use `http://<IP>:8080/callback` for a SPA app registration. Set up an HTTPS Gateway with a self-signed certificate (see Step 7) and register the `https://` callback URI instead.

### "AADSTS65001: The user or administrator has not consented to use the application"

Admin consent has not been granted for the API permissions. Fix:

**Portal**: Go to the app registration > **API permissions** > **Grant admin consent for \<your tenant\>**.

**CLI**:

```bash
az ad app permission admin-consent --id "<APP_CLIENT_ID>"
```

### "Token provider: disabled (encryption key not set)"

This is informational, not an error. Agent token minting (JWT) requires setting `config.jwtPrivateKey` in the Helm values (a 64-character hex string). This is only needed if you want to issue tokens to deployed agents. Generate one with:

```bash
openssl rand -hex 32
```

Then add to your values file:

```yaml
config:
  jwtPrivateKey: "<generated-hex-string>"
```

### v1.0 vs v2.0 Issuer Mismatch

Entra can issue tokens with two different `iss` claim values depending on the app registration's **accessTokenAcceptedVersion**:

| Setting | Issuer in Token |
|---------|----------------|
| `accessTokenAcceptedVersion: 2` (default for new registrations) | `https://login.microsoftonline.com/<TENANT_ID>/v2.0` |
| `accessTokenAcceptedVersion: 1` or `null` | `https://sts.windows.net/<TENANT_ID>/` |

The `oidc.issuer` in your Helm values must match the `iss` claim in the token. If they do not match, token validation will fail with an issuer mismatch error.

To check or set the version:

**Portal**: Go to the app registration > **Manifest** > set `accessTokenAcceptedVersion` to `2` > **Save**.

**CLI**:

```bash
# Check current value
az ad app show --id "$ARE_BACKEND_CLIENT_ID" --query "api.requestedAccessTokenVersion"

# Set to v2.0
az ad app update --id "$ARE_BACKEND_CLIENT_ID" \
  --set "api.requestedAccessTokenVersion=2"
```

Alternatively, if you cannot change the app manifest, set your Helm issuer to `https://sts.windows.net/<TENANT_ID>/`.

### Pods not starting

Check events and logs:

```bash
kubectl describe pod -n agentregistry-system -l app.kubernetes.io/name=agentregistry-enterprise
kubectl logs -n agentregistry-system deployment/agentregistry-enterprise -c wait-for-postgres
kubectl logs -n agentregistry-system deployment/agentregistry-enterprise
```

### CloudFormation stack fails

Check the stack events:

```bash
aws cloudformation describe-stack-events \
  --stack-name agentregistry-access-role \
  --region us-east-1 \
  --query 'StackEvents[?ResourceStatus==`CREATE_FAILED`]'
```

Common causes:
- IAM user lacks `iam:CreateRole` or `cloudformation:CreateStack` permissions
- Role name already exists (use `--role-name` flag with a unique name in `arctl provider setup aws`)

## Cleanup

To remove the installation:

```bash
# Remove the HTTPS Gateway and route
kubectl delete httproute are-https-route -n agentregistry-system
kubectl delete gateway are-https-gateway -n agentregistry-system
kubectl delete secret are-https-tls -n agentregistry-system

# Remove the Helm release
helm uninstall agentregistry-enterprise -n agentregistry-system

# Delete the namespace
kubectl delete namespace agentregistry-system

# Remove the AWS CloudFormation stack
aws cloudformation delete-stack \
  --stack-name agentregistry-access-role \
  --region us-east-1

# Remove temporary files
rm -f /tmp/are-values.yaml /tmp/aws-provider.yaml /tmp/agentregistry-cf.yaml
```

Optionally, clean up the Entra app registrations and groups:

**Portal**: Go to [App registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade) and delete `are-backend`, `are-cli`, and `are-ui`.

**CLI**:

```bash
# Delete app registrations
az ad app delete --id "$ARE_BACKEND_CLIENT_ID"
az ad app delete --id "$ARE_CLI_CLIENT_ID"
az ad app delete --id "$ARE_UI_CLIENT_ID"

# Delete security groups
az ad group delete --group "$GROUP_ADMINS"
az ad group delete --group "$GROUP_READERS"
az ad group delete --group "$GROUP_WRITERS"
```

## Reference

| Component | Value |
|-----------|-------|
| Chart | `oci://us-docker.pkg.dev/solo-public/agentregistry-enterprise/helm/agentregistry-enterprise` |
| Chart Version | `2026.5.3` |
| Image | `us-docker.pkg.dev/solo-public/agentregistry-enterprise/server:v2026.5.3` |
| CLI Install | `curl -sSL https://storage.googleapis.com/agentregistry-enterprise/install.sh \| ARCTL_VERSION=v2026.5.3 sh` |
| HTTP Port | 8080 |
| gRPC Port | 21212 |
| MCP Port | 31313 |
| HTTPS Gateway | Port 443 via `are-https-gateway` (self-signed TLS) |
| Entra OIDC Issuer | `https://login.microsoftonline.com/<TENANT_ID>/v2.0` |
| Entra Device Login | `https://microsoft.com/devicelogin` |
| Token Decoder | [jwt.ms](https://jwt.ms) |
| GitHub Release | [v2026.5.3](https://github.com/solo-io/agentregistry-enterprise/releases/tag/v2026.5.3) |

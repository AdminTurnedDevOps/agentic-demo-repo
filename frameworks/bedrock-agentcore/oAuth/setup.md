## Agentcore Creation

```bash
mkdir solagent
```

```bash
cd solagent
```

```bash
python3.13 -m venv .venv
source .venv/bin/activate
```

```bash
pip install bedrock-agentcore strands-agents bedrock-agentcore-starter-toolkit
```

```bash
agentcore create
```

## Keycloak Installation (Kubernetes)

```
kubectl create ns keycloak
```

```
openssl req -subj '/CN=test.keycloak.org/O=Test Keycloak./C=US' -newkey rsa:2048 -nodes -keyout key.pem -x509 -days 365 -out certificate.pem
```

```
kubectl create secret -n keycloak tls keycloak-tls-secret --cert certificate.pem --key key.pem
```

Deploy Keycloak to your EKS cluster:

```bash
kubectl apply -f keycloak-k8s/
```

Wait for the deployment and get the public NLB URL:

```bash
kubectl get svc keycloak -n keycloak -w
```

Once the `EXTERNAL-IP` is assigned, export it:

```bash
export KEYCLOAK_HOST=$(kubectl get svc keycloak -n keycloak -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
echo "https://$KEYCLOAK_HOST"
```

## Keycloak Client Setup

1. Access Keycloak Admin Console at `https://$KEYCLOAK_HOST` (accept the self-signed certificate warning)
2. Login with `admin` / `admin` (change in production via `keycloak-k8s/secret.yaml`)
3. Create a new realm (e.g., `agentcore`)
4. Go to **Clients** → **Create client**
5. Configure:
   - **Client ID**: `agentcore-client`
   - **Client authentication**: ON
   - **Authentication flow**: Check "Standard flow"
6. Save and go to **Credentials** tab to get the Client Secret

## AgentCore OAuth Configuration

```bash
export KEYCLOAK_DISCOVERY_URL="https://$KEYCLOAK_HOST/realms/agentcore/.well-known/openid-configuration"
export CLIENT_ID="agentcore-client"
export CLIENT_SECRET="<your-client-secret-from-keycloak>"
```

```bash
OAUTH2_RESPONSE=$(aws bedrock-agentcore-control create-oauth2-credential-provider \
  --name "keycloak-provider" \
  --credential-provider-vendor "CustomOauth2" \
  --oauth2-provider-config-input '{
    "customOauth2ProviderConfig": {
      "oauthDiscovery": {
        "discoveryUrl": "'"$KEYCLOAK_DISCOVERY_URL"'"
      },
      "clientId": "'"$CLIENT_ID"'",
      "clientSecret": "'"$CLIENT_SECRET"'"
    }
  }' \
  --output json)
```

Verify the provider was created:

```bash
aws bedrock-agentcore-control get-oauth2-credential-provider --name "keycloak-provider"
```

## Update Keycloak Redirect URI

Configure the redirect URI in your Keycloak client. The callback URL is provided dynamically by AgentCore at runtime, so use a wildcard:

1. Go to Keycloak Admin Console at `https://$KEYCLOAK_HOST`
2. Navigate to **Realm: agentcore** → **Clients** → **agentcore-client**
3. Under **Access settings**, add `*` to **Valid redirect URIs** (or `https://*.amazonaws.com/*` for more security)
4. Save

Note: When you run the agent, the actual callback URL will be shown in the OAuth flow. You can then update this to the specific URL.

## IAM Permissions

Ensure your agent's IAM role includes these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AccessKeycloakProvider",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:GetResourceOauth2Token",
        "secretsmanager:GetSecretValue"
      ],
      "Resource": [
        "arn:aws:bedrock-agentcore:*:*:workload-identity-directory/default/workload-identity/*",
        "arn:aws:bedrock-agentcore:*:*:token-vault/default/oauth2credentialprovider/keycloak-provider",
        "arn:aws:secretsmanager:*:*:secret:bedrock-agentcore-identity!default/oauth2/keycloak-provider*"
      ]
    }
  ]
}
```

## Deploy the Agent

OAuth requires the agent to be deployed to AWS (not running locally) so that AWS AgentCore can handle the callback URL.

### Step 1: Initial Deployment

Deploy the agent to AWS Bedrock AgentCore runtime:

```bash
cd solagent/soloagent
agentcore deploy
```

### Step 2: Get the Agent Endpoint URL

After deployment, get your agent's endpoint URL:

```bash
agentcore status
```

Look for the endpoint URL in the output (e.g., `https://abc123.bedrock-agentcore.us-east-1.amazonaws.com`).

### Step 3: Register Callback URL with Workload Identity

Register the callback URL with your workload identity using the endpoint from Step 2:

```bash
export AGENT_ENDPOINT="https://<your-agent-endpoint-from-status>"

agentcore identity update-workload-identity \
  --name soloagent_Agent-workload \
  --add-return-urls ${AGENT_ENDPOINT}/oauth/callback
```

### Step 3: Update main.py with Callback URL

Update the `OAUTH_CALLBACK_URL` in `src/main.py`:

```python
OAUTH_CALLBACK_URL = "https://<your-agent-endpoint>/oauth/callback"
```

### Step 4: Redeploy

Redeploy the agent with the updated callback URL:

```bash
agentcore deploy
```

### Step 5: Invoke the Agent

```bash
agentcore invoke "Hello"
```

The OAuth flow will:
1. Return an authorization URL pointing to Keycloak
2. User authenticates in Keycloak
3. Keycloak redirects to AWS AgentCore
4. AWS stores the token and provides it to subsequent agent invocations
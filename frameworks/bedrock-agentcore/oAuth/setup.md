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

## Run the Agent

```bash
cd solagent/soloagent
source ../.venv/bin/activate
agentcore dev
```

Invote the agent in a separate terminal:
```
agentcore invoke --dev "Hello"
```
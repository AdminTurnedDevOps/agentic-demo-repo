# On-Behalf-Of (OBO) Token Exchange with Microsoft Entra ID

This guide walks through configuring On-Behalf-Of token exchange using Microsoft Entra ID (Azure AD) with kagent-enterprise and agentgateway-enterprise. OBO lets a user authenticate to the kagent UI, and when agents call downstream services or MCP servers, the gateway exchanges the user's token for a new token scoped to that backend — preserving the user's identity chain.

## How Entra OBO Differs from RFC 8693

Microsoft Entra does **not** implement RFC 8693. Instead, it uses a proprietary OBO flow:

| Field | RFC 8693 (Keycloak, Okta) | Entra ID |
|-------|--------------------------|----------|
| `grant_type` | `urn:ietf:params:oauth:grant-type:token-exchange` | `urn:ietf:params:oauth:grant-type:jwt-bearer` |
| Subject token parameter | `subject_token` | `assertion` |
| Token use indicator | N/A | `requested_token_use=on_behalf_of` |
| Client auth | Basic Auth (standard) | Form-encoded `client_id` + `client_secret` |
| Response | Includes `issued_token_type` | Omits `issued_token_type`, adds `ext_expires_in` |

The agentgateway-enterprise controller handles this difference natively via the `entra` field on `EnterpriseAgentgatewayPolicy`.

## Architecture

```
                                    Microsoft Entra ID
                                   ┌──────────────────┐
                                   │  Token Endpoint   │
                                   │  /oauth2/v2.0/    │
                                   │     token         │
                                   └────────▲──────────┘
                                            │ 3. OBO exchange
                                            │    (jwt-bearer grant)
                                            │
User ──► kagent UI ──► agentgateway ────────┘
  │       (OIDC)        (enterprise)
  │                         │
  │  1. User logs in        │ 4. Forwards request with
  │     via Entra OIDC      │    exchanged token
  │                         ▼
  │                    Backend Service / MCP Server
  │
  └─► 2. User token propagated through agent
        (KAGENT_PROPAGATE_TOKEN=true)
```

1. User authenticates to the kagent UI via Entra OIDC
2. The user's token is propagated through the agent (via `KAGENT_PROPAGATE_TOKEN`)
3. When the agent calls a backend, agentgateway intercepts and performs OBO token exchange with Entra
4. The backend receives a new token scoped to its API, but the user identity is preserved

## Prerequisites

- Kubernetes cluster (GKE, AKS, or similar) with `kubectl` access
- Helm 3.x
- Enterprise license keys for both kagent-enterprise and agentgateway-enterprise
- A Microsoft Entra ID (Azure AD) tenant with admin access
- An LLM API key (Anthropic, OpenAI, etc.)

## Step 1: Register Entra App Registrations

You need a backend app registration for kagent. If your browser-facing UI uses a separate Entra client for interactive login, create a second frontend app registration for that flow.

### 1a. Backend App Registration (kagent-backend)

1. Go to [Azure Portal - App registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. Click **New registration**
3. Configure:
   - **Name**: `kagent-backend`
   - **Supported account types**: Single tenant
4. Click **Register**
5. Note the **Application (client) ID** — this is `KAGENT_BACKEND_CLIENT_ID`
6. Go to **Certificates & secrets** > **New client secret**
7. Copy the **Value** — this is `KAGENT_BACKEND_CLIENT_SECRET`
8. Go to **Expose an API**:
   - Set the Application ID URI (e.g., `api://<KAGENT_BACKEND_CLIENT_ID>`)
   - Add a delegated scope such as `access_as_user`

### 1b. Optional Frontend App Registration (kagent-ui)

1. Click **New registration**
2. Configure:
   - **Name**: `kagent-ui`
   - **Supported account types**: Single tenant
   - **Redirect URI**: Select **Web** (configure in Step 5 after you know the external IP)
3. Click **Register**
4. Note the **Application (client) ID** — this is `KAGENT_FRONTEND_CLIENT_ID`
5. Go to **API permissions** > **Add a permission** > **My APIs** > select `kagent-backend`
   - Add the delegated scope you exposed on `kagent-backend`
   - Click **Grant admin consent**

### 1c. Note Your Tenant ID

From the Azure Portal:
- **Directory (tenant) ID** — this is `TENANT_ID`

## Step 2: Collect Required Values

```bash
# Enterprise license keys
KAGENT_LICENSE_KEY=<enterprise kagent license key>
AGW_LICENSE_KEY=<enterprise AGW license key>

# LLM provider
ANTHROPIC_API_KEY=<api key for kagent>

# Entra backend app
KAGENT_BACKEND_CLIENT_ID=<uuid of entra kagent-backend application>
KAGENT_BACKEND_CLIENT_SECRET=<client-secret of entra kagent-backend application>

# Optional browser-facing frontend app
# The Helm values below do not consume this directly, but keep it if your
# deployed UI or auth layer needs a separate frontend client registration.
KAGENT_FRONTEND_CLIENT_ID=<uuid of entra kagent-ui application>

# Azure
TENANT_ID=<Entra tenant id>

# Optional group-to-role mapping
K8S_TOKEN_PASSTHROUGH_GROUP_ID=<group for logging into ui -- e.g., k8stokenpassthrough>
```

## Step 3: Create Kubernetes Secrets

```bash
# Create the namespace
kubectl create namespace kagent

# Entra OIDC secret for kagent-enterprise
kubectl create secret generic kagent-enterprise-oidc-secret \
  -n kagent \
  --from-literal=clientSecret="${KAGENT_BACKEND_CLIENT_SECRET}"

# LLM API key
kubectl create secret generic kagent-anthropic \
  -n kagent \
  --from-literal=ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}"

# Kagent enterprise license
kubectl create secret generic enterprise-kagent-license \
  -n kagent \
  --from-literal=enterprise-kagent-license-key="${KAGENT_LICENSE_KEY}"

# Agentgateway enterprise license
kubectl create secret generic enterprise-agentgateway-license \
  -n kagent \
  --from-literal=enterprise-agentgateway-license-key="${AGW_LICENSE_KEY}"

# Entra client secret for agentgateway OBO token exchange
kubectl create secret generic entra-obo-client-secret \
  -n kagent \
  --from-literal=client_secret="${KAGENT_BACKEND_CLIENT_SECRET}"
```

## Step 4: Install kagent-enterprise with Entra OIDC

Create `kagent-values.yaml`:

```yaml
oidc:
  issuer: "https://login.microsoftonline.com/${TENANT_ID}/v2.0"
  clientId: "${KAGENT_BACKEND_CLIENT_ID}"
  secretRef: "kagent-enterprise-oidc-secret"
  secretKey: "clientSecret"
  # Claims from the Entra token to propagate into OBO tokens
  oboClaimsToPropagate:
    - email
    - groups
    - oid
    - tid
    - upn
  skipOBO: false

rbac:
  roleMapping:
    roleMapper: "claims.Groups.transformList(i, v, v in rolesMap, rolesMap[v])"
    roleMappings:
      "${K8S_TOKEN_PASSTHROUGH_GROUP_ID}": "global.Admin"

providers:
  default: anthropic
  anthropic:
    provider: Anthropic
    model: "claude-haiku-4-5-20251001"
    apiKeySecretRef: kagent-anthropic
    apiKeySecretKey: ANTHROPIC_API_KEY

ui:
  enabled: true
  service:
    type: LoadBalancer

licensing:
  createSecret: false
  secretName: "enterprise-kagent-license"
```

`oidc.clientId` is the backend or middle-tier Entra application that kagent uses for token validation and OBO-related claims handling. The UI Service defaults to `ClusterIP`, so the example above switches it to `LoadBalancer` to match the external-IP workflow in the next step.

Replace the `${...}` placeholders with your actual values, then install:

```bash
helm upgrade --install kagent \
  oci://us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts/kagent-enterprise \
  -n kagent \
  -f kagent-values.yaml
```

## Step 5: Expose the UI and Configure Redirect URIs

After the kagent UI Service is up, get the external IP:

```bash
kubectl get svc kagent-ui -n kagent
```

If your browser-facing UI uses an Entra app registration, go to the **kagent-ui** app registration > **Authentication** and add the actual callback URI exposed by the UI:

```text
https://<EXTERNAL_IP>/callback
```

Do not use `/auth` as the OIDC callback. In the current enterprise UI codebase, `/auth` is a setup route, while `/callback` is the login callback path.

## Step 6: Install agentgateway-enterprise with Token Exchange

Before installing the agentgateway controller, make sure the required Gateway API and enterprise CRDs are present:

```bash
# Install the Kubernetes Gateway API CRDs
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.1/standard-install.yaml

# Install the enterprise agentgateway CRDs chart
helm upgrade --install agentgateway-crds \
  oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway-crds \
  -n kagent
```

If your cluster already has the standard Gateway API CRDs or the enterprise agentgateway CRDs installed, you can skip the corresponding command.

Create `agw-values.yaml`:

```yaml
tokenExchange:
  enabled: true

controller:
  service:
    ports:
      tokenExchange: 7777

licensing:
  createSecret: false
  secretName: "enterprise-agentgateway-license"
```

```bash
helm upgrade --install agentgateway \
  oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway \
  -n kagent \
  -f agw-values.yaml
```

## Step 7: Create the Entra OBO Policy

This `EnterpriseAgentgatewayPolicy` tells the gateway to perform Entra OBO token exchange for requests targeting a specific backend service.

Save as `entra-obo-policy.yaml`:

```yaml
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: entra-obo-token-exchange
  namespace: kagent
spec:
  targetRefs:
    # Target the backend service that requires an Entra-scoped token.
    # Change this to match your downstream service or MCP server.
    - kind: Service
      name: my-backend-service
      group: ""
  backend:
    tokenExchange:
      mode: ExchangeOnly
      entra:
        tenantId: "${TENANT_ID}"
        clientId: "${KAGENT_BACKEND_CLIENT_ID}"
        # Scope for the downstream API.
        # .default requests all statically consented permissions.
        scope: "api://${KAGENT_BACKEND_CLIENT_ID}/.default"
        clientSecretRef:
          name: entra-obo-client-secret
          key: client_secret
```

Replace the `${...}` placeholders and adjust `targetRefs` to match your backend, then apply:

```bash
kubectl apply -f entra-obo-policy.yaml
```

## Step 8: Configure the Agent for Token Propagation

Set `KAGENT_PROPAGATE_TOKEN=true` on any agent that must forward the user's token to the gateway for OBO exchange.

```yaml
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: obo-demo-agent
  namespace: kagent
  labels:
    app.kubernetes.io/name: obo-demo-agent
spec:
  type: Declarative
  description: "Demo agent with Entra OBO token propagation"
  declarative:
    modelConfig: default-model-config
    systemMessage: |
      You are a helpful assistant. When users ask you to interact with
      backend services, use the available tools. Your requests will
      automatically carry the user's identity via OBO token exchange.
    deployment:
      env:
        - name: KAGENT_PROPAGATE_TOKEN
          value: "true"
```

> **Note:** Do not assume the built-in Helm-installed agents set `KAGENT_PROPAGATE_TOKEN` for you. Add it explicitly to each agent that must participate in user-token propagation.

Apply:

```bash
kubectl apply -f obo-demo-agent.yaml
```

## Verification

### Check kagent OIDC config

```bash
kubectl get configmap kagent-enterprise-config -n kagent -o yaml
```

Confirm `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OBO_CLAIMS_TO_PROPAGATE`, and `SKIP_OBO` are set correctly.

### Check the agentgateway token exchange service

```bash
# Verify the token exchange port is listening
kubectl get svc agentgateway-enterprise-agentgateway -n kagent

# Check the controller logs for token exchange startup
kubectl logs deployment/agentgateway-enterprise-agentgateway -n kagent | grep -Ei "token exchange|AGW server"
```

### Check the policy status

```bash
kubectl get enterpriseagentgatewaypolicy -n kagent
kubectl describe enterpriseagentgatewaypolicy entra-obo-token-exchange -n kagent
```

### Test the flow

1. Open the kagent UI at `https://<EXTERNAL_IP>`
2. Log in with your Microsoft account (must be a member of the `K8S_TOKEN_PASSTHROUGH_GROUP_ID` group)
3. Select the `obo-demo-agent`
4. Send a message that triggers a tool call to the backend service
5. In the agentgateway controller logs, confirm the OBO token exchange succeeded:
   ```bash
   kubectl logs deployment/agentgateway-enterprise-agentgateway -n kagent | grep -i "entra"
   ```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `AADSTS50011: The redirect URI does not match` | Verify the UI app registration uses the actual `https://<EXTERNAL_IP>/callback` URL |
| `AADSTS700016: Application not found in directory` | Double-check `KAGENT_BACKEND_CLIENT_ID`, `KAGENT_FRONTEND_CLIENT_ID` if used, and `TENANT_ID` |
| `AADSTS65001: The user or administrator has not consented` | Grant admin consent for the backend API permission on the frontend app registration |
| `AADSTS7000218: Invalid client secret` | Regenerate the secret in Entra and update the `entra-obo-client-secret` Kubernetes secret |
| Token exchange returns 400 | Verify the `scope` in the policy matches what's exposed on the backend app registration (`api://<client-id>/.default`) |
| Agent requests don't carry user token | Confirm `KAGENT_PROPAGATE_TOKEN=true` is set on the agent pod: `kubectl get pod <agent-pod> -n kagent -o jsonpath='{.spec.containers[*].env}'` |
| `OBO_CLAIMS_TO_PROPAGATE` is empty | Check `kagent-values.yaml` has the `oboClaimsToPropagate` list and re-run `helm upgrade` |
| JWKS validation fails | Verify `kubernetes.jwksUrl` is correct for your cluster, or leave it empty for auto-discovery |
| UI login loop / no redirect | Ensure the Entra app has `openid`, `profile`, and `offline_access` in its API permissions |

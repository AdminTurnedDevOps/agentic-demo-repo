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
   - Add a delegated scope such as `kagent-backend`

### 1b. Frontend App Registration (kagent-ui)

1. Click **New registration**
2. Configure:
   - **Name**: `kagent-ui`
   - **Supported account types**: Single tenant
   - **Redirect URI**: Select **Single-page application (SPA)** (configure in Step 5 after you know the external IP)
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
KAGENT_FRONTEND_CLIENT_ID=72714acf-cb3e-4a6c-9134-bddfbc73512f
AGW_LICENSE_KEY=<enterprise AGW license key>
ANTHROPIC_API_KEY=<api key for kagent>
KAGENT_BACKEND_CLIENT_ID=<uuid of Entra kagent-backend app>
KAGENT_BACKEND_CLIENT_SECRET=<client secret for Entra kagent-backend app>
# Azure
TENANT_ID=<Entra tenant id>
# Optional group-to-role mapping
K8S_TOKEN_PASSTHROUGH_GROUP_ID=<Entra group object ID for the UI login group, for example 966e120a-237f-44fd-9b86-049da1106a93>
# Enterprise chart version and management cluster name
KAGENT_ENT_VERSION=0.3.12
MGMT_CLUSTER=<your-cluster-name>
```

`KAGENT_FRONTEND_CLIENT_ID` should be the browser-facing Entra app registration. For quick testing, you can reuse `KAGENT_BACKEND_CLIENT_ID`, but only if that app registration is configured to allow browser-based PKCE login with the callback URI from Step 5.

## Step 3: Create Kubernetes Secrets

```bash
# Create the namespace
kubectl create namespace kagent

# Shared Entra OIDC client secret for the management UI backend and the runtime controller.
kubectl create secret generic kagent-enterprise-oidc-secret \
  -n kagent \
  --from-literal=clientSecret="${KAGENT_BACKEND_CLIENT_SECRET}"

# LLM API key
kubectl create secret generic kagent-anthropic \
  -n kagent \
  --from-literal=ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}"
```

## Step 4: Install Solo Enterprise for kagent and the kagent Runtime with Entra OIDC

Create `management.yaml`:

```yaml
cluster: "${MGMT_CLUSTER}"

products:
  kagent:
    enabled: true
  agentgateway:
    enabled: true
    namespace: "agentgateway-system"

oidc:
  issuer: "https://login.microsoftonline.com/${TENANT_ID}/v2.0"
  additionalScopes:
    - "offline_access"
    - "api://${KAGENT_BACKEND_CLIENT_ID}/kagent-backend"

ui:
  backend:
    oidc:
      clientId: "${KAGENT_BACKEND_CLIENT_ID}"
      secretRef: "kagent-enterprise-oidc-secret"
      secretKey: "clientSecret"
  frontend:
    oidc:
      clientId: "${KAGENT_FRONTEND_CLIENT_ID}"

service:
  type: LoadBalancer
```

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
    roleMapper: "claims.groups.transformList(i, v, v in rolesMap, rolesMap[v])"
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
  enabled: false

licensing:
  createSecret: false
  secretName: "enterprise-kagent-license"
```

`management.yaml` installs the Solo Enterprise management plane with Microsoft Entra as the OIDC issuer. The UI frontend uses `KAGENT_FRONTEND_CLIENT_ID` for browser login, the UI backend validates tokens with `KAGENT_BACKEND_CLIENT_ID`, and `oidc.additionalScopes` requests both the delegated backend scope and `offline_access`. `kagent-values.yaml` installs the Solo-built kagent runtime, disables the standalone `kagent-ui`, and points the runtime controller at the same Entra issuer with the backend client ID.

Replace the `${...}` placeholders with your actual values, then install:

```bash
helm upgrade --install kagent-mgmt \
  oci://us-docker.pkg.dev/solo-public/solo-enterprise-helm/charts/management \
  --version ${KAGENT_ENT_VERSION} \
  -n kagent \
  --create-namespace \
  -f management.yaml

helm upgrade --install kagent-crds \
  oci://us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts/kagent-enterprise-crds \
  --version ${KAGENT_ENT_VERSION} \
  -n kagent

helm upgrade --install kagent \
  oci://us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts/kagent-enterprise \
  --version ${KAGENT_ENT_VERSION} \
  -n kagent \
  -f kagent-values.yaml
```

## Step 5: Expose the UI and Configure Redirect URIs

After the Solo Enterprise UI Service is up, get the external IP:

```bash
kubectl get svc solo-enterprise-ui -n kagent
```

The `solo-enterprise-ui` Service is HTTP-only. Microsoft Entra SPA redirect URIs require HTTPS on non-localhost addresses, so do **not** register the `solo-enterprise-ui` external IP as your callback URI. Instead, complete Step 7a to expose the UI through Agent Gateway over HTTPS, then register that HTTPS callback URI on the Entra frontend app registration from Step 1b.

The callback URI you ultimately need looks like:

```text
https://<AGW_HTTPS_EXTERNAL_IP>/callback
```

Do not use `/auth` as the OIDC callback. In the current enterprise UI codebase, `/auth` is a setup route, while `/callback` is the login callback path. If you reused the backend app registration for browser login, add the same callback URI there and make sure the app is configured for browser-based PKCE login.

## Step 6: Install agentgateway-enterprise with Token Exchange

Before installing the agentgateway controller, make sure the required Gateway API and enterprise CRDs are present:

```bash
# Install the Kubernetes Gateway API CRDs
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.0/standard-install.yaml

# Install the enterprise agentgateway CRDs chart
helm install agentgateway-crds \
  oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway-crds \
  --version v2.2.0 \
  --namespace agentgateway-system \
  --create-namespace
```

If your cluster already has the standard Gateway API CRDs or the enterprise agentgateway CRDs installed, you can skip the corresponding command.

Create the Agent Gateway enterprise license secret in the namespace that the controller will run in:

```bash
kubectl create secret generic enterprise-agentgateway-license \
  -n agentgateway-system \
  --from-literal=enterprise-agentgateway-license-key="${AGW_LICENSE_KEY}"
```

Create `agw-values.yaml`:

```yaml
tokenExchange:
  enabled: true
  issuer: "http://enterprise-agentgateway.agentgateway-system.svc.cluster.local:7777"
  subjectValidator:
    validatorType: "k8s"
  apiValidator:
    validatorType: "k8s"
  actorValidator:
    validatorType: "k8s"

controller:
  service:
    ports:
      tokenExchange: 7777

licensing:
  createSecret: false
  secretName: "enterprise-agentgateway-license"
```

The current `enterprise-agentgateway` chart requires more than `tokenExchange.enabled: true`. At minimum, the token exchange server also needs an `issuer` plus validator configuration for the subject, API, and actor tokens. The in-cluster service URL above matches the default service name that the chart creates in the `agentgateway-system` namespace.

```bash
helm install agentgateway \
  oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway \
  --version v2.2.0 \
  --namespace agentgateway-system \
  --create-namespace \
  -f agw-values.yaml
```

## Step 7: Create the Gateway and Entra OBO Policy

```
kubectl apply -f- <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: anthropic-secret
  namespace: agentgateway-system
  labels:
    app: agentgateway-entra-testing
type: Opaque
stringData:
  Authorization: $ANTHROPIC_API_KEY
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: agentgateway-entra-testing
  namespace: agentgateway-system
  labels:
    app: agentgateway-entra-testing
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
    - name: http
      port: 8080
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
EOF
```

### 7a. Add HTTPS for the enterprise UI login flow

To use Microsoft Entra SPA login on a non-localhost address, terminate TLS on the Agent Gateway and route the UI through that HTTPS listener.

First, wait for the Gateway to get an external IP:

```bash
kubectl get gateway agentgateway-entra-testing -n agentgateway-system
```

Then generate a self-signed certificate for that IP and create the TLS Secret:

```bash
AGW_HTTPS_EXTERNAL_IP=$(kubectl get gateway agentgateway-entra-testing -n agentgateway-system -o jsonpath='{.status.addresses[0].value}')

openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
  -keyout /tmp/kagent-ui-https.key \
  -out /tmp/kagent-ui-https.crt \
  -subj "/CN=${AGW_HTTPS_EXTERNAL_IP}" \
  -addext "subjectAltName = IP:${AGW_HTTPS_EXTERNAL_IP}"

kubectl create secret tls kagent-ui-https-tls \
  -n agentgateway-system \
  --cert=/tmp/kagent-ui-https.crt \
  --key=/tmp/kagent-ui-https.key \
  --dry-run=client -o yaml | kubectl apply -f -
```

Apply the companion Gateway API manifest that adds an HTTPS listener, a `ReferenceGrant`, and an `HTTPRoute` for the UI:

```bash
kubectl apply -f ui-https-gateway.yaml
```

That manifest is stored next to this guide and updates the existing `agentgateway-entra-testing` Gateway to expose the UI over HTTPS through the Agent Gateway load balancer.

After it is applied, verify the HTTPS endpoint:

```bash
kubectl get svc agentgateway-entra-testing -n agentgateway-system
curl -k -I "https://${AGW_HTTPS_EXTERNAL_IP}/"
curl -k -I "https://${AGW_HTTPS_EXTERNAL_IP}/callback"
```

Register this callback URI on the Entra frontend app registration:

```text
https://<AGW_HTTPS_EXTERNAL_IP>/callback
```

```
kubectl apply -f - <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  labels:
    app: agentgateway-entra-testing
  name: anthropic
  namespace: agentgateway-system
spec:
  ai:
    provider:
        anthropic:
          model: "claude-sonnet-4-6"
  policies:
    auth:
      secretRef:
        name: anthropic-secret
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: claude
  namespace: agentgateway-system
  labels:
    app: agentgateway-entra-testing
spec:
  parentRefs:
    - name: agentgateway-entra-testing
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
    - name: anthropic
      namespace: agentgateway-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```

Create the Entra OBO client secret in the same namespace as the `AgentgatewayBackend` and `EnterpriseAgentgatewayPolicy`:

```bash
kubectl create secret generic entra-obo-client-secret \
  -n agentgateway-system \
  --from-literal=client_secret="${KAGENT_BACKEND_CLIENT_SECRET}"
```

This `EnterpriseAgentgatewayPolicy` tells the gateway to perform Entra OBO token exchange for requests targeting a specific backend service.

Save as `entra-obo-policy.yaml`:

```
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: entra-obo-token-exchange
  namespace: agentgateway-system
spec:
  targetRefs:
    # Target the backend service that requires an Entra-scoped token.
    - kind: AgentgatewayBackend
      name: anthropic
      group: agentgateway.dev
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
EOF
```

The `EnterpriseAgentgatewayPolicy`, its `targetRefs`, and the `clientSecretRef` Secret must all line up in the same namespace when you target an `AgentgatewayBackend`.

Replace the `${...}` placeholders and adjust `targetRefs` to match your backend, then apply:

## Step 8: Configure the Agent for Token Propagation

Set `KAGENT_PROPAGATE_TOKEN=true` on any agent that must forward the user's token to the gateway for OBO exchange.

```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: anthropic-model-config
  namespace: kagent
spec:
  apiKeyPassthrough: true
  model: "claude-sonnet-4-6"
  provider: OpenAI
  openAI:
    baseUrl: http://agentgateway-entra-testing.agentgateway-system.svc.cluster.local:8080/anthropic
---
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
    modelConfig: anthropic-model-config
    systemMessage: |
      You are a helpful assistant. When users ask you to interact with
      backend services, use the available tools. Your requests will
      automatically carry the user's identity via OBO token exchange.
    deployment:
      env:
        - name: KAGENT_PROPAGATE_TOKEN
          value: "true"
EOF
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
kubectl get svc enterprise-agentgateway -n agentgateway-system

# Check the controller logs for token exchange startup
kubectl logs deployment/enterprise-agentgateway -n agentgateway-system | grep -Ei "token exchange|AGW server"
```

You'll see an output similar to the below:
```
{"time":"2026-04-02T20:56:21.553716884Z","level":"info","msg":"starting token exchange server with effective config","component":"tokenexchange","config":"{\"actorValidator\":{\"validatorType\":\"k8s\"},\"apiValidator\":{\"validatorType\":\"k8s\"},\"elicitation\":{\"secretName\":\"\"},\"enabled\":true,\"issuer\":\"http://enterprise-agentgateway.agentgateway-system.svc.cluster.local:7777\",\"subjectValidator\":{\"validatorType\":\"k8s\"}}"}
{"time":"2026-04-02T20:56:21.915446631Z","level":"info","msg":"using SQLite database for token exchange server","component":"tokenexchange","database_path":"/var/db/elicitation.db"}
{"time":"2026-04-02T20:56:21.922221201Z","level":"info","msg":"starting token exchange server on","component":"tokenexchange","address":"0.0.0.0:7777"}
```

### Check the policy status

```bash
kubectl get enterpriseagentgatewaypolicy -n agentgateway-system
kubectl describe enterpriseagentgatewaypolicy entra-obo-token-exchange -n agentgateway-system
```

### Test the flow

1. Open the kagent UI at `https://<AGW_HTTPS_EXTERNAL_IP>`
2. Log in with your Microsoft account (must be a member of the Entra group whose object ID is set in `K8S_TOKEN_PASSTHROUGH_GROUP_ID`)
3. Select the `obo-demo-agent`
4. Send a message that triggers a tool call to the backend service
5. In the agentgateway controller logs, confirm the OBO token exchange succeeded:
   ```bash
   kubectl logs deployment/enterprise-agentgateway -n agentgateway-system | grep -i "entra"
   ```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `AADSTS50011: The redirect URI does not match` | Verify the UI app registration uses the actual `https://<AGW_HTTPS_EXTERNAL_IP>/callback` URL from Step 7a |
| `AADSTS700016: Application not found in directory` | Double-check `KAGENT_BACKEND_CLIENT_ID`, `KAGENT_FRONTEND_CLIENT_ID` if used, and `TENANT_ID` |
| `AADSTS65001: The user or administrator has not consented` | Grant admin consent for the backend API permission on the frontend app registration |
| `AADSTS7000218: Invalid client secret` | Regenerate the secret in Entra and update the `entra-obo-client-secret` Kubernetes secret |
| Token exchange returns 400 | Verify the `scope` in the policy matches what's exposed on the backend app registration (`api://<client-id>/.default`) |
| Agent requests don't carry user token | Confirm `KAGENT_PROPAGATE_TOKEN=true` is set on the agent pod: `kubectl get pod <agent-pod> -n kagent -o jsonpath='{.spec.containers[*].env}'` |
| `OBO_CLAIMS_TO_PROPAGATE` is empty | Check `kagent-values.yaml` has the `oboClaimsToPropagate` list and re-run `helm upgrade` |
| JWKS validation fails | Verify `kubernetes.jwksUrl` is correct for your cluster, or leave it empty for auto-discovery |
| UI login loop / no redirect | Ensure the Entra app has `openid`, `profile`, and `offline_access` in its API permissions |

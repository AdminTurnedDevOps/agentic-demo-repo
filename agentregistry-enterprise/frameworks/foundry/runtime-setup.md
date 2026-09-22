# Azure AI Foundry Runtime Setup

This document records the AgentRegistry Enterprise Foundry runtime setup for:

- Foundry project endpoint: `https://YOUR_ENDPOINT.services.ai.azure.com/api/projects/proj-default`
- Azure tenant ID: `YOUR_AZURE_TENANT_ID`
- Azure subscription ID: YOUR_AZURE_SUB`
- Resource group: `YOUR_RESOURCE_GROUP`
- Foundry account: `YOUR_FOUNDRY_ACCOUNT`
- Foundry project: `proj-default`

## Resources Created

The Entra app registration and service principal were created for AgentRegistry:

```text
App registration display name: agentregistry-foundry-runtime
Client ID: YOUR_CLIENT_ID_FROM_APP_REG
App object ID: YOUR_CLIENT_ID
Service principal object ID: a4dc1bb7-9149-43af-9e3d-c495db16a221
```

The AgentRegistry Secret was created:

```text
Secret name: foundry-runtime-client-secret
Secret key: clientSecret
```

The AgentRegistry runtime connection was created:

```text
Runtime name: foundry-mlevantesting
Runtime type: MicrosoftFoundry
```

## Current Status

The runtime exists in AgentRegistry, and the stored client secret has been verified by Entra token issuance.

The remaining blocker is Azure RBAC. AgentRegistry can authenticate as the service principal, but Foundry sync currently fails with:

```text
Identity(object id: OBJECT_ID does not have permissions for Microsoft.MachineLearningServices/workspaces/agents/read actions.
```

The attempted project-scoped role assignment failed because the signed-in Azure user did not have `Microsoft.Authorization/roleAssignments/write` on the Foundry project scope.

## Required Azure RBAC

Have an Azure Owner or User Access Administrator assign a role that includes `Microsoft.MachineLearningServices/workspaces/agents/read` to the service principal.

Recommended command:

```bash
az role assignment create \
  --assignee-object-id a4dc1bb7-9149-43af-9e3d-c495db16a221 \
  --assignee-principal-type ServicePrincipal \
  --role "Azure AI Developer" \
  --scope /subscriptions/SUBSCRIPTION_ID/resourceGroups/levan-fe
```

If your Azure administrator wants to add the Foundry project role as well:

```bash
az role assignment create \
  --assignee-object-id a4dc1bb7-9149-43af-9e3d-c495db16a221 \
  --assignee-principal-type ServicePrincipal \
  --role "Foundry User" \
  --scope /subscriptions/SUBSCRIPTION_ID/resourceGroups/RESOURCE_GROUP/providers/Microsoft.CognitiveServices/accounts/PROJECT_NAME/projects/proj-default
```

## AgentRegistry Runtime Manifest

This is the runtime shape used by the UI and API:

```yaml
apiVersion: ar.dev/v1alpha1
kind: Runtime
metadata:
  name: foundry-mlevantesting
spec:
  type: MicrosoftFoundry
  config:
    projectEndpoint: https://PROJECT_NAME.services.ai.azure.com/api/projects/proj-default
    tenantId: TENANT_OD
    clientId: CLIENT_ID
    subscriptionId: SUBSCRIPTION_ID
    resourceGroup: RG_NAME
    auth:
      clientSecretRef:
        name: foundry-runtime-client-secret
        key: clientSecret
```

## Create Or Rotate The Client Secret

Do not print or commit the client secret. This command creates a fresh Entra client secret, waits for Entra propagation, verifies token issuance, and stores it in the AgentRegistry Secret.

It assumes a valid AgentRegistry user token is saved at `/tmp/are-user-token.json`.

```bash
APP_ID="app_id"
TENANT_ID="tenant_id"

SECRET_VALUE=$(az ad app credential reset \
  --id "$APP_ID" \
  --display-name agentregistry-foundry-runtime \
  --years 1 \
  --query password -o tsv 2>/dev/null)

for i in {1..12}; do
  TOKEN_TEST=$(curl -sS -X POST "https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "client_id=${APP_ID}" \
    --data-urlencode "client_secret=${SECRET_VALUE}" \
    --data-urlencode "grant_type=client_credentials" \
    --data-urlencode "scope=https://ai.azure.com/.default")

  if [ "$(printf "%s" "$TOKEN_TEST" | jq -r '.access_token != null')" = "true" ]; then
    break
  fi

  sleep 5
done

ENCODED_SECRET=$(printf "%s" "$SECRET_VALUE" | base64 | tr -d "\n")
ARE_TOKEN=$(jq -r .access_token /tmp/are-user-token.json)

jq -n --arg secret "$ENCODED_SECRET" '{
  apiVersion: "ar.dev/v1alpha1",
  kind: "Secret",
  metadata: { name: "foundry-runtime-client-secret" },
  spec: {
    type: "Opaque",
    data: { clientSecret: $secret }
  }
}' | curl -sS -X PUT \
  "http://127.0.0.1:12121/v0/secrets/foundry-runtime-client-secret" \
  -H "Authorization: Bearer ${ARE_TOKEN}" \
  -H "Content-Type: application/json" \
  --data-binary @-
```

## Verify

Port-forward AgentRegistry if needed:

```bash
kubectl -n agentregistry-system port-forward svc/agentregistry-enterprise-server 12121:12121
```

Check the runtime status:

```bash
ARE_TOKEN=$(jq -r .access_token /tmp/are-user-token.json)

curl -sS \
  -H "Authorization: Bearer ${ARE_TOKEN}" \
  http://127.0.0.1:12121/v0/runtimes/foundry-PROJECT_NAME | jq '.status'
```

After Azure RBAC is fixed, the `Synced` condition should no longer report the `Microsoft.MachineLearningServices/workspaces/agents/read` permission error.

Check that the Secret exists without exposing its value:

```bash
curl -sS \
  -H "Authorization: Bearer ${ARE_TOKEN}" \
  http://127.0.0.1:12121/v0/secrets/foundry-runtime-client-secret | jq '.status'
```

Expected Secret status:

```json
{
  "dataKeys": [
    "clientSecret"
  ]
}
```

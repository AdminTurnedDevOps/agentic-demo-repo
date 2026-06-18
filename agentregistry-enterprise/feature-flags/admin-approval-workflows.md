# Approval Workflows

If you're a read user or a user that may have write access, but requires an admin approval to perform a particular action, you can use Approval Workflows.

## Prerequisites

To follow along with this lab, you will need the following:
1. A Runtime deployed
2. An Agent Deployment deployed within your catalog

## Setup

The value that needs to be set in your `values.yaml` or inline is the following:

```
config:
  requireCreateApproval: “true”
```

Here's an example of upgrading an existing agentregistry installation:

```
helm install --upgrade agentregistry-enterprise oci://us-docker.pkg.dev/solo-public/agentregistry-enterprise/charts/agentregistry-enterprise \
--version 2026.6.0 \
--namespace agentregistry-system \
--set config.requireCreateApproval=true \ 
-reuse-values 
```

If you're installing a fresh agentregistry installation, you can use the same `--set config.requireCreateApproval=true` value.

Check and confirm that the approval setting was enabled:

```
kubectl -n agentregistry-system get configmap agentregistry-enterprise \
  -o jsonpath='{.data.REQUIRE_CREATE_APPROVAL}{"\n"}'
```

You should see an output of `true`

## Testing Approval workflows

1. Create an access policy that allows a user to read, public, and edit Runtimes, Deployments in the catalog, and Agents.

The below shows an example of a group called `are-readers` and I have one user within that group. Of course, your group GUID will be different.

```bash
arctl apply -f - <<EOF
apiVersion: ar.dev/v1alpha1
kind: AccessPolicy
metadata:
  name: are-readers-agent-write
spec:
  description: "Agent/Deployment/Runtime read, publish, and edit access for the are-readers Entra group"
  principals:
    - kind: Role
      name: "45cade63-b7a8-401a-b818-5cc06167729b" # are-readers
  rules:
    - actions:
        - "registry:read"
        - "registry:publish"
        - "registry:edit"
      resources:
        - kind: agent
          name: "*"
        - kind: server
          name: "*"
        - kind: runtime
          name: "*"
EOF
```

2. Log in as the user/account within your group and go to your Catalog.

3. Click **+ Create > Agent*

4. Create an Agent (can be anything you want as this is just to test approval flows)

After you create it, you will now see within the catalog an **Administrative Request**

## Approving Requests

1. Log into the UI as your adminsitrator account

2. Go to **Catalog**

You will now see an Adminsitrative Request that you can either **Approve** or **withdraw**

## CLI Based Approvals

You can test the same approval flow from the CLI by logging in as the non-admin user, submitting a catalog asset, and then logging in as an admin to approve it.

The CLI flow is for catalog assets such as `Agent`, `MCPServer`, `Skill`, and `Prompt`. Deploying an existing Agent creates a `Deployment`, and Deployments are not currently approval-gated.

1. Log in as the non-admin user that belongs to the group from the AccessPolicy above.

```bash
arctl user login \
  --oidc-issuer-url "$OIDC_ISSUER" \
  --oidc-client-id "$OIDC_CLIENT_ID"

arctl user whoami
```

Confirm the user has the expected group/role GUID and is not in the configured admin/superuser role.

2. Submit a new catalog Agent.

```bash
arctl apply -f - <<EOF
apiVersion: ar.dev/v1alpha1
kind: Agent
metadata:
  name: approval-test-agent
  tag: "1.0.0"
spec:
  title: approval-test-agent
  description: "Test agent for approval workflow validation"
  modelProvider: anthropic
  modelName: claude-sonnet-4-6
  source:
    image: docker.io/python:3.13-slim
EOF
```

The expected result is that the Agent is staged for approval instead of being created directly in the production catalog.

3. Confirm the Agent is not visible as a normal production catalog item yet.

```bash
arctl get agent approval-test-agent --tag 1.0.0
```

The expected result is `not found` or equivalent, because the asset is waiting in the approval queue.

4. List approval requests.

There is not currently an `arctl approve` command, so use the HTTP approval API with the token from your CLI login.

```bash
export ARCTL_API_TOKEN=$(arctl user info --show-tokens | jq -r .access_token)

curl -s \
  -H "Authorization: Bearer ${ARCTL_API_TOKEN}" \
  "${ARCTL_API_BASE_URL}/v0/approve" | jq .
```

You should see a pending request for:

```text
kind: Agent
namespace: default
name: approval-test-agent
tag: 1.0.0
```

5. Log in as the administrator account.

```bash
arctl user login \
  --oidc-issuer-url "$OIDC_ISSUER" \
  --oidc-client-id "$OIDC_CLIENT_ID"

arctl user whoami
export ARCTL_API_TOKEN=$(arctl user info --show-tokens | jq -r .access_token)
```

Confirm the admin user has the configured admin/superuser role.

6. Approve the request.

Use the `namespace` value from the approval list output. If the submitted YAML did not include `metadata.namespace`, the namespace is usually `default`.

```bash
curl -s -X POST \
  -H "Authorization: Bearer ${ARCTL_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"action":"approve","items":[{"kind":"Agent","namespace":"default","name":"approval-test-agent","tag":"1.0.0"}]}' \
  "${ARCTL_API_BASE_URL}/v0/approve" | jq .
```

7. Confirm the Agent is now in the production catalog.

```bash
arctl get agent approval-test-agent --tag 1.0.0
```

The Agent should now be returned successfully.

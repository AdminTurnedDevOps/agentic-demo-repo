## Showcasing ShadowAI For Managed And Unmanaged Instances

Within the UI, show:
1. Managed instances (the instances that are deployed by agentregistry)
2. Unmmanged instances (the instances that are discovered by agentregistry)


## Real-time Discoverability

### Agents

- Go into the Foundry Portal
- Go to **Build > Agents**
- Create a new Agent
- Wait about 30 seconds and you'll see the new Agent auto-discovered in agentregistry


### MCP

- Go to kagent
- Click on **Tool Servers**
- Add an MCP Server
- Go to agentregistry
- Click on **instances**
- Go to unmanaged instances
- click **Type > MCP Server**
- Wait about 30 seconds and you'll see the new MCP Server auto-discovered in agentregistry


## Virtual Runtime With Agentgateway

Show the virtual runtime, which is agentgateway, to explain that instead of agents connecting directly to MCP servers, the connection goes through the virtual runtime which provides security, observability, and governance of all MCP traffic.

- Gatway object: https://github.com/solo-io/field-agentic-labs/blob/main/agentregistry-enterprise/assets/mcp/agentgateway/parent-gateway-and-route.yaml
- Runtime for the gateway/virtual runtime: https://github.com/solo-io/field-agentic-labs/blob/main/agentregistry-enterprise/assets/mcp/agentgateway/virtual-default-runtime.yaml

## Adding Runtimes (AWS and Microsoft Foundry)

- Add runtimes in both the UI and arctl

Foundry runtime programmatically: https://github.com/solo-io/field-agentic-labs/blob/main/agentregistry-enterprise/011-azure-ai-foundry-runtime.md
AgentCore runtime programmatically: https://github.com/solo-io/field-agentic-labs/blob/main/agentregistry-enterprise/010-aws-bedrock-runtime.md

## Cataloging Of Agentic Resources

- Show how to see/create resources within the **Catalog** tab

## Access Policy

1. Open Access Policies in the dashboard
2. See the configuration that's available
3. Log out
4. Log in with `mlevan-svc`
5. Show whats available with the "read-only" user.

## Resource Deployment

Two methods:

1. Via the UI
2. With `arctl`

For example, with `arctl`, you can use the agentregistry API to add Prompts, Skills, etc. to the catalog (along with runtimes and any other object in agentregistry)

[example](https://github.com/solo-io/field-agentic-labs/blob/main/agentregistry-enterprise/040-prompts.md)

## CICD

The below will go over how to create access and deployment for CICD via GitHub Actions.

### Setup (one time)

The pipeline runs as **mlevan-svc**, the non-admin user from [HITL](#hitl), so its applies are staged for approval. No new Entra app is needed: the pipeline uses a short-lived mlevan-svc access token stored as a repo secret.

Add the API URL as a repo secret (run from the repo that holds the workflow):

```bash
gh secret set ARCTL_API_BASE_URL --body "http://$YOUR_AGENTREGISTRY_URL$:12121"
```

### Before each demo: refresh the token secret

The access token expires after about an hour, so do this shortly before you demo.

1. Get a token with the device-code login [here](https://github.com/AdminTurnedDevOps/agentic-demo-repo/blob/main/agentregistry-enterprise/entra-auth/token-auth.md). The script exports `ARCTL_API_TOKEN`.
2. Confirm it's the right identity: `Superuser` must be `false` and the `HITL_SUBMITTER_GROUP` role must show as `configured`:

   ```bash
   arctl user whoami
   ```

3. Store it as the repo secret:

   ```bash
   gh secret set ARCTL_API_TOKEN --body "${ARCTL_API_TOKEN}"
   ```

> If the pipeline's **Show pipeline identity** step fails with `401 Unauthorized`, the token expired. Repeat these steps and re-run the workflow.

### Workflow

Go to `.github/workflows/agentregistry-apply.yaml` to see the pipeline

### Demo flow

1. Open GitHub
2. Go to the repo
3. Go to Actions
4. See the pipeline

Once complete, delete the secret. Its encrypted in a GitHub Secret, but no point in leaving it around.

```bash
gh secret delete ARCTL_API_TOKEN.
```

## HITL

The below shows a full approval process/Human-In-The-Loop for creating resources.

### Access Policy

Governance human-in-the-loop: a non-admin can **submit** a catalog change, but nothing reaches the production catalog until a registry admin **approves** it. Every step lands in the audit log.

```bash
Entra group object ID of the NON-admin demo user
export HITL_SUBMITTER_GROUP="45cade63-b7a8-401a-b818-5cc06167729b"
```

Confirm the gate is on (output should be `true`):

```bash
kubectl -n agentregistry-system get configmap agentregistry-enterprise \
  -o jsonpath='{.data.REQUIRE_CREATE_APPROVAL}{"\n"}'
```

Log in as admin and give the submitter group permission to publish prompts. Without `registry:publish` the submission is denied outright, not staged.

```bash
arctl apply -f - <<EOF
apiVersion: ar.dev/v1alpha1
kind: AccessPolicy
metadata:
  name: hitl-demo-submitters
spec:
  description: "HITL demo - non-admins can submit prompts; approval required"
  principals:
    - kind: Role
      name: "${HITL_SUBMITTER_GROUP}"
  rules:
    - actions:
        - "registry:read"
        - "registry:publish"
        - "registry:edit"
      resources:
        - kind: prompt
          name: "*"
EOF
```

### 1. Submit as the non-admin user

Log in as the non-admin (use a private browser window for the device-code sign-in so you don't reuse the admin session). You can find the login [here](https://github.com/AdminTurnedDevOps/agentic-demo-repo/blob/main/agentregistry-enterprise/entra-auth/token-auth.md)

Check the user to ensure its not the admin user

```bash
arctl user whoami
```

Submit a prompt:

```bash
arctl apply -f - <<'EOF'
apiVersion: ar.dev/v1alpha1
kind: Prompt
metadata:
  name: hitl-demo-prompt
  tag: "1.0.0"
spec:
  description: "HITL demo - submitted by a non-admin, needs approval"
  content: |
    You are a customer support assistant.
    Never share account numbers or internal ticket IDs.
EOF
```

Expected output: the change is **staged**, not created:

```text
✓ Prompt/hitl-demo-prompt (1.0.0) staged
```

Show it isn't in the production catalog (shoudl show `resource not found`):

```bash
arctl get prompt hitl-demo-prompt --tag "1.0.0"
```

### 2. Approve as admin

**UI path:**
1. Log in as the admin
2. Note the notifications bell in the top bar (pending requests)
3. Go to **Catalog**, find `hitl-demo-prompt`, and click **Approve**

Expected: `"status": "approved"` for the item.

### 3. Show the audit trail

Every submit, approve, revoke, and withdraw is emitted as an `approval` audit event (submitter, approver, resource, state):

```bash
kubectl -n agentregistry-system logs deploy/agentregistry-audit-debug --since=30m \
  | grep -A16 'event.activity: Str(approval)' \
  | grep -E 'event\.action|approval\.(state|submitter)|actor\.name|resource\.(kind|name|tag)'
```

Look for `event.action: Str(submit)` from the non-admin, then `Str(approve)` (and `Str(revoke)` if you ran step 3) from the admin.
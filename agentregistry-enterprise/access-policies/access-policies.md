# AccessPolicies for Entra ID Groups

Agent Registry Enterprise is configured with `RBAC_ROLE_CLAIM=groups`, and
Entra emits group object IDs (GUIDs) in the `groups` claim. A `Role` principal
therefore references a group GUID, not the group's display name.

These examples use the `are-readers` group GUID

## Policy Model

The policy scopes are separate:

- `registry:*` controls Agent Registry control-plane access: catalog visibility and CRUD on registry resources.
- `registry:read` is what list/get filtering uses. It lets users see matching catalog resources, but it does not grant chat or runtime invocation.
- `runtime:invoke` controls runtime invocation. For chat/A2A, grant it to a `Role` principal on the target catalog `agent`.
- `runtime:invoke` on a `server` controls MCP invocation by runtime components such as deployed agents or gateway-backed MCP traffic.

Code-backed references in `gitrepos/agentregistry-enterprise`:

- `internal/registry/authz/engine.go`: list filtering only considers `registry:read`.
- `internal/registry/api/handlers/a2a.go`: chat/A2A authorizes `runtime:invoke` on the deployment target `agent`.
- `internal/accesspolicy/kagent/plan.go`: kagent fan-out only translates `runtime:invoke`; `Role` principals are dropped for kagent CRD fan-out.
- `internal/agwsync/config_translate.go`: agentgateway authorization only emits rules for `runtime:invoke`.

## Catalog Read Access

Members of `are-readers` can read matching catalog resources. Deletion is intentionally omitted.

```bash
arctl apply -f - <<EOF
apiVersion: ar.dev/v1alpha1
kind: AccessPolicy
metadata:
  name: are-readers-read-catalog
spec:
  description: "Catalog read access for the are-readers Entra group"
  principals:
    - kind: Role
      name: "45cade63-b7a8-401a-b818-5cc06167729b" # are-readers
  rules:
    - actions:
        - "registry:read"
      resources:
        - kind: skill
          name: "*"
        - kind: server
          name: "*"
        - kind: prompt
          name: "*"
EOF
```

## Catalog Write Access

Members of `are-readers` can read, publish, and edit matching catalog resources.
Deletion is intentionally omitted.

```bash
arctl apply -f - <<EOF
apiVersion: ar.dev/v1alpha1
kind: AccessPolicy
metadata:
  name: are-readers-catalog-write
spec:
  description: "Catalog read, publish, and edit access for the are-readers Entra group"
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

## User Chat Access

Chatting with an agent requires `runtime:invoke` on the catalog `agent` that the
Deployment targets. The A2A handler resolves the Deployment to `targetRef.name`
and checks this permission against the user's `Role` principals.

This grants `are-admins` chat access to the `k8shelper` catalog agent.

```bash
arctl apply -f - <<EOF
apiVersion: ar.dev/v1alpha1
kind: AccessPolicy
metadata:
  name: are-admins-k8shelper-chat
spec:
  description: "Allow are-admins users to invoke the k8shelper agent"
  principals:
    - kind: Role
      name: "94f6134f-0fbd-4786-b69f-1f163719f28c" # are-admins
  rules:
    - actions:
        - "runtime:invoke"
      resources:
        - kind: agent
          name: k8shelper
EOF
```

## Agent Runtime Access to MCP Tools

This controls what a deployed agent can invoke at runtime. Use a `Deployment`
principal for the deployed agent and grant `runtime:invoke` on the MCP `server`.

Omitting `subresources` allows all tools on the server. Adding `subresources`
limits access to specific MCP tools and each entry must use `tool/<name>`.

```bash
arctl apply -f - <<EOF
apiVersion: ar.dev/v1alpha1
kind: AccessPolicy
metadata:
  name: k8shelper-github-copilot-tools
spec:
  description: "Allow the k8shelper deployment to invoke GitHub Copilot MCP tools"
  principals:
    - kind: Deployment
      name: k8shelper-kagent
  rules:
    - actions:
        - "runtime:invoke"
      resources:
        - kind: server
          name: github-copilot-mcp-server
EOF
```

Example with explicit tool restriction:

```bash
arctl apply -f - <<EOF
apiVersion: ar.dev/v1alpha1
kind: AccessPolicy
metadata:
  name: k8shelper-github-copilot-create-issue
spec:
  description: "Allow the k8shelper deployment to invoke only selected GitHub Copilot MCP tools"
  principals:
    - kind: Deployment
      name: k8shelper-kagent
  rules:
    - actions:
        - "runtime:invoke"
      resources:
        - kind: server
          name: github-copilot-mcp-server
          subresources:
            - tool/create_issue
EOF
```

## Verify

```bash
# Confirm your mapped roles contain the Entra group GUIDs used above.
arctl user whoami

# List applied policies.
arctl get accesspolicies

# Catalog visibility should be controlled by registry:read.
arctl get agents
arctl get runtimes

# User chat/invoke requires runtime:invoke on the target catalog agent.
# If catalog read works but chat fails, check the User Chat Access policy.
```

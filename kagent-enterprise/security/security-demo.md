## k8s Agent Access Policies (programmatic)

1. Creat a new namespace to work in and enroll it into the mesh:
```
kubectl create ns policies

kubectl label namespaces policies istio.io/dataplane-mode=ambient
```

2. Create an MCP Server object
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha1
kind: MCPServer
metadata:
  name: test-mcp-server
  namespace: policies
  labels:
    kagent.solo.io/waypoint: "true"
spec:
  deployment:
    image: mcp/everything
    port: 3000
    cmd: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-github"
  transportType: stdio
EOF
```

3. Create an environment variable and k8s secret for your Anthropic key:
```
export ANTHROPIC_API_KEY=

kubectl create secret generic kagent-anthropic --from-literal=ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY -n policies
```

4. Create a Model Config
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: anthropic-model-config
  namespace: policies
spec:
  apiKeySecret: kagent-anthropic
  apiKeySecretKey: ANTHROPIC_API_KEY
  model: claude-sonnet-4-20250514
  provider: Anthropic
  anthropic: {}
EOF
```

5. Create an Agent
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: test-tools-agent
  namespace: policies
spec:
  description: This agent can use a single tool to expand it's Kubernetes knowledge for troubleshooting and deployment
  type: Declarative
  declarative:
    modelConfig: anthropic-model-config
    systemMessage: |-
      You're a friendly and helpful agent that uses the Kubernetes tool to help troubleshooting and deploy environments
  
      # Instructions
  
      - If user question is unclear, ask for clarification before running any tools
      - Always be helpful and friendly
      - If you don't know how to answer the question DO NOT make things up
        respond with "Sorry, I don't know how to answer that" and ask the user to further clarify the question
  
      # Response format
      - ALWAYS format your response as Markdown
      - Your response will include a summary of actions you took and an explanation of the result
    tools:
    - type: McpServer
      mcpServer:
        name: test-mcp-server
        kind: MCPServer
        toolNames:
        - search_repositories
        - search_issues
        - search_code
        - search_users
EOF
```

6. Open the Agent in kagent and ask `What tools do you have available? Give me the list`

You should see four tools:
        - search_repositories
        - search_issues
        - search_code
        - search_users

### Access Policy For Denying Tools

1. Apply an access policy that specifies only access to one of the tools
```
kubectl apply -f - <<EOF
apiVersion: policy.kagent-enterprise.solo.io/v1alpha1
kind: AccessPolicy
metadata:
  name: deny-github-tool-server
  namespace: policies
spec:
  from:
    subjects:
    - kind: Agent
      name: test-tools-agent
      namespace: policies
  targetRef:
    kind: MCPServer
    name: test-mcp-server
    tools: ["search_repositories"]
  action: DENY
EOF
```

2. Prompt again
```
What tools do you have available? Give me the list
```

You should now not the `search_repositories` tool

3. Delete the policy

```
kubectl delete -f - <<EOF
apiVersion: policy.kagent-enterprise.solo.io/v1alpha1
kind: AccessPolicy
metadata:
  name: deny-github-tool-server
  namespace: policies
spec:
  from:
    subjects:
    - kind: Agent
      name: test-access-policy
      namespace: kagent
  targetRef:
    kind: MCPServer
    name: test-mcp-server
    tools: ["search_repositories"]
  action: DENY
EOF
```

### Access Policies For Allowing Specific Tools

1. Apply an access policy that specifies only access to one of the tools
```
kubectl apply -f - <<EOF
apiVersion: policy.kagent-enterprise.solo.io/v1alpha1
kind: AccessPolicy
metadata:
  name: allow-github-tool-server
  namespace: policies
spec:
  from:
    subjects:
    - kind: Agent
      name: test-tools-agent
      namespace: policies
  targetRef:
    kind: MCPServer
    name: test-mcp-server
    tools: ["search_repositories"]
  action: ALLOW
EOF
```

2. Prompt again
```
What tools do you have available? Give me the list
```

You should now the `search_repositories` tool

3. Delete the policy:

```
kubectl delete -f - <<EOF
apiVersion: policy.kagent-enterprise.solo.io/v1alpha1
kind: AccessPolicy
metadata:
  name: allow-github-tool-server
  namespace: policies
spec:
  from:
    subjects:
    - kind: Agent
      name: test-tools-agent
      namespace: policies
  targetRef:
    kind: MCPServer
    name: test-mcp-server
    tools: ["search_repositories"]
  action: ALLOW
EOF
```

## k8s Agent Access Policies (UI)

1. Log into kagent
2. Go to Access Policies
3. Create a new access policy
4. Choose "Deny" as the action
5. For the **Subjects**, choose **Agent** for the Kind and your Agents name for the Agent (`test-tools-agent`)
6. For the **Target Type**, choose **MCP Server** and specify the MCP Server tool `search_repositories` that will be denied via the Access Policy

You should now be able to open the `test-tools-agent` and prompt it with `What tools do you have access to?`. It should return:

## Prompt Guards

1. Create a Gateway, Route, and Backend. You can find the configurations for that here: `https://github.com/AdminTurnedDevOps/agentic-demo-repo/blob/main/agentgateway-enterprise/security/prompt-guard/setup.md`

2. Create a policy to block against specific prompts
```
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: credit-guard-prompt-guard
  namespace: agentgateway-system
  labels:
    app: agentgateway-route
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: claude
  backend:
    ai:
      promptGuard:
        request:
        - response:
            message: "Rejected due to inappropriate content"
          regex:
            action: Reject
            matches:
            - "credit card"
EOF
```

3. Test the `curl` again
```
curl "$INGRESS_GW_ADDRESS:8080/anthropic" -v -H content-type:application/json -H "anthropic-version: 2023-06-01" -d '{
  "messages": [
    {
      "role": "system",
      "content": "You are a skilled cloud-native network engineer."
    },
    {
      "role": "user",
      "content": "What is a credit card?"
    }
  ]
}' | jq
```

You should now see the `403 forbidden`
```
* upload completely sent off: 204 bytes
< HTTP/1.1 403 Forbidden
< content-length: 37
< date: Mon, 19 Jan 2026 12:56:34 GMT
```

4. Clean up the policy
```
kubectl delete -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: credit-guard-prompt-guard
  namespace: agentgateway-system
  labels:
    app: agentgateway-route
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: claude
  backend:
    ai:
      promptGuard:
        request:
        - response:
            message: "Rejected due to inappropriate content"
          regex:
            action: Reject
            matches:
            - "credit card"
EOF
```

## UI Auth with an OIDC provider

- Logging in with keycloak (currently works in demo environment. Show log in and log off)

Providers: https://docs.solo.io/kagent-enterprise/docs/main/install/idp/


## Platform RBAC (Kubernetes RBAC for the kagent CRDs)

Below are several examples for managing kagent CRDs in k8s rbac

### ClusterRole for kagent CRD Management

This ClusterRole grants full access to manage kagent custom resources:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kagent-crd-admin
rules:
  - apiGroups: ["kagent.dev"]
    resources: ["agents", "mcpservers", "modelconfigs"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["policy.kagent-enterprise.solo.io"]
    resources: ["accesspolicies"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

### ClusterRole for Read-Only Access

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kagent-crd-viewer
rules:
  - apiGroups: ["kagent.dev"]
    resources: ["agents", "mcpservers", "modelconfigs"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["policy.kagent-enterprise.solo.io"]
    resources: ["accesspolicies"]
    verbs: ["get", "list", "watch"]
```

### Namespace-scoped Role for Agent Operators

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: kagent-operator
  namespace: kagent
rules:
  - apiGroups: ["kagent.dev"]
    resources: ["agents", "mcpservers"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["policy.kagent-enterprise.solo.io"]
    resources: ["accesspolicies"]
    verbs: ["get", "list", "watch"]
```

### ClusterRoleBinding for Admin Users

Bind the admin ClusterRole to a specific group or user:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: kagent-admin-binding
subjects:
  - kind: Group
    name: kagent-admins
    apiGroup: rbac.authorization.k8s.io
  - kind: User
    name: platform-admin@example.com
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: kagent-crd-admin
  apiGroup: rbac.authorization.k8s.io
```

### RoleBinding for Namespace Operators

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: kagent-operator-binding
  namespace: kagent
subjects:
  - kind: Group
    name: kagent-operators
    apiGroup: rbac.authorization.k8s.io
  - kind: ServiceAccount
    name: ci-deploy-agent
    namespace: ci-cd
roleRef:
  kind: Role
  name: kagent-operator
  apiGroup: rbac.authorization.k8s.io
```

## Role mapping

https://docs.solo.io/kagent-enterprise/docs/main/install/idp/#rbac

You can update this ConfigMap to map your claim name and user groups to roles.

```
kubectl edit configmap rbac-config-management -n kagent
```

### ConfigMap Structure

The `rbac-config-management` ConfigMap uses a CEL expression to map IdP group claims to kagent roles:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: rbac-config-management
  namespace: kagent
data:
  config: |
    {
      "roleMapper": "has(claims.Groups) ? claims.Groups.transformList(i, v, v in rolesMap, rolesMap[v]) : (has(claims.groups) ? claims.groups.transformList(i, v, v in rolesMap, rolesMap[v]) : [])",
      "roleMappings": {
        "admins": "global.Admin",
        "readers": "global.Reader",
        "writers": "global.Writer"
      }
    }
```
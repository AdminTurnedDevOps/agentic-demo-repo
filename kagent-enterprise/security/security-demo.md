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

1. Create a ServiceAccount to test with

```
kubectl create serviceaccount test-reader -n kagent
```

2. Create the ClusterRole

```
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kagent-crd-viewer
rules:
  - apiGroups: ["kagent.dev"]
    resources: ["agents", "mcpservers", "modelconfigs"]
    verbs: ["get", "list", "watch"]
EOF
```

3. Bind the ClusterRole to the ServiceAccount

```
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: kagent-viewer-binding
subjects:
  - kind: ServiceAccount
    name: test-reader
    namespace: kagent
roleRef:
  kind: ClusterRole
  name: kagent-crd-viewer
  apiGroup: rbac.authorization.k8s.io
EOF
```

4. Verify read access works (should return "yes")

```
kubectl auth can-i get mcpservers.kagent.dev --as=system:serviceaccount:kagent:test-reader
```

5. Verify create access is denied (should return "no")

```
kubectl auth can-i create mcpservers.kagent.dev --as=system:serviceaccount:kagent:test-reader
```

6. Try creating an MCPServer as the ServiceAccount (should be forbidden)

```
kubectl apply -f - <<EOF --as=system:serviceaccount:kagent:test-reader
apiVersion: kagent.dev/v1alpha1
kind: MCPServer
metadata:
  name: test-reader-only
  namespace: kagent
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

You'll get an error like the below:
```
Error from server (Forbidden): error when creating "STDIN": mcpservers.kagent.dev is forbidden: User "system:serviceaccount:kagent:test-reader" cannot create resource "mcpservers" in API group "kagent.dev" in the namespace "kagent"
```

7. Cleanup test resources

```
kubectl delete serviceaccount test-reader -n kagent
kubectl delete clusterrolebinding test-reader-binding
kubectl delete clusterrole kagent-crd-viewer
```
1. Create an MCP Server object
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha1
kind: MCPServer
metadata:
  name: test-mcp-server
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

2. Create an Agent
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: test-access-policy
  namespace: kagent
spec:
  description: This agent can use a single tool to expand it's Kubernetes knowledge for troubleshooting and deployment
  type: Declarative
  declarative:
    modelConfig: default-model-config
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

3. Open the Agent in kagent and ask `What tools do you have available?`

You should see four tools:
        - search_repositories
        - search_issues
        - search_code
        - search_users

4. Apply an access policy that specifies only access to one of the tools
```
kubectl apply -f - <<EOF
apiVersion: policy.kagent-enterprise.solo.io/v1alpha1
kind: AccessPolicy
metadata:
  name: deny-kagent-tool-server
  namespace: kagent
spec:
  from:
    subjects:
    - kind: Agent
      name: test-access-policy
      namespace: kagent
  targetRef:
    kind: MCPServer
    name: test-mcp-server
    # if you comment out the tools parameter, the agent will say it has to tools
    tools: ["search_repositories"]
  action: ALLOW
EOF
```

5. Prompt again
```
`What tools do you have available?`
```

You should now only see access to the `search_repositories` tool
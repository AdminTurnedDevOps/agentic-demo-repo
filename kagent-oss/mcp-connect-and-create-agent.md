The config below It works very much like a package/library import in application code.

When you apply this `MCPServer` resource to your Kubernetes cluster via kagent:

1. kagent (the Kubernetes agent) sees the MCPServer resource
2. It automatically creates a deployment that runs npx `kubernetes-mcp-server@latest`
3. npx fetches the latest version of the `kubernetes-mcp-server` package from npm (just like `pip install` or `npm install` would)
4. The MCP server starts running in a Pod and becomes available via the stdio transport

kagent handles the "package resolution" and deployment automatically. You just declare what MCP server you want (like declaring a dependency in `package.json` or `requirements.txt`), and kagent takes care of fetching, installing, and running it in your cluster.

This is the power of the declarative approach. You specify what you want (the `kubernetes-mcp-server`), and kagent figures out how to get it running.

Don't specify port configurations since stdio transport doesn't use HTTP

1. Create a new MCP Server object in Kubernetes
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha1
kind: MCPServer
metadata:
  name: mcp-kubernetes-server
  namespace: kagent
spec:
  deployment:
    args:
    - kubernetes-mcp-server@latest
    cmd: npx
  stdioTransport: {}
  transportType: stdio
EOF
```

2. Create a new Agent and use the MCP Server you created in step 1
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: kubernetes-mcp-agent
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
        name: mcp-kubernetes-server
        kind: MCPServer
        toolNames:
        - events_list
        - namespaces_list
        - pods_list
        - pods_list_in_namespace
        - pods_get
        - pods_delete
        - pods_log
        - pods_exec
        - pods_run
        - resources_list
        - resources_get
        - resources_create_or_update
        - resources_delete
EOF
```

3. Look at the Agent configuration and wait until both `READY` and `ACCEPTED` are in a `True` status
```
kubectl get agents -n kagent
```

4. Feel free to dive into how it looks "underneath the hood"
```
kubectl describe agent kubernetes-mcp-agent -n kagent
```
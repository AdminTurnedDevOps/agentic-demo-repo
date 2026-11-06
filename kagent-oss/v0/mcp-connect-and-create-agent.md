The config below works very much like a package/library import in application code.

When you apply this `MCPServer` resource to your Kubernetes cluster via kagent:

1. kagent (the Kubernetes agent) sees the MCPServer resource
2. It automatically creates a deployment that runs the GitHub MCP Server Docker container
3. Docker pulls the latest version of `ghcr.io/github/github-mcp-server` from GitHub Container Registry
4. The MCP server starts running in a Pod and becomes available via the stdio transport

kagent handles the "package resolution" and deployment automatically. You just declare what MCP server you want (like declaring a dependency in `package.json` or `requirements.txt`), and kagent takes care of fetching, installing, and running it in your cluster.

This is the power of the declarative approach. You specify what you want (the GitHub MCP Server), and kagent figures out how to get it running.

**Note:** The GitHub MCP Server requires a Personal Access Token (PAT) for authentication. You'll need to create a Kubernetes secret with your GitHub PAT before deploying.

Don't specify port configurations since stdio transport doesn't use HTTP

1. Create the github pat token environment variable:
```
export GITHUB_PERSONAL_ACCESS_TOKEN=your_github_pat_here
```

2. Create the k8s secret to store the PAT token:
```
kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: github-pat
  namespace: kagent
type: Opaque
stringData:
  GITHUB_PERSONAL_ACCESS_TOKEN: $GITHUB_PERSONAL_ACCESS_TOKEN
EOF
```

3. Create a new MCP Server object in Kubernetes:
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: RemoteMCPServer
metadata:
  name: github-mcp-remote
  namespace: kagent
spec:
  description: GitHub Copilot MCP Server
  url: https://api.githubcopilot.com/mcp/
  protocol: STREAMABLE_HTTP
  headersFrom:
    - name: Authorization
      valueFrom:
        type: Secret
        name: github-pat
        key: GITHUB_PERSONAL_ACCESS_TOKEN
  timeout: 5s
  terminateOnClose: true
EOF
```

4. Create a new Agent and use the MCP Server you created in the previous step:
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: github-mcp-agent
  namespace: kagent
spec:
  description: This agent can interact with GitHub repositories, issues, pull requests, and more
  type: Declarative
  declarative:
    modelConfig: default-model-config
    systemMessage: |-
      You're a friendly and helpful agent that uses GitHub tools to help with repository management, issues, pull requests, and code review

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
        name: github-mcp-remote
        kind: RemoteMCPServer
        toolNames:
        - get_latest_release
        - get_commit
        - get_tag
        - list_branches
EOF
```

4. Look at the Agent configuration and wait until both `READY` and `ACCEPTED` are in a `True` status:
```
kubectl get agents -n kagent
```

5. Open the kagent UI, go to the UI, and ask: `What branches are available under `https://github.com/AdminTurnedDevOps/agentic-demo-repo``

6. Feel free to dive into how it looks "underneath the hood":
```
kubectl describe agent github-mcp-agent -n kagent
```

## Creating Your GitHub Personal Access Token

To use the GitHub MCP Server, you need a Personal Access Token with appropriate permissions:

1. Go to GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Click "Generate new token (classic)"
3. Give it a descriptive name like "kagent-mcp-server"
4. Select the following scopes at minimum:
   - `repo` - Full control of private repositories
   - `read:org` - Read org and team membership
   - `read:packages` - Download packages from GitHub Package Registry
5. Click "Generate token" and copy the token immediately (you won't be able to see it again)

For GitHub Enterprise Server, you'll also need to set the `GITHUB_HOST` environment variable in the MCPServer spec.
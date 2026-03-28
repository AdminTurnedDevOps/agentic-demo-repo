## Part 1: MCP Setup

1. Create a `RemotMCPServer` and use the URL of the gateway (this would be a hostname or ALB public IP) in step one within the object.

```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: RemoteMCPServer
metadata:
  name: math-server
  namespace: kagent
spec:
  description: Math server on aks2 in us west
  url: http://20.99.218.165:8080/mcp
  protocol: STREAMABLE_HTTP
  timeout: 5s
  terminateOnClose: true
EOF
```

## Part 2: Agent Setup

1. This `ModelConfig` should already exist from when you ran it in `aks-useast1-agent1setup.md`, but just in case, here it is again:
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: llm-foundry-model-config
  namespace: kagent
spec:
  apiKeySecret: azureopenai-secret
  apiKeySecretKey: Authorization
  model: gpt-5.4-mini
  provider: OpenAI
  openAI:
    baseUrl: http://20.99.229.96:8082/azureopenai
EOF
```

2. Create an Agent. This Agent hits Azure Foundry via your LLM Gateway (Foundry in `South Central US`) and the `math-server` MCP Server via the MCP Gateway, both of which live in the AKS cluster running in `West US`. This shows your Agent going through not only one, but two separate regions as the Agent is deployed in `East US`.
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: test-math
  namespace: kagent
spec:
  description: This agent can use a single tool to expand it's Kubernetes knowledge for troubleshooting and deployment
  type: Declarative
  declarative:
    modelConfig: llm-foundry-model-config
    systemMessage: |-
      You're a friendly math wiz
    tools:
    - type: McpServer
      mcpServer:
        name: math-server
        kind: RemoteMCPServer
        toolNames:
        - add
        - multiply
EOF
```

3. Run the Agent
```
kagent invoke --agent test-math --task "What can you do" -n kagent
```

4. Try to use the MCP Server
```
kagent invoke --agent test-math --task "What MCP Servers and tools do you have access to?" -n kagent
```
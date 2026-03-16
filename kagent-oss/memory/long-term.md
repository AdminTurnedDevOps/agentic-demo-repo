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
    memory:
      modelConfig: embedding-model  # references the embedding ModelConfig above
      ttlDays: 15                   # memories expire after 15 days (default)
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
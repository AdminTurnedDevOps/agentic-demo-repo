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
    a2aConfig:
      skills:
        - id: cluster-diagnostics
          name: Cluster Diagnostics
          description: The ability to analyze and diagnose Kubernetes Cluster issues.
          tags:
            - cluster
            - diagnostics
          examples:
            - "What is the status of my cluster?"
            - "How can I troubleshoot a failing pod?"
            - "What are the resource limits for my nodes?"
        - id: resource-management
          name: Resource Management
          description: The ability to manage and optimize Kubernetes resources.
          tags:
            - resource
            - management
          examples:
            - "Scale my deployment X to 3 replicas."
            - "Optimize resource requests for my pods."
            - "Reserve more CPU for my nodes."
        - id: security-audit
          name: Security Audit
          description: The ability to audit and enhance Kubernetes security.
          tags:
            - security
            - audit
          examples:
            - "Check for RBAC misconfigurations."
            - "Audit my network policies."
            - "Identify potential security vulnerabilities in my cluster."
EOF
```
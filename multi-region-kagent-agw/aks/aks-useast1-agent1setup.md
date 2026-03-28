## Part 1: Agent Setup

1. Put your Foundry API key in an environment variable
```
export AZURE_FOUNDRY_API_KEY=
```

2. Create a new secret with the Foundry API key.
```
kubectl apply -f- <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: azureopenai-secret
  namespace: kagent
  labels:
    app: agentgateway-route-foundry
type: Opaque
stringData:
  Authorization: $AZURE_FOUNDRY_API_KEY
EOF
```

3. Create a ModelConfig. This is pointing to your LLM Gateway (which is agentgateway) and agentgateways `AgentgatewayBackend` is using Microsoft Foundry (in South Central US) as a static host
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

4. Create an Agent that uses the `ModelConfig` above for calling out to Foundry via Agentgateway within `us-central-1`.
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: kagent-direct-test
  namespace: kagent
spec:
  description: This agent can use a single tool to expand it's Kubernetes knowledge for troubleshooting and deployment
  type: Declarative
  declarative:
    modelConfig: llm-foundry-model-config
    systemMessage: |-
      You're a friendly and helpful agent that uses the Kubernetes tool to help troubleshooting and deploy environments
EOF
```

5. Run the Agent
```
kagent invoke --agent kagent-direct-test --task "What can you do" -n kagent
```

You'll see an output similar to the below:

```
{"artifacts":[{"artifactId":"389bd549-0b6a-4c80-be12-2132873ac1f3","parts":[{"kind":"text","text":"I can help you troubleshoot and deploy Kubernetes environments.\n\nTypical things I can do:\n- Diagnose pod, deployment, service, ingress, and job issues\n- Help interpret `kubectl` output and error messages\n- Suggest fixes for crash loops, image pull errors, pending pods, and readiness/liveness probe failures\n- Help plan or review manifests for deployments, services, configmaps, secrets, PVCs, ingress, etc.\n- Assist with rollout, scaling, and namespace-related tasks\n- Walk through production-safe debugging steps\n\nIf you want, send me:\n- the symptom or error message\n- relevant YAML\n- and the output of commands like `kubectl get pods`, `kubectl describe pod ...`, or `kubectl logs ...`\n\nI’ll help you narrow it down."}]}],"contextId":"a6e6e943-1c05-49df-bc6f-65cca4d406c3","history":[{"contextId":"a6e6e943-1c05-49df-bc6f-65cca4d406c3","kind":"message","messageId":"msg-fd2dc7ef-1b02-44e0-b76c-db29007c99e4","parts":[{"kind":"text","text":"What can you do"}],"role":"user","taskId":"5494c578-4a07-4493-8069-793cc9cd9575"},{"contextId":"a6e6e943-1c05-49df-bc6f-65cca4d406c3","kind":"message","messageId":"msg-fd2dc7ef-1b02-44e0-b76c-db29007c99e4","parts":[{"kind":"text","text":"What can you do"}],"role":"user","taskId":"5494c578-4a07-4493-8069-793cc9cd9575"},{"kind":"message","messageId":"229b0cc3-c94e-441d-a248-71556ec5c340","metadata":{"kagent_adk_partial":null,"kagent_app_name":"kagent__NS__kagent_direct_test","kagent_author":"kagent_direct_test","kagent_invocation_id":"e-3b5444d9-189f-4609-8f62-944b694c0cb4","kagent_session_id":"a6e6e943-1c05-49df-bc6f-65cca4d406c3","kagent_usage_metadata":{"candidatesTokenCount":163,"promptTokenCount":283,"totalTokenCount":446},"kagent_user_id":"admin@kagent.dev"},"parts":[{"kind":"text","text":"I can help you troubleshoot and deploy Kubernetes environments.\n\nTypical things I can do:\n- Diagnose pod, deployment, service, ingress, and job issues\n- Help interpret `kubectl` output and error messages\n- Suggest fixes for crash loops, image pull errors, pending pods, and readiness/liveness probe failures\n- Help plan or review manifests for deployments, services, configmaps, secrets, PVCs, ingress, etc.\n- Assist with rollout, scaling, and namespace-related tasks\n- Walk through production-safe debugging steps\n\nIf you want, send me:\n- the symptom or error message\n- relevant YAML\n- and the output of commands like `kubectl get pods`, `kubectl describe pod ...`, or `kubectl logs ...`\n\nI’ll help you narrow it down."}],"role":"agent"}],"id":"5494c578-4a07-4493-8069-793cc9cd9575","kind":"task","metadata":{"kagent_adk_partial":null,"kagent_app_name":"kagent__NS__kagent_direct_test","kagent_author":"kagent_direct_test","kagent_invocation_id":"e-3b5444d9-189f-4609-8f62-944b694c0cb4","kagent_session_id":"a6e6e943-1c05-49df-bc6f-65cca4d406c3","kagent_usage_metadata":{"candidatesTokenCount":163,"promptTokenCount":283,"totalTokenCount":446},"kagent_user_id":"admin@kagent.dev"},"status":{"state":"completed","timestamp":"2026-03-28T17:56:17.330194+00:00"}}
```
## Copilot w/ Agentgateway

## Microsoft Foundry w/ Agentgateway

```
export AZURE_FOUNDRY_API_KEY=
```

```
kubectl apply -f- <<EOF
kind: Gateway
apiVersion: gateway.networking.k8s.io/v1
metadata:
  name: agentgateway-azureopenai-route
  namespace: agentgateway-system
  labels:
    app: agentgateway-azureopenai-route
spec:
  gatewayClassName: enterprise-agentgateway
  infrastructure:
    parametersRef:
      group: enterpriseagentgateway.solo.io
      kind: EnterpriseAgentgatewayParameters
      name: tracing
  listeners:
  - protocol: HTTP
    port: 8088
    name: http
    allowedRoutes:
      namespaces:
        from: All
EOF
```

```
export INGRESS_GW_ADDRESS=$(kubectl get svc -n agentgateway-system agentgateway-azureopenai-route -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESS
```

```
kubectl apply -f- <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: azureopenai-secret
  namespace: agentgateway-system
  labels:
    app: agentgateway-azureopenai-route
type: Opaque
stringData:
  Authorization: $AZURE_FOUNDRY_API_KEY
EOF
```

```
kubectl apply -f- <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  labels:
    app: agentgateway-azureopenai-route
  name: azureopenai
  namespace: agentgateway-system
spec:
  ai:
    provider:
      azureopenai:
        endpoint: mlevantesting.services.ai.azure.com
        deploymentName: gpt-4.1-mini
        apiVersion: 2025-01-01-preview
  policies:
    auth:
      secretRef:
        name: azureopenai-secret
EOF
```

```
kubectl get agentgatewaybackend -n agentgateway-system
```

```
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: azureopenai
  namespace: agentgateway-system
  labels:
    app: agentgateway-azureopenai-route
spec:
  parentRefs:
    - name: agentgateway-azureopenai-route
      namespace: agentgateway-system
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /azureopenai
    filters:
    - type: URLRewrite
      urlRewrite:
        path:
          type: ReplaceFullPath
          replaceFullPath: /v1/chat/completions
    backendRefs:
    - name: azureopenai
      namespace: agentgateway-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```

```
curl "$INGRESS_GW_ADDRESS:8088/azureopenai" -v -H content-type:application/json -d '{
  "messages": [
    {
      "role": "system",
      "content": "You are a skilled cloud-native network engineer."
    },
    {
      "role": "user",
      "content": "Write me a paragraph containing the best way to think about Istio Ambient Mesh"
    }
  ]
}' | jq
```

![](images/route-to-foundry.png)

## Agentgateway Direct To Anthropic

## Switching Model Providers

Ability to switch providers without client change based on price/performance

## Agentgateway Direct To On-Prem

1. Llama as an example

## Traces
1. From agentic runtime to llm provider
2. From agentic runtime to mcp server

## Agentic Security
1. Rate Limiting
2. Audit Logging
3. AuthN/Z
4. Prompt guards
5. OBO

## Performance/Benchmarks

## Agents
1. 1-2 business Agents

## MCP Server & Security

1. User identity
2. Control of MCP Server tools (which can be used, which can't be used, and which need auth)
3. Respect existing OIDC / AD controls
4. Need-to-know access / no leakage


## Target Architecture
1. Where Agentgateway sits relative to Kubernetes
2. Where Agentgateway sits relative to firewalls
3. Where Agentgateway sits relative to external providers
4. Where Agentgateway sits relative to MCP servers
5. Hybrid path across on-prem and cloud providers
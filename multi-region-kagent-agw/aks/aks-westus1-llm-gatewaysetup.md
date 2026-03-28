## Gateway Creation
```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: agentgateway-route-foundry
  namespace: agentgateway-system
  labels:
    app: agentgateway-route-foundry
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
    - name: http
      port: 8082
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
EOF
```

```
export AZURE_FOUNDRY_API_KEY=
```

```
kubectl apply -f- <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: azureopenai-secret
  namespace: agentgateway-system
  labels:
    app: agentgateway-route-foundry
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
    app: agentgateway-route-foundry
  name: azureopenaibackend
  namespace: agentgateway-system
spec:
  ai:
    provider:
      azureopenai:
        endpoint: michaellevan-5616-resource.services.ai.azure.com
        deploymentName: gpt-5.4-mini
        apiVersion: 2025-01-01-preview
  policies:
    auth:
      secretRef:
        name: azureopenai-secret
EOF
```

```
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: azureopenai
  namespace: agentgateway-system
  labels:
    app: agentgateway-route-foundry
spec:
  parentRefs:
    - name: agentgateway-route-foundry
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
    - name: azureopenaibackend
      namespace: agentgateway-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```

```
export INGRESS_GW_ADDRESS=$(kubectl get svc -n agentgateway-system agentgateway-route-foundry -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESS
```

```
curl "$INGRESS_GW_ADDRESS:8082/azureopenai" -v -H content-type:application/json -d '{
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

Example output:

```
2026-03-28T17:28:10.940640Z     info    request gateway=agentgateway-system/agentgateway-route-foundry listener=http route=agentgateway-system/azureopenai endpoint=michaellevan-5616-resource.services.ai.azure.com:443 src.addr=10.224.0.4:14204 http.method=POST http.host=20.99.229.96 http.path=/azureopenai http.version=HTTP/1.1 http.status=200 protocol=llm gen_ai.operation.name=chat gen_ai.provider.name=azure.openai gen_ai.request.model=gpt-5.4-mini gen_ai.response.model=gpt-5.4-mini-2026-03-17 gen_ai.usage.input_tokens=34 gen_ai.usage.output_tokens=173 duration=1704ms
```
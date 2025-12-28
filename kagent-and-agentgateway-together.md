## Kagent Install

```
helm install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
    --namespace kagent \
    --create-namespace
```

```
helm upgrade --install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
    --namespace kagent \
    --set providers.default=anthropic \
    --set providers.anthropic.apiKey=$ANTHROPIC_API_KEY \
    --set ui.service.type=LoadBalancer
```

## Agentgateway Install

```
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml
```

```
helm upgrade -i --create-namespace \
  --namespace agentgateway-system \
  --version v2.2.0-main agentgateway-crds oci://ghcr.io/kgateway-dev/charts/agentgateway-crds
```

```
helm upgrade -i -n agentgateway-system agentgateway oci://ghcr.io/kgateway-dev/charts/agentgateway \
--version v2.2.0-main
```

```
kubectl get pods -n agentgateway-system
```

## LLM Connectivity

```
kubectl apply -f- <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: anthropic-secret
  namespace: agentgateway-system
  labels:
    app: agentgateway-route
type: Opaque
stringData:
  Authorization: $ANTHROPIC_API_KEY
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: agentgateway-route
  namespace: agentgateway-system
  labels:
    app: agentgateway
spec:
  gatewayClassName: agentgateway
  listeners:
    - name: http
      port: 8080
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  labels:
    app: agentgateway-route
  name: anthropic
  namespace: agentgateway-system
spec:
  ai:
    provider:
        anthropic:
          model: "claude-3-5-haiku-latest"
  policies:
    auth:
      secretRef:
        name: anthropic-secret
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: claude
  namespace: agentgateway-system
  labels:
    app: agentgateway-route
spec:
  parentRefs:
    - name: agentgateway-route
      namespace: agentgateway-system
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /anthropic
    filters:
    - type: URLRewrite
      urlRewrite:
        path:
          type: ReplaceFullPath
          replaceFullPath: /v1/chat/completions
    backendRefs:
    - name: anthropic
      namespace: agentgateway-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```

```
export INGRESS_GW_ADDRESS=$(kubectl get svc -n agentgateway-system agentgateway-route -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESS
```

```
curl "$INGRESS_GW_ADDRESS:8080/anthropic" -H content-type:application/json -H "anthropic-version: 2023-06-01" -d '{
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

## Traffic Through Agentgateway From Kagent

```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: anthropic-model-config
  namespace: kagent
spec:
  apiKeySecret: anthropic-secret
  apiKeySecretKey: Authorization
  model: claude-3-5-haiku-latest
  provider: OpenAI
  openAI:
    baseUrl: http://20.57.202.54:8080/anthropic
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: testing-agentgateway
  namespace: kagent
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
EOF
```

```
kubectl logs agentgateway-route-5656b65794-hl9xv -n agentgateway-system

.addr=10.224.0.4:12567 http.method=POST http.host=20.57.202.54 http.path=/anthropic/chat/completions http.version=HTTP/1.1 http.status=200 protocol=llm gen_ai.operation.name=chat gen_ai.provider.name=anthropic gen_ai.request.model=claude-3-5-haiku-latest gen_ai.response.model=claude-3-5-haiku-20241022 gen_ai.usage.input_tokens=183 gen_ai.usage.output_tokens=245 duration=5683ms
```
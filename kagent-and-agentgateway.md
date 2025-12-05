## kagent install

1. Install the kagent CRDs
```
helm install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
    --namespace kagent \
    --create-namespace
```

2. Export your default AI key. In this case, Anthropic is used for the default Model config, but you can change it to any supported provider
```
export ANTHROPIC_API_KEY=your_api_key
```

3. Install kagent

The below contains the flag to give the kagent UI a public IP so you can reach it that way instead of doing a `port-forward`. However, if you're running kagent locally or don't want to create a load balancer, you can just remove the `--set ui.service.type=LoadBalancer` part of the installation below.

```
helm upgrade --install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
    --namespace kagent \
    --set providers.default=anthropic \
    --set providers.anthropic.apiKey=$ANTHROPIC_API_KEY \
    --set ui.service.type=LoadBalancer
```

4. Ensure that kagent is running as expected
```
kubectl get svc -n kagent
```

## kgateway + agentgateway install

1. Install Kubernetes Gateway API CRDs (to be used with the `Gateway` and `HTTPRoute` objects later)
```
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml
```

2. Install the kgateway CRDs (kgateway is used for the gateway control plane)
```
helm upgrade -i --create-namespace --namespace kgateway-system kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds  \
--version v2.1.1 \
--set controller.image.pullPolicy=Always
```

3. Install kgateay with agentgateway (the agentic data plane/proxy)
```
helm upgrade -i -n kgateway-system kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway \
    --version v2.1.1 \
    --set agentgateway.enabled=true \
    --set controller.image.pullPolicy=Always
```

4. Ensure that kgateway is running as expected (you won't see any agentgateway Pods until a `Gateway` object is deployed)
```
kubectl get pods -n kgateway-system
```

5. Ensure that you can see the `agentgateway` Gateway Class
```
kubectl get gatewayclass
```

## LLM Connectivity

```
kubectl apply -f- <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: anthropic-secret
  namespace: kagent
  labels:
    app: agentgateway
type: Opaque
stringData:
  Authorization: $ANTHROPIC_API_KEY
EOF
```

```
kubectl apply -f- <<EOF
kind: Gateway
apiVersion: gateway.networking.k8s.io/v1
metadata:
  name: agentgateway
  namespace: kgateway-system
  labels:
    app: agentgateway
spec:
  gatewayClassName: agentgateway
  listeners:
  - protocol: HTTP
    port: 8080
    name: http
    allowedRoutes:
      namespaces:
        from: All
EOF
```

```
export INGRESS_GW_ADDRESS=$(kubectl get svc -n kgateway-system agentgateway -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESS
```

```
kubectl apply -f- <<EOF
apiVersion: gateway.kgateway.dev/v1alpha1
kind: Backend
metadata:
  labels:
    app: agentgateway
  name: anthropic
  namespace: kgateway-system
spec:
  type: AI
  ai:
    llm:
        anthropic:
          authToken:
            kind: SecretRef
            secretRef:
              name: anthropic-secret
          model: "claude-3-5-haiku-latest"
EOF
```

```
kubectl get backend -n kgateway-system
```

```
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: claude
  namespace: kgateway-system
  labels:
    app: agentgateway
spec:
  parentRefs:
    - name: agentgateway
      namespace: kgateway-system
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
      namespace: kgateway-system
      group: gateway.kgateway.dev
      kind: Backend
EOF
```

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
    baseUrl: http://a1e5a3b9a8eba4aa09517966f1777763-34157947.us-east-1.elb.amazonaws.com:8080/anthropic
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

Run `kubectl logs agentgateway-74f485d95c-hgnmn -n kgateway-system` and you should see an output similar to the below:

```
2025-12-05T17:18:05.241265Z     info    request gateway=kgateway-system/agentgateway listener=http route=kgateway-system/claude endpoint=api.anthropic.com:443 src.addr=192.168.26.166:30892 http.method=POST http.host=xxxx3xxxxx-34xxxxx7.us-east-1.elb.amazonaws.com http.path=/anthropic/chat/completions http.version=HTTP/1.1 http.status=200 protocol=llm gen_ai.operation.name=chat gen_ai.provider.name=anthropic gen_ai.request.model=claude-3-5-haiku-latest gen_ai.response.model=claude-3-5-haiku-20241022 gen_ai.usage.input_tokens=182 gen_ai.usage.output_tokens=269 duration=5929ms
```


### For Bedrock
```
kubectl apply -f- <<EOF
apiVersion: gateway.kgateway.dev/v1alpha1
kind: Backend
metadata:
  labels:
    app: agentgateway
  name: anthropic
  namespace: kgateway-system
spec:
  ai:
    llm:
      bedrock:
        model: eu.anthropic.claude-sonnet-4-5-20250929-v1:0
        region: eu-west-1
EOF
```
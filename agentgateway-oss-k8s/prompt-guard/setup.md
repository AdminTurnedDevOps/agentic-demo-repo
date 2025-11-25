## Gateway and LLM Connectivity

1. Create env variable for Anthropic key

```
export ANTHROPIC_API_KEY=
```

2. Create a Gateway for Anthropic

A `Gateway` resource is used to trigger kgateway to deploy agentgateway data plane Pods

The Agentgateway data plane Pod is the Pod that gets created when a Gateway object is created in a Kubernetes environment where Agentgateway is deployed as the Gateway API implementation.
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

3. Capture the LB IP of the service. This will be used later to send a request to the LLM.
```
export INGRESS_GW_ADDRESS=$(kubectl get svc -n kgateway-system agentgateway -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESS
```

4. Create a secret to store the Claude API key
```
kubectl apply -f- <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: anthropic-secret
  namespace: kgateway-system
  labels:
    app: agentgateway
type: Opaque
stringData:
  Authorization: $ANTHROPIC_API_KEY
EOF
```

5. Create a `Backend` object 

A Backend resource to define a backing destination that you want kgateway to route to. In this case, it's Claude.
```
kubectl apply -f- <<EOF
apiVersion: gateway.kgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  labels:
    app: agentgateway
  name: anthropic
  namespace: kgateway-system
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

6. Ensure everything is running as expected
```
kubectl get agentgatewaybackend -n kgateway-system
```

7. Apply the Route so you can reach the LLM
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
      kind: AgentgatewayBackend
EOF
```

8. Test the LLM connectivity
```
curl "$INGRESS_GW_ADDRESS:8080/anthropic" -H content-type:application/json -H x-api-key:$ANTHROPIC_API_KEY -H "anthropic-version: 2023-06-01" -d '{
  "messages": [
    {
      "role": "system",
      "content": "You are a skilled cloud-native network engineer."
    },
    {
      "role": "user",
      "content": "What is a credit card?"
    }
  ]
}' | jq
```

## Prompt Guard

```
kubectl apply -f - <<EOF
apiVersion: gateway.kgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: credit-guard-prompt-guard
  namespace: kgateway-system
  labels:
    app: agentgateway
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: claude
  backend:
    ai:
      promptGuard:
        request:
        - response:
            message: "Rejected due to inappropriate content"
          regex:
            action: REJECT
            matches:
            - "credit card"
EOF
```

```
curl "$INGRESS_GW_ADDRESS:8080/anthropic" -v -H content-type:application/json -H x-api-key:$ANTHROPIC_API_KEY -H "anthropic-version: 2023-06-01" -d '{
  "messages": [
    {
      "role": "system",
      "content": "You are a skilled cloud-native network engineer."
    },
    {
      "role": "user",
      "content": "What is a credit card?"
    }
  ]
}' | jq
```
export ANTHROPIC_API_KEY=
export OPENAI_API_KEY=

```
kubectl apply -f- <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: anthropic-secret
  namespace: kgateway-system
  labels:
    app: agentgateway-failover
type: Opaque
stringData:
  Authorization: $ANTHROPIC_API_KEY
EOF
```

```
kubectl apply -f- <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: openai-secret
  namespace: kgateway-system
  labels:
    app: agentgateway-failover
type: Opaque
stringData:
  Authorization: $OPENAI_API_KEY
EOF
```

```
kubectl apply -f- <<EOF
kind: Gateway
apiVersion: gateway.networking.k8s.io/v1
metadata:
  name: agentgateway-failover
  namespace: kgateway-system
  labels:
    app: agentgateway-failover
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
kubectl apply -f- <<EOF
apiVersion: gateway.kgateway.dev/v1alpha1
kind: Backend
metadata:
  labels:
    app: agentgateway-failover
  name: agentgateway-failover
  namespace: kgateway-system
spec:
  type: AI
  ai:
    priorityGroups:
    - providers:
      - name: claude-haiku
        anthropic:
          model: "claude-3-5-haiku-latest"
          authToken:
            kind: SecretRef
            secretRef:
              name: anthropic-secret
      - name: gpt-turbo
        openai:
          model: "gpt-3.5-turbo"
          authToken:
            kind: SecretRef
            secretRef:
              name: openai-secret
      - name: claude-opus
        anthropic:
          model: "claude-opus-4-1"
          authToken:
            kind: SecretRef
            secretRef:
              name: anthropic-secret
EOF
```

```
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: claude-gpt-failover
  namespace: kgateway-system
  labels:
    app: agentgateway-failover
spec:
  parentRefs:
    - name: agentgateway-failover
      namespace: kgateway-system
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /model
    filters:
    - type: URLRewrite
      urlRewrite:
        path:
          type: ReplaceFullPath
          replaceFullPath: /v1/chat/completions
    backendRefs:
    - name: agentgateway-failover
      namespace: kgateway-system
      group: gateway.kgateway.dev
      kind: Backend
EOF
```

```
export INGRESS_GW_ADDRESS=$(kubectl get svc -n kgateway-system agentgateway-failover -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESS
```

```
curl "$INGRESS_GW_ADDRESS:8080/model" -H content-type:application/json -H x-api-key:$ANTHROPIC_API_KEY -H "x-api-key:$OPENAI_API_KEY" -H "anthropic-version: 2023-06-01" -d '{
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
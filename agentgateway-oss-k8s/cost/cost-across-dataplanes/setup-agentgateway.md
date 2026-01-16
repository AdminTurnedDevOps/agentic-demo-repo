## Install agentgateway

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

## Claude LLM Secret

1. Create env variable for Anthropic key

```
export ANTHROPIC_API_KEY=
```

2. Create a secret to store the Claude API key
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

## Create Gateways

1. Gateway 1
```
kubectl apply -f- <<EOF
kind: Gateway
apiVersion: gateway.networking.k8s.io/v1
metadata:
  name: agentgateway1
  namespace: agentgateway-system
  labels:
    app: agentgateway1
spec:
  gatewayClassName: agentgateway
  listeners:
  - protocol: HTTP
    port: 8080
    name: http
    allowedRoutes:
      namespaces:
        from: All
---
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  labels:
    app: agentgateway1
  name: anthropic1
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
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: claude1
  namespace: agentgateway-system
  labels:
    app: agentgateway1
spec:
  parentRefs:
    - name: agentgateway1
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
    - name: anthropic1
      namespace: agentgateway-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```

2. Gateway 2
```
kubectl apply -f- <<EOF
kind: Gateway
apiVersion: gateway.networking.k8s.io/v1
metadata:
  name: agentgateway2
  namespace: agentgateway-system
  labels:
    app: agentgateway2
spec:
  gatewayClassName: agentgateway
  listeners:
  - protocol: HTTP
    port: 8080
    name: http
    allowedRoutes:
      namespaces:
        from: All
---
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  labels:
    app: agentgateway2
  name: anthropic2
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
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: claude2
  namespace: agentgateway-system
  labels:
    app: agentgateway2
spec:
  parentRefs:
    - name: agentgateway2
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
    - name: anthropic2
      namespace: agentgateway-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```

3. Gateway 3
```
kubectl apply -f- <<EOF
kind: Gateway
apiVersion: gateway.networking.k8s.io/v1
metadata:
  name: agentgateway3
  namespace: agentgateway-system
  labels:
    app: agentgateway3
spec:
  gatewayClassName: agentgateway
  listeners:
  - protocol: HTTP
    port: 8080
    name: http
    allowedRoutes:
      namespaces:
        from: All
---
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  labels:
    app: agentgateway3
  name: anthropic3
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
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: claude1
  namespace: agentgateway-system
  labels:
    app: agentgateway3
spec:
  parentRefs:
    - name: agentgateway3
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
    - name: anthropic3
      namespace: agentgateway-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```
## Test Gateways

Capture the LB IP of the services. This will be used later to send a request to the LLM.
```
export INGRESS_GW_ADDRESSONE=$(kubectl get svc -n agentgateway-system agentgateway1 -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESSONE

export INGRESS_GW_ADDRESSTWO=$(kubectl get svc -n agentgateway-system agentgateway2 -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESSTWO

export INGRESS_GW_ADDRESSTHREE=$(kubectl get svc -n agentgateway-system agentgateway3 -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESSTHREE
```

Test the LLM connectivity
```
curl "$INGRESS_GW_ADDRESSONE:8080/anthropic" -v \ -H content-type:application/json -H "anthropic-version: 2023-06-01" -d '{
  "model": "claude-sonnet-4-5",
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

```
curl "$INGRESS_GW_ADDRESSTWO:8080/anthropic" -v \ -H content-type:application/json -H "anthropic-version: 2023-06-01" -d '{
  "model": "claude-sonnet-4-5",
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

```
curl "$INGRESS_GW_ADDRESSTHREE:8080/anthropic" -v \ -H content-type:application/json -H "anthropic-version: 2023-06-01" -d '{
  "model": "claude-sonnet-4-5",
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

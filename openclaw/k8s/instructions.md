# OpenClaw on Kubernetes with agentgateway
```
  Users → kubectl exec / port-forward → OpenClaw Service → OpenClaw Pod
                                                              ↓
                                                       LLM API calls
                                                              ↓
                                                        Agentgateway
                                                              ↓
                                                       Anthropic API
```

Traffic flow:
```
OpenClaw → agentgateway → Anthropic API → back through agentgateway → OpenClaw.
```

## Create An AKS Cluster

https://github.com/AdminTurnedDevOps/Kubernetes-Quickstart-Environments/tree/main/azure/aks


## Create An Agentgateway Config

```
kubectl apply -f- <<EOF
kind: Gateway
apiVersion: gateway.networking.k8s.io/v1
metadata:
  name: agentgateway-oc
  namespace: agentgateway-system
  labels:
    app: agentgateway
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
  - protocol: HTTP
    port: 8081
    name: http
    allowedRoutes:
      namespaces:
        from: All
EOF
```

```
export ANTHROPIC_API_KEY=
```

```
kubectl apply -f- <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: anthropic-secret
  namespace: agentgateway-system
  labels:
    app: agentgateway-oc
type: Opaque
stringData:
  Authorization: $ANTHROPIC_API_KEY
EOF
```

```
kubectl apply -f- <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  labels:
    app: agentgateway-oc
  name: anthropic
  namespace: agentgateway-system
spec:
  static:
    host: api.anthropic.com
    port: 443
  policies:
    tls: {}
EOF
```

```
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: ocroute
  namespace: agentgateway-system
spec:
  parentRefs:
    - name: agentgateway-oc
      namespace: agentgateway-system
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /v1/messages
    backendRefs:
    - name: anthropic
      namespace: agentgateway-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```

Confirm the Gateway was created with an IP
```
export INGRESS_GW_ADDRESS=$(kubectl get svc -n agentgateway-system agentgateway-oc -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESS
```

## Create Deployment

Use the following:
1. `openclaw/k8s/openclawcm.yaml`
2. `openclaw/k8s/deployment.yaml`

## Onboard OpenClaw


For OpenClaw onboarding:
```
kubectl exec -it YOUR_OPENCLAW_POD -n default -- openclaw onboard
```

## Test

```
kubectl exec OPENCLAW_POD_NAME -n default -- openclaw agent --message "Say hi"
```

You should see a similar result as below:
```
2026-03-14T15:41:26.634010Z     info    request gateway=agentgateway-system/agentgateway-oc listener=http route=agentgateway-system/ocroute endpoint=api.anthropic.com:443 src.addr=10.224.0.149:62282 http.method=POST http.host=52.241.254.163 http.path=/v1/messages http.version=HTTP/1.1 http.status=200 protocol=http duration=2936ms

```
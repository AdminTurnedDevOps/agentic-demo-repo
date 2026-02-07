## Create A Virtual Machine

1. Spin up an Ubuntu instance. You can use minimal resources like a B-series VM in Azure with a public IP and an NSG
2. For security purposes, lock down the security group/network security group. Only allow SSH from your IP, plus whatever port the gateway listens on (default 18789) from your IP or your messaging platform webhooks.

## Install OpenClaw

3. Install Node 22+
4. Install OpenClaw: `sudo npm install -g openclaw@latest && openclaw onboard --install-daemon`

The daemon runs via systemd user service, so it survives reboots

## Create An AKS Cluster

https://github.com/AdminTurnedDevOps/Kubernetes-Quickstart-Environments/tree/main/azure/aks

## Create An Agentgateway Config

```
export ANTHROPIC_API_KEY=
```

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
  ai:
    provider:
        anthropic:
          model: "claude-opus-4-6"
  policies:
    auth:
      secretRef:
        name: anthropic-secret
EOF
```

```
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: anthropic
  namespace: agentgateway-system
spec:
  parentRefs:
    - name: agentgateway-oc
      namespace: agentgateway-system
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /v1/chat/completions
    backendRefs:
    - name: anthropic
      namespace: agentgateway-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```

Test to confirm authentication works
```
export INGRESS_GW_ADDRESS=$(kubectl get svc -n agentgateway-system agentgateway-oc -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESS
```

Test the connection.

```
curl "$INGRESS_GW_ADDRESS:8080" -H content-type:application/json -d '{
  "model": "claude-sonnet-4-5-20250929",
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


## Configure OpenClaw With Agentgateway

1. SSH into the Azure VM
2. Update the OpenClaw config. The config lives in `~/.openclaw/openclaw.json` and you can override the baseUrl directly.

> **Note:** Use the `openai` provider (not `anthropic`) so OpenClaw sends OpenAI-compatible format. AgentGateway translates this to Anthropic API on the backend. Using native Anthropic format causes marshaling errors with complex message content.

```json
  "models": {
    "mode": "merge",
    "providers": {
      "anthropic": {
        "baseUrl": "http://YOUR_GATEWAY_IP:8080",
        "models": []
      }
    }
  },
  "auth": {
    "profiles": {
      "anthropic:default": {
        "provider": "anthropic",
        "mode": "api_key"
      }
    }
  },
```

3. Restart the OpenClaw daemon:
```
systemctl --user restart openclaw-gateway
```

## Test

To confirm that traffic is flowing through the Gateway, send a request via OpenClaw with the following:

```
kubectl logs -n agentgateway-system agentgateway-oc-POD_NAME -f
```

```
2026-02-07T17:37:45.140127Z     info    request gateway=agentgateway-system/agentgateway-oc listener=http route=agentgateway-system/claude endpoint=api.anthropic.com:443 src.addr=10.224.0.39:48844 http.method=POST http.host=40.125.42.28 http.path=/v1/messages http.version=HTTP/1.1 http.status=200 protocol=llm gen_ai.operation.name=chat gen_ai.provider.name=anthropic gen_ai.request.model=claude-opus-4-6 gen_ai.response.model=claude-opus-4-6 gen_ai.usage.input_tokens=8 gen_ai.usage.output_tokens=1 gen_ai.request.max_tokens=1 duration=1537ms
```
## Ollama Setup On VM

Run Ollama on an Azure VM, and then set the host in your backend config to the VM's public IP address (e.g., http://<azure-vm-public-ip>) with port 11434.

A few things to keep in mind:

- NSG rules — Open port 11434 in the Azure Network Security Group attached to the VM.
- Ollama bind address — By default Ollama only listens on 127.0.0.1. Set the environment variable OLLAMA_HOST=0.0.0.0 so it listens on all interfaces and is reachable externally.
- Security — Ollama has no built-in auth, so exposing it directly to the internet means anyone can use it. Consider restricting the NSG rule to your cluster's egress IP, or putting a reverse proxy with auth in front of it.

## Agw Config

Create env variable for Anthropic key

```
# This is just a placeholder because the OpenAI API spec needs a secret passed in, even if it isn't used

export ANTHROPIC_API_KEY="psuedosecret"
```

Create a Gateway for Llama

```
kubectl apply -f- <<EOF
kind: Gateway
apiVersion: gateway.networking.k8s.io/v1
metadata:
  name: agentgateway-llama
  namespace: agentgateway-system
  labels:
    app: agentgateway-llama
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

Capture the LB IP of the service. This will be used later to send a request to the LLM.
```
export INGRESS_GW_ADDRESS=$(kubectl get svc -n agentgateway-system agentgateway-llama -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $INGRESS_GW_ADDRESS
```

Create a secret to store the Claude API key
```
kubectl apply -f- <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: anthropic-secret
  namespace: agentgateway-system
  labels:
    app: agentgateway-llama
type: Opaque
stringData:
  Authorization: $ANTHROPIC_API_KEY
EOF
```

Create the backend with the static host to connect to the Azure VM exposing Llama
```
kubectl apply -f- <<EOF
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  labels:
    app: agentgateway-llama
  name: llama-backend
  namespace: agentgateway-system
spec:
  static:
    host: http://myhost.com
    port: 11434
  policies:
    auth:
      secretRef:
        # This is just a placeholder because the OpenAI API spec needs a secret passed in, even if it isn't used
        name: anthropic-secret
EOF
```

7. Apply the Route so you can reach the LLM
```
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: llama
  namespace: agentgateway-system
  labels:
    app: agentgateway-llama
spec:
  parentRefs:
    - name: agentgateway-llama
      namespace: agentgateway-system
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /ollama
    filters:
    - type: URLRewrite
      urlRewrite:
        path:
          type: ReplaceFullPath
          replaceFullPath: /v1/chat/completions
    backendRefs:
    - name: llama-backend
      namespace: agentgateway-system
      group: agentgateway.dev
      kind: AgentgatewayBackend
EOF
```
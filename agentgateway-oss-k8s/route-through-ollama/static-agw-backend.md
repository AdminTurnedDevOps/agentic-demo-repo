## Ollama Setup On VM

Run Ollama on an Azure VM, and then set the host in your backend config to the VM's public IP address (e.g., http://<azure-vm-public-ip>) with port 11434.

A few things to keep in mind:

- NSG rules — Open port 11434 in the Azure Network Security Group attached to the VM.
- Ollama bind address — By default Ollama only listens on 127.0.0.1. Set the environment variable OLLAMA_HOST=0.0.0.0 so it listens on all interfaces and is reachable externally.
- Security — Ollama has no built-in auth, so exposing it directly to the internet means anyone can use it. Consider restricting the NSG rule to your cluster's egress IP, or putting a reverse proxy with auth in front of it.

1. Install Ollama

SSH into your Ubuntu VM and run:

`curl -fsSL https://ollama.com/install.sh | sh`

2. Pull a Model

`ollama pull codellama:7b-instruct`

Replace with whichever model you want (e.g., mistral, codellama, qwen2.5-coder).

3. Expose Ollama on All Interfaces

By default, Ollama only listens on 127.0.0.1:11434. To expose it on the public IP, you need to configure it to listen on 0.0.0.0. Edit the systemd service override:

```
sudo systemctl edit ollama
```

Add these lines in the editor that opens (between the comment markers):

```
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
```

Then restart:

```
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Verify it's listening on all interfaces:

```
ss -tlnp | grep 11434
```

You should see 0.0.0.0:11434 instead of 127.0.0.1:11434.

4. Open Port 11434 in Azure NSG

In the Azure Portal (or via CLI):

Portal: VM > Networking > Add inbound port rule:
- Destination port: 11434
- Protocol: TCP
- Action: Allow
- Priority: (e.g., 310)
- Name: Allow-Ollama

Or via Azure CLI:

`az vm open-port --resource-group <YOUR_RG> --name <YOUR_VM> --port 11434 --priority 310`

5. Open the Ubuntu Firewall (if enabled)

```
sudo ufw allow 11434/tcp
```

6. Test It

From your local machine:

```
curl http://<VM_PUBLIC_IP>:11434/api/generate -d '{
  "model": "llama3.1:8b",
  "prompt": "Hello!",
  "stream": false
}'
```

7. Use with an Agent

Point your agent's LLM configuration to the OpenAI-compatible endpoint Ollama exposes:

- Base URL: http://<VM_PUBLIC_IP>:11434/v1
- API Key: any non-empty string (e.g., ollama) — Ollama doesn't validate it
- Model: llama3.1:8b (or whatever you pulled)

Most agent frameworks (LangChain, CrewAI, AutoGen, etc.) accept an OpenAI-compatible base URL.

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

Apply the Route so you can reach the LLM
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
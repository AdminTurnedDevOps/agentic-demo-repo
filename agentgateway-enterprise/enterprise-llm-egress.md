# Enterprise LLM Egress with Agentgateway: Custom Auth Headers for kagent

This workshop demonstrates how to route kagent LLM traffic through [Agentgateway](https://docs.solo.io/agentgateway/latest/) to an enterprise LLM backend that requires custom authentication headers.

## The Problem

Enterprise AI platforms often impose custom requirements on LLM API calls:

1. **Non-standard auth headers** -- e.g., `X-Corp-Trust-Token` instead of `Authorization: Bearer`
2. **Mandatory metadata headers** -- e.g., `x-correlation-id`, `x-usersession-id` for chargeback and tracking
3. **Short-lived JWT tokens** -- tokens with 30-second expiry fetched from a separate token endpoint
4. **OpenAI-compatible body format** -- the request/response body is standard, only the headers are custom

kagent speaks standard OpenAI/Anthropic API formats. Rather than customizing kagent for each enterprise's requirements, Agentgateway sits in front of the LLM backend and handles all header transformation, auth injection, and protocol normalization.

## Architecture

```mermaid
sequenceDiagram
    participant User as User / UI
    participant KA as kagent
    participant AGW as Agentgateway
    participant LLM as Enterprise LLM API

    User->>KA: "Why is my pod failing?"
    KA->>AGW: POST /v1/chat/completions<br/>(standard OpenAI format)
    Note over AGW: Injects custom headers:<br/>X-Corp-Trust-Token: <JWT><br/>x-correlation-id: <id><br/>x-usersession-id: <id>
    AGW->>LLM: POST /v1/chat/completions<br/>(with custom headers)
    LLM-->>AGW: Response
    Note over AGW: Logs token usage,<br/>model, latency
    AGW-->>KA: Response
    KA-->>User: "The pod is in CrashLoopBackOff because..."
```

### Header Transformation Flow

```mermaid
flowchart LR
    subgraph kagent
        req["Standard request<br/>Authorization: Bearer kagent-token"]
    end

    subgraph Agentgateway
        transform["Header Transformation<br/>1. Add X-Corp-Trust-Token<br/>2. Add x-correlation-id<br/>3. Add x-usersession-id"]
    end

    subgraph Enterprise LLM
        llm["Receives request with<br/>custom enterprise headers"]
    end

    req --> transform --> llm

    style transform fill:#4CAF50,color:#fff
    style llm fill:#2196F3,color:#fff
```

---

## Prerequisites

- Kubernetes cluster with kagent already installed
- Helm 3.x
- `kubectl` access to the cluster
- An LLM backend (OpenAI API key for this workshop; in production, your enterprise LLM endpoint)

---

## Step 1: Install Agentgateway

Install the Gateway API CRDs and Agentgateway:

```bash
kubectl apply --server-side -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.0.0/experimental-install.yaml
```

```bash
export AGENTGATEWAY_LICENSE_KEY=

helm upgrade -i --create-namespace \
  --namespace agentgateway-system \
  --version v2026.8.1 enterprise-agentgateway-crds oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway-crds 

helm upgrade -i -n agentgateway-system enterprise-agentgateway oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway \
--version v2026.8.1  \
--set-string licensing.licenseKey=${AGENTGATEWAY_LICENSE_KEY}
```

Verify the installation:

```bash
kubectl get pods -n agentgateway-system
```

---

## Step 2: Deploy the Gateway, Backend, and Route

Apply all three resources at once. This creates:
- A **Gateway** listening on port 8080
- An **AgentgatewayBackend** pointing to the LLM provider (OpenAI for this workshop)
- An **HTTPRoute** that injects the custom enterprise headers on every request

```bash
export OPENAI_API_KEY=
```

```yaml
kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: openai-secret
  namespace: agentgateway-system
type: Opaque
stringData:
  Authorization: "Bearer ${OPENAI_API_KEY}"
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: llm-gateway
  namespace: agentgateway-system
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
    - name: http
      port: 8080
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: All
---
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayBackend
metadata:
  name: enterprise-llm
  namespace: agentgateway-system
spec:
  ai:
    provider:
      openai:
        model: gpt-5.6-luna
  policies:
    auth:
      secretRef:
        name: openai-secret
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: llm-route
  namespace: agentgateway-system
spec:
  parentRefs:
    - name: llm-gateway
      namespace: agentgateway-system
  rules:
    - filters:
        - type: RequestHeaderModifier
          requestHeaderModifier:
            add:
              - name: X-Corp-Trust-Token
                value: "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.example-trust-token"
              - name: x-correlation-id
                value: "kagent-demo-001"
              - name: x-usersession-id
                value: "kagent-session-001"
      backendRefs:
        - name: enterprise-llm
          namespace: agentgateway-system
          group: enterpriseagentgateway.solo.io
          kind: EnterpriseAgentgatewayBackend
EOF
```

```bash
kubectl apply -f agentgateway-llm.yaml
```

Wait for the gateway to be ready:

```bash
kubectl get gateway llm-gateway -n agentgateway-system
```

Expected output:
```
NAME          CLASS                     ADDRESS        PROGRAMMED   AGE
llm-gateway   enterprise-agentgateway   x.x.x.x        True         36s
```

---

## Step 3: Test the LLM Route

Send a chat completion request through the gateway:

```bash
export LLM_GW=$(kubectl get gateway llm-gateway -n agentgateway-system -o jsonpath='{.status.addresses[0].value}')
```

```bash
curl -s http://$LLM_GW:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What is Kubernetes? Reply in one sentence."}],
    "max_tokens": 50
  }' | jq
```

Example output:
```json
{
  "model": "gpt-5.6-luna",
  "service_tier": "default",
  "usage": {
    "prompt_tokens": 16,
    "completion_tokens": 25,
    "total_tokens": 41
  },
  "choices": [
    {
      "message": {
        "content": "Kubernetes is an open-source platform for automating the deployment, scaling, and management of containerized applications.",
        "role": "assistant"
      },
      "finish_reason": "stop"
    }
  ]
}
```

### Check the Access Logs

Agentgateway automatically logs every LLM request with AI-specific metadata:

```bash
kubectl logs deploy/llm-gateway -n agentgateway-system | grep 'request '
```

Expected output:
```json
{
2026-08-25T15:01:26.801848Z     info    request gateway=agentgateway-system/llm-gateway listener=http route=agentgateway-system/llm-route endpoint=api.openai.com:443 src.addr=x.x.x.x:24311 http.method=POST http.host=x.x.x.x http.path=/v1/chat/completions http.version=HTTP/1.1 http.status=200 protocol=llm gen_ai.operation.name=chat gen_ai.provider.name=openai gen_ai.request.model=gpt-5.6-luna gen_ai.response.model=gpt-5.6-luna gen_ai.usage.input_tokens=15 gen_ai.usage.cache_creation.input_tokens=0 gen_ai.usage.cache_read.input_tokens=0 gen_ai.usage.output_tokens=25 gen_ai.usage.reasoning_tokens=0 agw.ai.usage.cost.total=0.000033 gen_ai.usage.input_audio_tokens=0 gen_ai.usage.output_audio_tokens=0 gen_ai.request.max_tokens=50 duration=1719ms
}
```

This gives you per-request visibility into token usage, model, and latency, which is critical for enterprise cost tracking and chargeback.

### Verify Header Injection

To confirm the custom headers are being injected, deploy an echo service and add a test route:

```yaml
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: echo
  namespace: agentgateway-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: echo
  template:
    metadata:
      labels:
        app: echo
    spec:
      containers:
      - name: echo
        image: ealen/echo-server:latest
        ports:
        - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: echo
  namespace: agentgateway-system
spec:
  ports:
  - port: 80
    targetPort: 80
  selector:
    app: echo
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: echo-test
  namespace: agentgateway-system
spec:
  parentRefs:
    - name: llm-gateway
      namespace: agentgateway-system
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /echo
      filters:
        - type: RequestHeaderModifier
          requestHeaderModifier:
            add:
              - name: X-Corp-Trust-Token
                value: "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.example-trust-token"
              - name: x-correlation-id
                value: "kagent-demo-001"
              - name: x-usersession-id
                value: "kagent-session-001"
      backendRefs:
        - name: echo
          namespace: agentgateway-system
          kind: Service
          port: 80
EOF
```

Send a request and inspect the headers the upstream received:

```bash
curl -s http://$LLM_GW:8080/echo \
  -H "Authorization: Bearer original-kagent-token" | jq '.request.headers'
```

Expected output:
```json
{
  "authorization": "Bearer original-kagent-token",
  "user-agent": "curl/8.7.1",
  "accept": "*/*",
  "x-corp-trust-token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.example-trust-token",
  "x-correlation-id": "kagent-demo-001",
  "x-usersession-id": "kagent-session-001",
  "host": "x.x.x.x:8080"
}
```

All three custom headers are injected by Agentgateway before the request reaches the upstream. Clean up the echo resources when done:

```bash
kubectl delete httproute/echo-test deploy/echo svc/echo -n agentgateway-system
```

---

## Step 4: Configure kagent to Use Agentgateway

Now that Agentgateway is handling header injection and LLM routing, point [kagent](https://docs.solo.io/kagent/latest/) at it. kagent supports any OpenAI-compatible endpoint via the `openAI.baseUrl` field in its `ModelConfig` resource.

```mermaid
flowchart LR
    subgraph cluster["Kubernetes Cluster"]
        subgraph kagent-ns["kagent namespace"]
            mc["ModelConfig<br/><b>baseUrl: http://llm-gateway:8080/v1</b>"]
            agent["Agent<br/>k8s-agent"]
            agent -->|uses| mc
        end

        subgraph agw-ns["agentgateway-system namespace"]
            gw["llm-gateway<br/>Gateway :8080"]
            route["HTTPRoute<br/>+ RequestHeaderModifier"]
            backend["AgentgatewayBackend<br/>enterprise-llm"]
            gw --> route --> backend
        end

        mc -->|"POST /v1/chat/completions"| gw
    end

    backend -->|"+ X-Corp-Trust-Token<br/>+ x-correlation-id<br/>+ x-usersession-id"| llm["Enterprise LLM API"]

    style mc fill:#ff9800,color:#fff
    style route fill:#4CAF50,color:#fff
    style llm fill:#2196F3,color:#fff
```

### Create the ModelConfig

The `provider` is set to `OpenAI` and `openAI.baseUrl` points at the Agentgateway service. kagent sends standard OpenAI Chat Completions requests to Agentgateway, which adds the custom headers and forwards to the actual LLM.

```yaml
kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: openai-secret
  namespace: kagent
type: Opaque
stringData:
  Authorization: "Bearer ${OPENAI_API_KEY}"
---
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: enterprise-llm
  namespace: kagent
spec:
  provider: OpenAI
  model: gpt-4o-mini
  apiKeySecret: kagent-openai
  apiKeySecretKey: OPENAI_API_KEY
  openAI:
    baseUrl: http://$LLM_GW:8080/v1
EOF
```

### Create or Update an Agent

Create an agent that uses the new ModelConfig. This example creates a Kubernetes troubleshooting agent:

```yaml
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: k8s-agent
  namespace: kagent
spec:
  description: Kubernetes troubleshooting agent routed through Agentgateway.
  type: Declarative
  declarative:
    modelConfig: enterprise-llm
    systemMessage: |
      You are a Kubernetes expert. Help users diagnose and fix issues
      with their clusters, pods, deployments, and services.
    tools:
      - type: McpServer
        mcpServer:
          apiGroup: kagent.dev
          kind: MCPServer
          name: kubernetes
EOF
```

### Verify the Integration

Open the kagent dashboard and chat with the agent by either:

1. Open the ALB IP via the `solo-enterprise-ui` service under the `kagent` namespace

2. Port-forward the UI:

```bash
kubectl port-forward -n kagent svc/solo-enterprise-ui 8080:80
```

Ask the agent a question like *"What pods are running in the default namespace?"*. Then confirm the request flowed through Agentgateway by checking the access logs:

```bash
kubectl logs deploy/llm-gateway -n agentgateway-system --tail=5 | grep '"scope":"request"'
```

You should see the LLM request logged with token usage, model, and latency -- confirming that all kAgent LLM traffic is now flowing through Agentgateway with the custom enterprise headers injected.

---

## Step 5: Production — Automatic Token Rotation with ExtAuth

Steps 1–4 use a static token in the HTTPRoute, which works for demos. In production, enterprise LLM backends often issue short-lived JWT tokens (e.g., 30-second expiry) from a separate token endpoint. A static token would expire almost immediately.

Enterprise Agentgateway solves this with an **External Authorization (ExtAuth) service** that fetches a fresh token on every LLM request:

```mermaid
sequenceDiagram
    participant KA as kagent
    participant AGW as Agentgateway
    participant Auth as ExtAuth Service
    participant IDP as Enterprise Token Endpoint
    participant LLM as Enterprise LLM API

    KA->>AGW: POST /v1/chat/completions
    AGW->>Auth: Check request (gRPC ext-authz)
    Auth->>IDP: POST /token<br/>(service account credentials)
    IDP-->>Auth: JWT (30s TTL)
    Auth-->>AGW: 200 OK<br/>+ inject header: X-Corp-Trust-Token
    Note over AGW: Adds token from ext-auth<br/>response into upstream request
    AGW->>LLM: POST /v1/chat/completions<br/>(with fresh JWT + metadata headers)
    LLM-->>KA: Response
```

### Deploy the ExtAuth Service

The ext-auth service implements the [Envoy gRPC ext-authz protocol](https://www.envoyproxy.io/docs/envoy/latest/api-v3/service/auth/v3/external_auth.proto). On each request, it:
1. Calls the enterprise token endpoint with service account credentials
2. Receives a fresh JWT
3. Returns the JWT in a response header that Agentgateway injects into the upstream request

A sample token-fetcher implementation is available at [`rvennam/token-fetcher`](https://hub.docker.com/r/rvennam/token-fetcher). It's a ~100 line Go service that:
1. Receives a gRPC ext-authz `Check` request from Agentgateway
2. POSTs to the enterprise token endpoint with service credentials
3. Extracts the JWT from the response
4. Returns it as a header in the ext-authz `OkHttpResponse.Headers` field, which Agentgateway injects into the upstream request

Source code: [`token-fetcher/main.go`](./token-fetcher/main.go)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: token-fetcher
  namespace: agentgateway-system
  labels:
    app: token-fetcher
spec:
  ports:
    - port: 9000
      targetPort: 9000
      protocol: TCP
      appProtocol: kubernetes.io/h2c
  selector:
    app: token-fetcher
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: token-fetcher
  namespace: agentgateway-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: token-fetcher
  template:
    metadata:
      labels:
        app: token-fetcher
    spec:
      containers:
        - name: token-fetcher
          image: rvennam/token-fetcher:latest
          ports:
            - containerPort: 9000
          env:
            - name: TOKEN_ENDPOINT
              value: "https://your-enterprise-idp/token"
            - name: TOKEN_REQUEST_BODY
              value: '{"input_token_state":{"token_type":"CREDENTIAL","username":"your_service_account","password":"your_password"},"output_token_state":{"token_type":"JWT"}}'
            - name: TOKEN_RESPONSE_FIELD
              value: "issued_token"
            - name: INJECT_HEADER_NAME
              value: "X-Corp-Trust-Token"
```

| Environment Variable | Description |
|---|---|
| `TOKEN_ENDPOINT` | URL to POST to for a fresh JWT |
| `TOKEN_REQUEST_BODY` | JSON body to send to the token endpoint |
| `TOKEN_RESPONSE_FIELD` | JSON field in the response containing the token (default: `issued_token`) |
| `INJECT_HEADER_NAME` | Header name to inject into the upstream request (default: `X-Corp-Trust-Token`) |

### Attach the ExtAuth Policy

Create an `EnterpriseAgentgatewayPolicy` that calls the token-fetcher on every request to the LLM route:

```yaml
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: llm-ext-auth
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
      name: llm-route
  traffic:
    extAuth:
      backendRef:
        name: token-fetcher
        namespace: agentgateway-system
        port: 9000
      grpc: {}
```

```bash
kubectl apply -f ext-auth.yaml
```

With this setup, kagent and the HTTPRoute stay exactly the same as Steps 1–4. The ExtAuth service runs transparently in front of every request:
- Tokens are always fresh — no 30-second expiry issues
- kagent has zero awareness of the enterprise auth flow
- The token-fetcher service is a simple gRPC server you control (~100 lines of code)

> **Note:** ExtAuth requires Enterprise Agentgateway. The static `RequestHeaderModifier` approach from Steps 1–4 works with both OSS and Enterprise.

---

## Summary

| Layer | Responsibility |
|---|---|
| **kagent** | AI agent with K8s tools, standard OpenAI API calls |
| **Agentgateway** | Header injection, auth management, observability |
| **Enterprise LLM** | Custom API with non-standard auth requirements |

```mermaid
flowchart LR
    subgraph kagent["kagent (existing)"]
        agent["K8s Agent"]
        model["ModelConfig<br/>baseUrl → Agentgateway"]
    end

    subgraph agw["Agentgateway"]
        route["HTTPRoute + RequestHeaderModifier"]
        headers["Adds enterprise headers<br/>X-Corp-Trust-Token<br/>x-correlation-id<br/>x-usersession-id"]
        logs["Access Logs + Metrics<br/>Token Usage Tracking"]
    end

    subgraph enterprise["Enterprise LLM"]
        llm["LLM API<br/>Custom Headers Required"]
    end

    agent --> model --> route --> headers --> llm
    headers --> logs

    style headers fill:#4CAF50,color:#fff
    style logs fill:#ff9800,color:#fff
    style llm fill:#2196F3,color:#fff
```

### What We Demonstrated

1. **Zero kagent changes** -- only the `baseUrl` in `ModelConfig` changes
2. **Custom header injection** -- enterprise-specific auth and metadata headers added via standard Gateway API `RequestHeaderModifier`
3. **Full observability** -- per-request token usage, model, and latency in structured JSON access logs
4. **Automatic token rotation** -- ExtAuth fetches fresh short-lived JWTs on every request (Enterprise)
5. **Clean separation of concerns** -- kagent handles AI, Agentgateway handles enterprise networking
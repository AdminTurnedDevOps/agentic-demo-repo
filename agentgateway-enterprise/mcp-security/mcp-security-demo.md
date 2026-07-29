## Env Setup

Below is the Gateway and MCP configuration that you can use to get this up and running.

### Gateway

```
export ANTHROPIC_API_KEY=

export GITHUB_PAT=
```

```
kubectl apply -f- <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: anthropic-secret
  namespace: agentgateway-system
type: Opaque
stringData:
  Authorization: $ANTHROPIC_API_KEY
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: github-pat
  namespace: agentgateway-system
type: Opaque
stringData:
  Authorization: "Bearer ${GITHUB_PAT}"
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: mcp-gateway-sec
  namespace: agentgateway-system
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
    - name: mcp
      port: 3000
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayBackend
metadata:
  name: github-mcp-server
  namespace: agentgateway-system
spec:
  entMcp:
    targets:
      - name: github-copilot
        static:
          host: api.githubcopilot.com
          port: 443
          path: /mcp/
          protocol: StreamableHTTP
          policies:
            tls: {}
            auth:
              secretRef:
                name: github-pat
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayBackend
metadata:
  name: anthropic
  namespace: agentgateway-system
spec:
  ai:
    provider:
      anthropic:
        model: "claude-sonnet-6"
  policies:
    ai:
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
  name: mcp-route
  namespace: agentgateway-system
spec:
  parentRefs:
    - name: mcp-gateway-sec
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
          group: enterpriseagentgateway.solo.io
          kind: EnterpriseAgentgatewayBackend
    - matches:
        - path:
            type: PathPrefix
            value: /mcp
      backendRefs:
        - name: github-mcp-server
          namespace: agentgateway-system
          group: enterpriseagentgateway.solo.io
          kind: EnterpriseAgentgatewayBackend
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: mcp-gateway-tracing
  namespace: agentgateway-system
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: mcp-gateway
  frontend:
    tracing:
      backendRef:
        group: ""
        kind: Service
        name: solo-enterprise-telemetry-collector
        namespace: kagent
        port: 4317
      protocol: GRPC
      clientSampling: "true"
      randomSampling: "true"
      resources:
      - name: service.name
        expression: '"mcp-gateway"'
      - name: deployment.environment.name
        expression: '"demo"'
      attributes:
        add:
        - name: request.host
          expression: 'request.host'
        - name: mcp.method_name
          expression: 'default(mcp.methodName, "")'
        - name: mcp.session_id
          expression: 'default(mcp.sessionId, "")'
        - name: mcp.tool_name
          expression: 'default(mcp.tool.name, "")'
        - name: backend.name
          expression: 'default(backend.name, "")'
    accessLog:
      otlp:
        backendRef:
          group: ""
          kind: Service
          name: solo-enterprise-telemetry-collector
          namespace: kagent
          port: 4317
        protocol: GRPC
      attributes:
        add:
        - name: gen_ai.tool.name
          expression: 'default(mcp.tool.name, "")'
        - name: mcp.tool_name
          expression: 'default(mcp.tool.name, "")'
        - name: mcp.tool_target
          expression: 'default(mcp.tool.target, "")'
        - name: mcp.method_name
          expression: 'default(mcp.methodName, "")'
EOF
```

```
export GATEWAY_IP=$(kubectl get svc mcp-gateway -n agentgateway-system -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo $GATEWAY_IP
```

```
curl "http://$GATEWAY_IP:3000/anthropic" \
  -H "content-type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "system": "You are a skilled cloud-native network engineer.",
    "messages": [
      {
        "role": "user",
        "content": "Write me a paragraph containing the best way to think about Istio Ambient Mesh"
      }
    ]
  }' | jq
```

Open MCP Inspector
```
npx modelcontextprotocol/inspector#0.18.0
```

## Agent Config

### Traffic Through Agentgateway From Kagent

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
  model: your_model
  provider: OpenAI
  openAI:
    baseUrl: http://$YOUR_GATEWAY$:8080/anthropic
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: mcpsec-testing
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

## Demo

### Prompt Guards

1. Create a policy to block against specific prompts
```
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: credit-guard-prompt-guard
  namespace: agentgateway-system
  labels:
    app: agentgateway-route
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: mcp-route
  backend:
    ai:
      promptGuard:
        request:
        - response:
            message: "Rejected due to inappropriate content"
          regex:
            action: Reject
            matches:
            - "credit card"
EOF
```

3. Test the `curl`
```
curl -v "http://$GATEWAY_IP:3000/anthropic" \
  -H "content-type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "system": "credit card person.",
    "messages": [
      {
        "role": "user",
        "content": "What is a credit card"
      }
    ]
  }' | jq
```

You should now see the `403 forbidden`
```
* upload completely sent off: 204 bytes
< HTTP/1.1 403 Forbidden
< content-length: 37
< date: Mon, 19 Jan 2026 12:56:34 GMT
```

4. Clean up the policy
```
kubectl delete -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: credit-guard-prompt-guard
  namespace: agentgateway-system
  labels:
    app: agentgateway-route
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: mcp-route
  backend:
    ai:
      promptGuard:
        request:
        - response:
            message: "Rejected due to inappropriate content"
          regex:
            action: Reject
            matches:
            - "credit card"
EOF
```

### MCP Auth

1. Get your MCP Gateway
```
kubectl get gateway -n agentgateway-system mcp-gateway
```

2. Open MCP Inspector in a new terminal
```
npx modelcontextprotocol/inspector#0.18.0
```

3. Specify, within the **URL** section, the following:
```
http://YOUR_ALB_IP:3000/mcp
```

You should now be able to see the connection without any security. This means that the MCP Server is wide open.

4. To implement auth security, add a gateway policy
```
kubectl apply -f- <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: jwt
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: mcp-gateway
  traffic:
    jwtAuthentication:
      providers:
        - issuer: solo.io
          jwks:
            inline: '{"keys": [{"kty": "RSA", "kid": "solo-public-key-001", "use": "sig", "alg": "RS256", "n": "vdV2XxH70WcgDKedYXNQ3Dy1LN8LKziw3pxBe0M-QG3_urCbN-oTPL2e0xrj5t2JOV-eBNaII17oZ6z9q84lLzn4mgU_UzP-Efv6iTZLlC_SD30AknifnoX8k38zbJtuwkvVcZvkam0LM5oIwSf4wJVpdPKHb3o_gGRpCBxWdQHPdBWMBPwOeqFfONFrM0bEnShFWf3d87EgckdVcrypelLyUZJ_ACdEGYUhS6FHmyojA1g6zKryAAWsH5Y-UCUuJd7VlOCMoBpAKK0BSdlF3WVSYHDlyMSB5H61eYCXSpfKcGhoHxViLgq6yjUR7TOHkJ-OtWna513TrkRw2Y0hsQ", "e": "AQAB"}]}'
EOF
```

5. Open the MCP Inspector and under **Authentication**, add in the following:
- Header Name: **Authorization**
- Bearer Token:
```
eyJhbGciOiJSUzI1NiIsImtpZCI6InNvbG8tcHVibGljLWtleS0wMDEiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJzb2xvLmlvIiwib3JnIjoic29sby5pbyIsInN1YiI6ImJvYiIsInRlYW0iOiJvcHMiLCJleHAiOjIwNzQyNzQ5NTQsImxsbXMiOnsibWlzdHJhbGFpIjpbIm1pc3RyYWwtbGFyZ2UtbGF0ZXN0Il19fQ.AZF6QKJJbnayVvP4bWVr7geYp6sdfSP-OZVyWAA4RuyjHMELE-K-z1lzddLt03i-kG7A3RrCuuF80NeYnI_Cm6pWtwJoFGbLfGoE0WXsBi50-0wLnpjAb2DVIez55njP9NVv3kHbVu1J8_ZO6ttuW6QOZU7AKWE1-vymcDVsNkpFyPBFXV7b-RIHFZpHqgp7udhD6BRBjshhrzA4752qovb-M-GRDrVO9tJhDXEmhStKkV1WLMJkH43xPSf1uNR1M10gMMzjFZgVB-kg6a1MRzElccpRum729c5rRGzd-_C4DsGm4oqBjg-bqXNNtUwNCIlmfRI5yeAsbeayVcnTIg
```

6. Clean up the policy
```
kubectl delete -f- <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: jwt
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: mcp-gateway
  traffic:
    jwtAuthentication:
      providers:
        - issuer: solo.io
          jwks:
            inline: '{"keys": [{"kty": "RSA", "kid": "solo-public-key-001", "use": "sig", "alg": "RS256", "n": "vdV2XxH70WcgDKedYXNQ3Dy1LN8LKziw3pxBe0M-QG3_urCbN-oTPL2e0xrj5t2JOV-eBNaII17oZ6z9q84lLzn4mgU_UzP-Efv6iTZLlC_SD30AknifnoX8k38zbJtuwkvVcZvkam0LM5oIwSf4wJVpdPKHb3o_gGRpCBxWdQHPdBWMBPwOeqFfONFrM0bEnShFWf3d87EgckdVcrypelLyUZJ_ACdEGYUhS6FHmyojA1g6zKryAAWsH5Y-UCUuJd7VlOCMoBpAKK0BSdlF3WVSYHDlyMSB5H61eYCXSpfKcGhoHxViLgq6yjUR7TOHkJ-OtWna513TrkRw2Y0hsQ", "e": "AQAB"}]}'
EOF
```

### MCP Traffic Policy (no tools)

1. Add the traffic policy
```
kubectl apply -f- <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: tool-select
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: agentgateway.dev
      kind: AgentgatewayBackend
      name: github-mcp-server
  backend:
    mcp:
      authorization:
        policy:
          matchExpressions:
            - 'mcp.tool.name == ""'
EOF
```

### MCP Traffic Policy (add tool)

1. Add the traffic policy
```
kubectl apply -f- <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: tool-select
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: agentgateway.dev
      kind: AgentgatewayBackend
      name: github-mcp-server
  backend:
    mcp:
      authorization:
        policy:
          matchExpressions:
            - 'mcp.tool.name == "get_me"'
EOF
```

2. Cleanup

```
kubectl delete -f- <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: tool-select
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: agentgateway.dev
      kind: AgentgatewayBackend
      name: github-mcp-server
  backend:
    mcp:
      authorization:
        policy:
          matchExpressions:
            - 'mcp.tool.name == "get_me"'
EOF
```

### Agentgateway Traffic Policy/Rate Limiting

1. Create a rate limit rule that targets the `HTTPRoute` you just created
```
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: traffic-policy
  namespace: agentgateway-system
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: mcp-route
  traffic:
    rateLimit:
      local:
        - requests: 1
          unit: Minutes
EOF
```


2. Capture the LB IP of the service to test again
```
export GATEWAY_IP=$(kubectl get svc mcp-gateway -n agentgateway-system -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo $GATEWAY_IP
```

3. Test the LLM connectivity
```
curl -v "http://$GATEWAY_IP:3000/anthropic" \
  -H "content-type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "system": "credit card person.",
    "messages": [
      {
        "role": "user",
        "content": "What is a credit card"
      }
    ]
  }' | jq
```

10. Run the `curl` again

You'll see a `curl` error that looks something like this:

```
< x-ratelimit-limit: 1
< x-ratelimit-remaining: 0
< x-ratelimit-reset: 76
< content-length: 19
< date: Tue, 18 Nov 2025 15:35:45 GMT
```

### Elicitation

MCP Elicitation is a human-in-the-loop feature that allows servers to dynamically pause tool execution and ask the user for missing parameters, clarification, or additional context.

Create or update the GitHub App used for OAuth elicitation:

1. In GitHub, open your profile menu and select **Settings**.
2. Select **Developer settings**, then **GitHub Apps**.
3. Select an existing app or click **New GitHub App**.
4. Set the homepage URL to `https://34.74.210.205/age/`.
5. Set the callback URL to `https://34.74.210.205/age/elicitations`.
6. Under **Webhook**, clear **Active**. OAuth elicitation does not require a webhook.
7. Click **Create GitHub App**. Client credentials are not shown until the app is created.
8. On the app's **General** settings page, copy the **Client ID**.
9. In the **Client secrets** section, click **Generate a new client secret**. Do not use a private key; private keys are for GitHub App JWT authentication, not this OAuth flow.
10. Copy the client secret immediately. GitHub displays it only once.

```bash
export GITHUB_CLIENT_ID=
export GITHUB_CLIENT_SECRET=
```

```bash
kubectl create secret generic elicitation-oidc -n agentgateway-system \
 --from-literal=type=oauth \
 --from-literal=title="GitHub" \
 --from-literal=instructions="## Authorize GitHub Access\n\nThis service needs access to your GitHub account to list repositories and manage pull requests on your behalf.\n\nClick **Authorize** to be redirected to GitHub to complete the OAuth flow." \
 --from-literal=client_id=${GITHUB_CLIENT_ID} \
 --from-literal=client_secret=${GITHUB_CLIENT_SECRET} \
 --from-literal=app_id=github \
 --from-literal=authorize_url=https://github.com/login/oauth/authorize \
 --from-literal=access_token_url=https://github.com/login/oauth/access_token \
 --from-literal=scopes=read:user \
 --from-literal=redirect_uri=https://34.74.210.205/age/elicitations \
 --dry-run=client -o yaml | kubectl apply -f -
```

```bash
helm upgrade --install agentgateway \
  oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway \
  --namespace agentgateway-system \
  --version v2026.7.0 \
  --reuse-values \
  --set tokenExchange.elicitation.secretName=elicitation-oidc \
  --set tokenExchange.apiValidator.validatorType=remote \
  --set-string tokenExchange.apiValidator.remoteConfig.url=https://login.microsoftonline.com/5e7d8166-7876-4755-a1a4-b476d4a344f6/discovery/v2.0/keys \
  --set tokenExchange.maintenance.enabled=true \
  --set-string controller.extraEnv.CALLBACK_URL=https://34.74.210.205/age/elicitations
```

This upgrades my existing agw control plane. If you don't already have a gateway for your traffic, follow [these docs](https://docs.solo.io/agentgateway/latest/mcp/token-exchange/elicitations/setup/#step-5-configure-the-proxy-for-token-exchange)

Those `env` variables below enable the `mcp-gateway` proxy (or whatever you decide to call your MCP gateway) to call the elicitation-aware STS endpoint:

- `STS_URI`: where token exchange and elicitation requests go.
- `STS_AUTH_TOKEN`: gateway service-account token used to authenticate to STS.

They enable the capability on the MCP gateway, but do not activate elicitation by themselves. The backend policy determines which traffic uses it.

```yaml
kubectl apply -f - <<'EOF'
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayParameters
metadata:
  name: mcp-gateway-elicitations
  namespace: agentgateway-system
spec:
  env:
    - name: STS_URI
      value: http://enterprise-agentgateway.agentgateway-system.svc.cluster.local:7777/elicitations/oauth2/token
    - name: STS_AUTH_TOKEN
      value: /var/run/secrets/xds-tokens/xds-token
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: mcp-gateway
  namespace: agentgateway-system
  labels:
    app: github-mcp-server
spec:
  gatewayClassName: enterprise-agentgateway
  infrastructure:
    parametersRef:
      group: enterpriseagentgateway.solo.io
      kind: EnterpriseAgentgatewayParameters
      name: mcp-gateway-elicitations
  listeners:
    - name: mcp
      port: 3000
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
EOF
```

The Elicitation policy targets only:

```
kind: EnterpriseAgentgatewayBackend
name: github-mcp-server
```

Therefore:
- Every request to github-mcp-server uses elicitation.
- Other MCP backends on mcp-gateway are unaffected.
- The gateway-level STS_URI only enables token-exchange capability; it does not force every backend to use it.
- Elicitation becomes broader only if you attach a policy to additional backends, routes, or the Gateway itself.

```yaml
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: github-mcp-elicitation
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: enterpriseagentgateway.solo.io
      kind: EnterpriseAgentgatewayBackend
      name: github-mcp-server
  backend:
    tokenExchange:
      elicitation:
        secretName: elicitation-oidc
EOF
```

Remove the static GitHub PAT authentication so the backend uses per-user OAuth elicitation instead.

```bash
kubectl patch enterpriseagentgatewaybackend github-mcp-server \
  -n agentgateway-system \
  --type=json \
  -p='[{"op":"remove","path":"/spec/entMcp/targets/0/static/policies/auth"}]'
```

```bash
kubectl rollout status deployment/enterprise-agentgateway -n agentgateway-system --timeout=60s
```

#### Test Elicitation

1. Clear previous ephemeral tokens:
```
kubectl rollout status deployment/enterprise-agentgateway \
  -n agentgateway-system --timeout=60s
```

2. Open the elicitation view:
https://34.74.210.205/age/elicitations


3. Open kagent:
https://34.74.210.205/ke/


4. Ask obo-readonly-agent:
`Use the GitHub MCP get_me tool to show my GitHub identity.`

5. The call should create a pending elicitation. Refresh /age/elicitations.

6. Click Authorize, complete GitHub consent, and return to the UI.

7. Retry the same prompt. It should now return the GitHub identity without another approval.

This requires the elicitation policy to be active and the static github-pat authentication removed. The controller restart makes the demo repeatable because your current token storage is ephemeral.

8. Restart the Gateway so you can reate a new pending elicitation if you want to show the process again

```
kubectl rollout restart deployment/enterprise-agentgateway \
  -n agentgateway-system
```

### Guardrails

MCP guardrails (also called ExtMCP) to apply external authorization and external processing to MCP requests.

Agentgateway supports both calling out to an external gRPC server so that you can centralize authorization and requesting or response mutation outside the proxy. However, these integrations operate on raw HTTP. To make a decision about an MCP tool call, the external server must reassemble the HTTP body, parse the JSON-RPC envelope, and handle MCP framing itself. MCP guardrails solve this challenge by calling out at the MCP method layer instead of the HTTP layer.

```
kubectl apply -f- <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: mcp-guardrails
spec:
  targetRefs:
    - group: enterpriseagentgateway.solo.io
      kind: EnterpriseAgentgatewayBackend
      name: github-mcp-server
  backend:
    mcp:
      guardrails:
        processors:
        - remote:
            backendRef:
              name: ext-mcp
              port: 4445
            failureMode: FailClosed
          methods:
            tools/call: Request
            tools/list: Response
EOF
```

The MCP methods to route through the policy server, and the phase for each.

- tools/call: Request sends each tool call to the server before it reaches the MCP backend, so the server can allow, mutate, or deny the call.
- tools/list: Response sends the tool listing to the server after the backend returns it, so the server can filter or annotate the list.

The `failureMode: FailClosed` Deny requests if the policy server is unreachable or returns an error. To allow requests instead, set `FailOpen`.

### Agent Identity

In the example below, you will see a policy that targets your enterprise agentgateway backend with the github copilot mcp server. Then, within `cel` expressions, you can match the expression to be your agent ID/identity and the target, along with whether or not it can access the target or not. Below the example is an agent named `mcpsec-testing` can only use MCP Server tools that start with `search_`, `get_`, or `list_`.

```yaml
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: github-mcp-rbac
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: enterpriseagentgateway.solo.io
      kind: EnterpriseAgentgatewayBackend
      name: github-mcp-server
  backend:
    mcp:
      authorization:
        action: Allow
        policy:
          matchExpressions:
            # Read-only persona — search/get/list + dedicated *_read tools
            - 'request.headers["x-agent-name"] == "mcpsec-testing" && (mcp.tool.name.startsWith("search_") || mcp.tool.name.startsWith("get_") || mcp.tool.name.startsWith("list_") || mcp.tool.name in ["issue_read", "pull_request_read"])'
            # Full persona — everything EXCEPT destructive/admin tools
            #- 'request.headers["x-agent-name"] == "mcpsec-testing" && !(mcp.tool.name in ["merge_pull_request", "delete_file", "run_secret_scanning"])'
EOF
```

### Progressive Disclosure

1. Apply the following with progressive disclosure enabled.

```
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayBackend
metadata:
  name: github-mcp-server
  namespace: agentgateway-system
spec:
  entMcp:
    toolMode: Search
    targets:
      - name: github-copilot
        static:
          host: api.githubcopilot.com
          port: 443
          path: /mcp/
          protocol: StreamableHTTP
          policies:
            tls: {}
            auth:
              secretRef:
                name: github-pat
EOF
```

2. Open MCP Inspector in a new terminal
```
npx modelcontextprotocol/inspector#0.18.0
```

3. Specify, within the **URL** section, the following:
```
http://YOUR_ALB_IP:3000/mcp
```

You should now only see `get_tool` and `invoke_tool`.

4. Revert the change.

```
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayBackend
metadata:
  name: github-mcp-server
  namespace: agentgateway-system
spec:
  entMcp:
    targets:
      - name: github-copilot
        static:
          host: api.githubcopilot.com
          port: 443
          path: /mcp/
          protocol: StreamableHTTP
          policies:
            tls: {}
            auth:
              secretRef:
                name: github-pat
EOF
```

With at least one `Allow` rule present, the policy is deny-by-default, so any request whose `X-Agent-Name` doesn't match a rule sees zero tools and gets zero authorizations.

And if you check the agentgateway Pod logs, you'll see the rate limit error.

## A Full OBO Flow Demo

https://github.com/AdminTurnedDevOps/agentic-demo-repo/blob/main/kagent-enterprise/obo/setup.md

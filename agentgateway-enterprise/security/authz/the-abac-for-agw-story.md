# ABAC With Agentgateway

agentgateway has multiple methods of implementing and helping with Attribute-Based Access Control (ABAC). The goal of this "doc" (which will hopefully turn into a real doc), is to be a living doc that as we go, we can add what works with agetngateway for ABAC.

For more info on ABAC: https://frontegg.com/guides/abac

## Implementations

1. Guardrails

Because the guardrail webhook is your own service, you can make it attribute-aware. If agentgateway passes enough context for your use case, or if you can derive it from headers/body/session/token context available to the webhook.

With Agentgateway 2.1.x, the guardrail webhook is a synchronous hook that Agentgateway calls before the LLM request and after the LLM response.

If you google guarddrails, you'll see an explanation about it being real-time policy enforcement. If it is "real-time policy enforcement", that means the guarddrail webhook can work with a policy enforcement tool like OPA or Kyverno. For example, if a request comes into agentgateway, the guarddrails webhook can call to OPA or Kyverno to ensure that the policies that are set are met.

Client → Agentgateway → Guardrail webhook → OPA or Kyverno → webhook returns allow/modify/reject → Agentgateway continues or blocks

Use ABAC for:
- who can access which route/model/tool
- tenant/team/role/claim-based decisions
- environment-aware authorization decisions

Use guardrails for:
- PII masking
- prompt/response moderation
- output schema/JSON validation
- jailbreak/injection inspection
- response redaction or rewriting

Example (ABAC-aware webhook + policy):

```yaml
# 1) Attach a guardrail webhook to request + response phases
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: openai-prompt-guard
  namespace: agentgateway-system
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: openai
  backend:
    ai:
      promptGuard:
        request:
        - webhook:
            backendRef:
              kind: Service
              name: ai-guardrail-webhook
              port: 8000
        response:
        - webhook:
            backendRef:
              kind: Service
              name: ai-guardrail-webhook
              port: 8000
```

```python
# 2) Guardrail webhook logic example (attribute-aware ABAC decision)
#    - Enforce claim- and model-based access
#    - Optionally call OPA/Kyverno for central policy
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)
OPA_URL = "http://opa.opa.svc.cluster.local:8181/v1/data/agw/allow"

@app.post("/guardrail")
def guardrail():
    payload = request.get_json(force=True)

    claims = payload.get("jwt", {})
    route = payload.get("route", "")
    model = payload.get("llm", {}).get("model", "")
    user_text = str(payload.get("requestBody", ""))

    # Local ABAC checks
    if claims.get("team") != "platform":
        return jsonify({"decision": "reject", "message": "team is not allowed"}), 403
    if route == "openai-admin" and claims.get("role") != "admin":
        return jsonify({"decision": "reject", "message": "admin route requires admin role"}), 403
    if model.startswith("gpt-4") and claims.get("tier") not in ["pro", "enterprise"]:
        return jsonify({"decision": "reject", "message": "model not allowed for plan"}), 403

    # Optional external policy call
    opa = requests.post(OPA_URL, json={"input": payload}, timeout=0.3)
    if not opa.ok or not opa.json().get("result", False):
        return jsonify({"decision": "reject", "message": "denied by OPA"}), 403

    # Example content rewrite
    rewritten = user_text.replace("ssn", "***")
    return jsonify({"decision": "allow", "requestBody": rewritten}), 200
```


2. MCP Server Tool Access

Tools can be exposed and seen based on a policy from policy enforcement. It dynamically adjusts so Agents can only see the tools they have access to.

The [tool-access guide](https://docs.solo.io/agentgateway/2.1.x/mcp/tool-access/) shows CEL expressions over both JWT claims and resource attributes like tool name, for example:

```
jwt.sub == "alice"

mcp.tool.name == "add_issue_comment"

jwt.sub == "alice" && mcp.tool.name == "add_issue_comment"
```

Example (tool-level ABAC):

```yaml
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: mcp-tool-access
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: agentgateway.dev
      kind: AgentgatewayBackend
      name: github-mcp-backend
  backend:
    mcp:
      authorization:
        action: Allow
        policy:
          matchExpressions:
            # Only alice can see/use get_me
            - 'jwt.sub == "alice" && mcp.tool.name == "get_me"'
            # Example: ops team can use incident tools
            - 'jwt.team == "ops" && mcp.tool.name.startsWith("incident_")'
```


3. BYO Policy Enforcement

You can use OPA, Kyverno, or any other policy enforcement platform/tool you'd like within your environment. Agentgateway can call out to it for authorization decisions.

BYO external auth means that agentgateway can call your gRPC external authorization service with headers, path, and method, and that service can make decisions using tokens, headers, database lookups, etc. It can also optionally inject headers back into the request. That is the right path when your policy depends on business data like account tier, project membership, entitlements, or time-based rules.

https://docs.solo.io/agentgateway/2.1.x/security/extauth/byo-ext-auth-service/

Sidenote: For attribute enrichment, ExtProc is useful when the attributes are not already present as headers/claims. The docs say ExtProc can read and modify headers, body, and trailers, and can terminate the request.

Example (external auth service + gateway policy):

```yaml
# External auth policy on the Gateway
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  namespace: agentgateway-system
  name: gateway-ext-auth-policy
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: agentgateway-proxy
  traffic:
    extAuth:
      backendRef:
        name: ext-authz
        namespace: agentgateway-system
        port: 4444
      grpc: {}
```

```rego
# OPA policy example your ext-auth service can evaluate
package agw.authz

default allow = false

allow if {
  input.jwt.claims.org == "acme"
  input.jwt.claims.project == "payments"
  input.request.path == "/openai"
  input.request.headers["x-llm"] == "gpt-4o-mini"
}
```


4. Token Exchange

On-Behalf-Of/Elicitation. This feeds ABAC because the exchanged tokens carry scoped claims/attributes that downstream policy engines can evaluate.

Example (enable STS token exchange for OBO + enforce STS-issued JWT):

```yaml
# Helm values (enterprise-agentgateway) to enable OBO token exchange
tokenExchange:
  enabled: true
  issuer: "enterprise-agentgateway.agentgateway-system.svc.cluster.local:7777"
  tokenExpiration: 24h
  subjectValidator:
    validatorType: remote
    remoteConfig:
      url: "${KEYCLOAK_JWKS_URI}"
  actorValidator:
    validatorType: k8s
```

```yaml
# Require STS-issued token on MCP route
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: jwt-policy
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
      name: mcp
  traffic:
    jwtAuthentication:
      mode: Strict
      providers:
      - issuer: enterprise-agentgateway.agentgateway-system.svc.cluster.local:7777
        jwks:
          inline: '${KEYCLOAK_CERT_KEYS}'
```

```yaml
# Elicitation-only mode for upstream OAuth token collection/injection
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: token-exchange-elicit-service
  namespace: httpbin
spec:
  targetRefs:
    - group: ""
      kind: Service
      name: httpbin
  backend:
    tokenExchange:
      mode: ElicitationOnly
```

5. CEL

Common Expression Language is very similar to, if you need a comparison, if statements/logic. You can specify, from a transformation policy perspective, requests or responses on specific parameters.

Agentgateway’s CEL-based auth can evaluate request attributes. Agentgateway proxies use CEL expressions to match requests or responses on parameters such as request headers or source address, and allow/deny based on whether the condition matches.


Please note, this is more coarse-grained than fine-grained, but it's a good RBAC primitive to have if you have any workflows that require the standard roles/permissions approach.

Example:
```yaml
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: rbac-policy
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
      name: google
  traffic:
    authorization:
      action: Allow
      policy:
        matchExpressions:
          - "request.headers['x-llm'] == 'gemini'"
```

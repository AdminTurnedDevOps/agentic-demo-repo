# Agentgateway Enterprise ABAC Demo (Enterprise ExtAuth + OPA)

This demo implements ABAC for Agentgateway Enterprise 2.1.x using:

- `EnterpriseAgentgatewayPolicy` with `traffic.entExtAuth`
- built-in Enterprise ExtAuth service (default backend behavior, no `backendRef`)
- `AuthConfig` (`extauth.solo.io/v1`) with `opaServerAuth`
- OPA as the allow/deny policy engine
- `AgentgatewayBackend` pointing to Anthropic Claude

Flow:

`Client -> Agentgateway -> Enterprise ExtAuth -> OPA -> allow/deny -> ExtAuth -> Agentgateway -> Claude`

## Files

- `manifests/gateway.yaml` (contains Namespace + Gateway + AgentgatewayBackend + HTTPRoute)
- `opa-install.md` (Helm install instructions for OPA + ConfigMap-mounted Rego)
- `manifests/enterprise-agentgateway-policy.yaml` (contains AuthConfig + EnterpriseAgentgatewayPolicy)
- `opa/policy.rego`
- `docs/architecture.md`
- `scripts/setup.sh`
- `scripts/test-allow.sh`
- `scripts/test-deny.sh`
- `scripts/test-admin-allow.sh`
- `scripts/test-admin-deny.sh`
- `scripts/test-default-deny.sh`

## Deploy AGW and OPA

```bash
cd agentgateway-enterprise/security/authz/abac

export ANTHROPIC_API_KEY=<your-anthropic-api-key>

kubectl apply -f manifests/gateway.yaml
kubectl -n abac-demo create secret generic anthropic-secret \
  --from-literal=Authorization="$ANTHROPIC_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f manifests/enterprise-agentgateway-policy.yaml
```

Install OPA via Helm + mount Rego from `opa/policy.rego`:

```bash
kubectl -n abac-demo create configmap opa-policy \
  --from-file=policy.rego=opa/policy.rego \
  --dry-run=client -o yaml | kubectl apply -f -

helm repo add open-policy-agent https://open-policy-agent.github.io/kube-mgmt/charts
helm repo update
helm upgrade --install opa open-policy-agent/opa \
  -n abac-demo \
  --set service.type=ClusterIP \
  --set service.port=8181 \
  --set "extraVolumes[0].name=opa-policy" \
  --set "extraVolumes[0].configMap.name=opa-policy" \
  --set "extraVolumeMounts[0].name=opa-policy" \
  --set "extraVolumeMounts[0].mountPath=/policies" \
  --set "extraArgs[0]=run" \
  --set "extraArgs[1]=--server" \
  --set "extraArgs[2]=--addr=0.0.0.0:8181" \
  --set "extraArgs[3]=/policies/policy.rego"
```

Optional checks:

```bash
kubectl -n abac-demo get deploy,svc,pods
kubectl -n abac-demo get enterpriseagentgatewaypolicy abac-ent-extauth
```

Port-forward Gateway:

```bash
kubectl -n abac-demo port-forward svc/abac-gateway 3000:3000
```

Optional shortcut:

```bash
./scripts/setup.sh
```

## Run tests

```bash
./scripts/test-allow.sh
./scripts/test-deny.sh
./scripts/test-admin-allow.sh
./scripts/test-admin-deny.sh
./scripts/test-default-deny.sh
```

## Expected outcomes

- `test-allow.sh`: allow by ABAC, request forwarded to Claude path (`/v1/messages`)
- `test-deny.sh`: denied by ABAC before Claude call
- `test-admin-allow.sh`: allow by ABAC, request forwarded to Claude path
- `test-admin-deny.sh`: denied by ABAC before Claude call
- `test-default-deny.sh`: denied by ABAC (missing attributes)

## What it enforces

- Tenant isolation
  - `x-tenant: acme` can only access `/acme`
  - `x-tenant: contoso` can only access `/contoso`
- Team-based admin access
  - only `x-team: engineering` can access `/admin`
- Role restriction
  - `x-role: contractor` is denied for `/admin`
  - `x-role: employee` may pass if other rules pass
- Default deny when required headers are missing

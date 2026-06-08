# kagent Runtime Setup

This guide registers an existing kagent installation as an AgentRegistry Enterprise runtime, then deploys an image-backed Agent to kagent.

## 1. Register the kagent Runtime

Create the runtime manifest:

```bash
cat > /tmp/kagent-runtime.yaml <<'EOF'
apiVersion: ar.dev/v1alpha1
kind: Runtime
metadata:
  name: kagent
spec:
  type: Kagent
  telemetryEndpoint: http://agentregistry-enterprise-telemetry-collector.agentregistry-system.svc.cluster.local:4318
  config:
    kagentUrl: http://kagent-controller.kagent.svc.cluster.local:8083
    namespace: kagent
EOF
```

Apply it:

```bash
arctl apply -f /tmp/kagent-runtime.yaml
arctl get runtimes
```

Expected result: a runtime named `kagent` with type `Kagent`.

### Auth Mode for This Demo

For this demo environment, the kagent controller must accept the `X-User-Id` header that AgentRegistry sends when it creates kagent resources. Enable kagent's unsecure controller auth mode:

```bash
kubectl set env deployment/kagent-controller -n kagent INSECURE_MODE=true
kubectl rollout status deployment/kagent-controller -n kagent --timeout=5m
```

Verify the kagent API accepts requests from the AgentRegistry pod:

```bash
kubectl exec -n agentregistry-system deployment/agentregistry-enterprise-server -- \
  curl -i -H 'X-User-Id: admin@kagent.dev' \
  'http://kagent-controller.kagent.svc.cluster.local:8083/api/agents?namespace=kagent'
```

Expected result: `HTTP/1.1 200 OK`.

> **Demo-only note:** `INSECURE_MODE=true` disables kagent controller authn/authz. Use it only for demos or isolated development clusters. For production-style deployments, configure kagent and AgentRegistry to use compatible OIDC token audience/issuer settings or a token-exchange flow.

> **Helm note:** The live demo validated this with `kubectl set env`. If you manage kagent exclusively through Helm, persist the same env var in Helm values under `controller.env` so a future `helm upgrade` does not remove it.

## 2. Register an Agent for kagent

The k8shelper image must contain the model-selection fix from `agentregistry/k8shelper/k8shelper/agent.py`, which reads `MODEL_NAME` from the environment:

```python
return os.getenv("MODEL_NAME", "gemini-3.5-flash")
```

Build and push the image first. Replace the image value with a registry you can push to and that your cluster can pull from:

```bash
# Run from the root of agentic-demo-repo.
cd agentregistry/k8shelper

export K8SHELPER_IMAGE="<your-registry>/k8shelper:model-fix"
docker buildx build --platform linux/amd64 -t "${K8SHELPER_IMAGE}" --push .
```

Create a Kubernetes Secret for the Gemini API key. Do not put API keys directly in the AgentRegistry manifest:

```bash
kubectl create secret generic k8shelper-google \
  -n kagent \
  --from-literal=GOOGLE_API_KEY="${GOOGLE_API_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Save the following in a file called `k8shelper.yaml`:

```yaml
apiVersion: ar.dev/v1alpha1
kind: Agent
metadata:
  name: k8shelper
  tag: "1.0.0"
spec:
  title: k8shelper
  description: "Kubernetes helper agent deployed through the kagent runtime"
  modelProvider: gemini
  modelName: gemini-3.5-flash
  source:
    image: ${K8SHELPER_IMAGE}
```

Apply it:

```bash
envsubst < k8shelper.yaml | arctl apply -f -
arctl get agents
```

## 3. Deploy the Agent to kagent

Create a Deployment that targets the `kagent` runtime. Save the following as `ardeploy.yaml`

```yaml
apiVersion: ar.dev/v1alpha1
kind: Deployment
metadata:
  name: k8shelper-kagent
spec:
  targetRef:
    kind: Agent
    name: k8shelper
    tag: "1.0.0"
  runtimeRef:
    kind: Runtime
    name: kagent
  env:
    MODEL_PROVIDER: gemini
    MODEL_NAME: gemini-3.5-flash
```

Apply it:

```bash
arctl apply -f ardeploy.yaml
```

Patch the generated kagent Agent CR to reference the Google API key Secret. AgentRegistry `Deployment.spec.env` supports literal values, but this Secret reference must be added on the generated kagent resource:

```bash
kubectl patch agent k8shelper -n kagent --type='json' -p='[
  {"op":"add","path":"/spec/byo/deployment/env/-","value":{"name":"GOOGLE_API_KEY","valueFrom":{"secretKeyRef":{"name":"k8shelper-google","key":"GOOGLE_API_KEY"}}}}
]'

kubectl rollout status deployment/k8shelper -n kagent --timeout=5m
```

The deployment should move from `deploying` to `deployed` / `Ready=True`.

## 4. Verify in Kubernetes

AgentRegistry creates a kagent `Agent` CR in the runtime namespace. For the example above, check:

```bash
kubectl get agents.kagent.dev -n kagent k8shelper -o yaml
kubectl get pods -n kagent -l kagent=k8shelper
kubectl get svc -n kagent -l kagent=k8shelper
kubectl get deploy k8shelper -n kagent -o yaml | grep -E 'MODEL_NAME|MODEL_PROVIDER|GOOGLE_API_KEY|image:'
```

If the Agent name contains characters that are not valid in Kubernetes resource names, AgentRegistry sanitizes it before creating the kagent CR.

## Troubleshooting

If the AgentRegistry Deployment fails, inspect the status condition:

```bash
arctl get deployment k8shelper-kagent -o yaml
```

Common issues:

- `image must be specified`: kagent requires `spec.source.image` on the Agent.
- `kagent URL is required`: the runtime is missing `spec.config.kagentUrl`.
- `authentication token expired during deployment; please retry`: AgentRegistry maps any kagent API `401` to this message. It does not always mean the token is old. It can also mean the kagent controller endpoint rejected the forwarded AgentRegistry bearer token or expected a browser/session-based kagent identity instead.
- Image pull failures: the image must be public or the runtime must include image pull secrets that exist in the kagent namespace.
- Gemini `429 RESOURCE_EXHAUSTED` for `gemini-2.0-flash`: the old demo image hardcoded `gemini-2.0-flash`. Rebuild and deploy the patched image from this repo so `MODEL_NAME=gemini-3.5-flash` is honored.

For Entra-authenticated installs, refreshing the CLI token is worth trying first:

```bash
arctl apply -f ardeploy.yaml
arctl get deployment k8shelper-kagent -o yaml
```

If the same error returns immediately with a fresh token, check the kagent controller API auth behavior from inside the AgentRegistry pod:

```bash
kubectl exec -n agentregistry-system deployment/agentregistry-enterprise-server -- \
  curl -i -H 'X-User-Id: admin@kagent.dev' \
  'http://kagent-controller.kagent.svc.cluster.local:8083/api/agents?namespace=kagent'
```

If that returns `no session found` or `401 Unauthorized`, enable `INSECURE_MODE=true` for the demo as shown above, then re-apply the Deployment. Re-applying the Deployment will not fix it until the runtime points at a kagent API endpoint that accepts the forwarded identity or unauthenticated/X-User-Id requests.

To deploy into another namespace, either update `spec.config.namespace` on the Runtime or create a second Runtime with a different name and namespace.

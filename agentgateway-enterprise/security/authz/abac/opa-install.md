# OPA Installation (Helm)

Install OPA in `abac-demo` via Helm and mount the ABAC Rego policy from `opa/policy.rego`.

## 1) Ensure namespace exists

```bash
kubectl apply -f manifests/gateway.yaml
```

`manifests/gateway.yaml` includes the `abac-demo` Namespace.

## 2) Create/update ConfigMap from local Rego policy

```bash
kubectl -n abac-demo create configmap opa-policy \
  --from-file=policy.rego=opa/policy.rego \
  --dry-run=client -o yaml | kubectl apply -f -
```

## 3) Add OPA Helm repo

```bash
helm repo add open-policy-agent https://open-policy-agent.github.io/kube-mgmt/charts
helm repo update
```

## 4) Install/upgrade OPA with mounted ConfigMap

`opa/policy.rego` is a repo-local file. The ConfigMap mounts it into the OPA container at `/policies/policy.rego`, which is why the OPA runtime arg points to `/policies/policy.rego`.

```bash
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

## 5) Verify

```bash
kubectl -n abac-demo get deploy,svc,pods -l app.kubernetes.io/name=opa
kubectl -n abac-demo get svc opa
```

The AuthConfig in `manifests/enterprise-agentgateway-policy.yaml` points to:

- `serverAddr: opa.abac-demo.svc.cluster.local:8181`

So the Service name must remain `opa` in namespace `abac-demo`.

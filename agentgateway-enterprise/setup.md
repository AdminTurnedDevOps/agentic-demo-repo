```
export AGENTGATEWAY_LICENSE_KEY=
```

```
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml 
```

```
helm upgrade -i enterprise-agentgateway-crds oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway-crds \
  --version v2.2.0 \
  --namespace agentgateway-system \
  --reuse-values
```

```
helm upgrade -i enterprise-agentgateway oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway \
  -n agentgateway-system  \
  --version v2.2.0 \
  --set agentgateway.enabled=true \
  --set extAuthServer.enabled=true \
  --set licensing.licenseKey=${AGENTGATEWAY_LICENSE_KEY}
```

```
helm upgrade -i management oci://us-docker.pkg.dev/solo-public/solo-enterprise-helm/charts/management \
--namespace agentgateway-system \
--create-namespace \
--version 0.3.7 \
--set cluster="mgmt-cluster" \
--set tracing.verbose=true \
--set telemetry.traces.enabled=true \
--set products.agentgateway.enabled=true
```

```
kubectl get pods -n agentgateway-system
```
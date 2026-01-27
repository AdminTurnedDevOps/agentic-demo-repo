```
export AGENTGATEWAY_LICENSE_KEY=
```

```
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml 
```

```
helm upgrade -i agentgateway-crds oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway-crds \
  --create-namespace \
  --namespace agentgateway-system  \
  --version 2.1.0-rc.2
```

```
helm upgrade -i agentgateway oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway \
  -n agentgateway-system  \
  --version 2.1.0-rc.2 \
  --set agentgateway.enabled=true \
  --set licensing.licenseKey=${AGENTGATEWAY_LICENSE_KEY}
```

```
kubectl get pods -n agentgateway-system
```
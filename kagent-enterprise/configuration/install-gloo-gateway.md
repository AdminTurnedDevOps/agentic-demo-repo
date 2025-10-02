```
export CLUSTER1=
```

```
export GLOO_GATEWAY_LICENSE_KEY=
export AGENTGATEWAY_LICENSE_KEY=
```

```
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/standard-install.yaml
```

```
helm upgrade -i gloo-gateway-crds oci://us-docker.pkg.dev/solo-public/gloo-gateway/charts/gloo-gateway-crds \
  --create-namespace \
  --namespace gloo-system \
  --version 2.0.0-rc.1

helm upgrade -i gloo-gateway oci://us-docker.pkg.dev/solo-public/gloo-gateway/charts/gloo-gateway \
  -n gloo-system \
  --version 2.0.0-rc.1 \
  --set agentgateway.enabled=true \
  --set licensing.agentgatewayLicenseKey=$AGENTGATEWAY_LICENSE_KEY \
  --set licensing.glooGatewayLicenseKey=$GLOO_GATEWAY_LICENSE_KEY
```

```
kubectl get pods -n gloo-system --context=$CLUSTER1
```
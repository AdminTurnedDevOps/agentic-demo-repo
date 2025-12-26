## Enterprise

```
export GLOO_GATEWAY_LICENSE_KEY=
export AGENTGATEWAY_LICENSE_KEY=
```

```
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml
```

```
helm upgrade -i --create-namespace --namespace gloo-system --version v2.0.0-main gloo-gateway-crds oci://us-docker.pkg.dev/solo-public/gloo-gateway/charts/gloo-gateway-crds
```

```
helm upgrade -i -n gloo-system gloo-gateway oci://us-docker.pkg.dev/solo-public/gloo-gateway/charts/gloo-gateway \
--version v2.0.0-main \
--set gateway.aiExtension.enabled=true \
--set agentgateway.enabled=true \
--set licensing.glooGatewayLicenseKey=$GLOO_GATEWAY_LICENSE_KEY \
--set licensing.agentgatewayLicenseKey=$AGENTGATEWAY_LICENSE_KEY
```

## OSS

```
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml
```

```
helm upgrade -i --create-namespace --namespace kgateway-system --version v2.2.0-main \
kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds \
--set controller.image.pullPolicy=Always
```

```
helm upgrade -i --namespace kgateway-system --version v2.2.0-main kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway \
  --set gateway.aiExtension.enabled=true \
  --set agentgateway.enabled=true  \
  --set controller.image.pullPolicy=Always
```

```
kubectl get pods -n kgateway-system
```
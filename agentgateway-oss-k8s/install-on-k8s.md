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
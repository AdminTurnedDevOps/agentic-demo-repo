```
helm upgrade --install substrate-crds \
oci://ghcr.io/kagent-dev/substrate/helm/substrate-crds
```

```
helm upgrade --install substrate \
oci://ghcr.io/kagent-dev/substrate/helm/substrate \
--namespace ate-system --create-namespace
```
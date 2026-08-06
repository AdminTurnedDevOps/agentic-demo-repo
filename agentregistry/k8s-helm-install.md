

## Bundled Postgres

```bash
helm upgrade --install agentregistry \
  oci://ghcr.io/agentregistry-dev/agentregistry/charts/agentregistry \
  --namespace agentregistry \
  --create-namespace
```

```bash
kubectl -n agentregistry port-forward svc/agentregistry 12121:12121
```

With an LB for the service:

```bash
helm upgrade --install agentregistry \
  oci://ghcr.io/agentregistry-dev/agentregistry/charts/agentregistry \
  --namespace agentregistry \
  --create-namespace \
  --set service.type=LoadBalancer
```

Access the ui: `http://34.73.63.97:12121`

## External Postgres

```
helm install my-agentregistry \
  oci://ghcr.io/agentregistry-dev/agentregistry/charts/agentregistry \
  --set database.postgres.type=external \
  --set database.postgres.external.url='postgres://USER:PASS@HOST:5432/DB'
```
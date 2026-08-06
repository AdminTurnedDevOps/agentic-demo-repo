

## Bundled Postgres

```
helm upgrade --install agentregistry \
  oci://ghcr.io/agentregistry-dev/agentregistry/charts/agentregistry \
  --namespace agentregistry \
  --create-namespace
```

With an LB for the service:
```
helm upgrade --install agentregistry \
  oci://ghcr.io/agentregistry-dev/agentregistry/charts/agentregistry \
  --namespace agentregistry \
  --create-namespace \
  --set service.type=LoadBalancer
```

## External Postgres

```
helm install my-agentregistry \
  oci://ghcr.io/agentregistry-dev/agentregistry/charts/agentregistry \
  --set database.postgres.type=external \
  --set database.postgres.external.url='postgres://USER:PASS@HOST:5432/DB'
```
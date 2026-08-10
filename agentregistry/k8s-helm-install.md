

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

Access the ui: `http://YOUR_ALB_IP:12121`

### Enabling The Plugin Marketplace

The below env var enabled the plugin marketin
```bash
--set-json 'extraEnvVars=[{"name":"AGENT_REGISTRY_PLUGIN_MARKETPLACE_COMPAT_ENABLED","value":"true"}]'
```

```bash
helm upgrade --install agentregistry \
  oci://ghcr.io/agentregistry-dev/agentregistry/charts/agentregistry \
  --namespace agentregistry \
  --create-namespace \
  --set-json 'extraEnvVars=[{"name":"AGENT_REGISTRY_PLUGIN_MARKETPLACE_COMPAT_ENABLED","value":"true"}]'
```

## External Postgres

```
helm install my-agentregistry \
  oci://ghcr.io/agentregistry-dev/agentregistry/charts/agentregistry \
  --set database.postgres.type=external \
  --set database.postgres.external.url='postgres://USER:PASS@HOST:5432/DB'
```
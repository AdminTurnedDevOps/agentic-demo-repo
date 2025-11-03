export CLUSTER_NAME=agentgateway-mlevan
echo $CLUSTER_NAME

```
helm repo add gloo-platform https://storage.googleapis.com/gloo-platform/helm-charts
helm repo update
```

```
helm upgrade -i gloo-platform-crds gloo-platform/gloo-platform-crds \
--namespace=gloo-system \
--version=2.10.2 \
--set installEnterpriseCrds=false
```

```
helm upgrade -i gloo-platform gloo-platform/gloo-platform \
--namespace gloo-system \
--version=2.10.2 \
-f - <<EOF
common:
  adminNamespace: "gloo-system"
  cluster: $CLUSTER_NAME
glooInsightsEngine:
  enabled: true
glooAnalyzer:
  enabled: true
glooUi:
  enabled: true
licensing:
  glooGatewayLicenseKey: $GLOO_GATEWAY_LICENSE_KEY
prometheus:
  enabled: true
telemetryCollector:
  enabled: true
  mode: deployment
  replicaCount: 1
EOF
```

```
kubectl port-forward deployment/gloo-mesh-ui -n gloo-system 8090
```
## Set Environment Variables

```
export ANTHROPIC_API_KEY=
export CLUSTER1=
export CLUSTER1_NAME=
export KEYCLOAK_IP=
export OIDC_BACKEND=
export OIDC_FRONTEND=
export BACKEND_CLIENT_SECRET=
export ENDPOINT=
export OIDC_ISSUER=
```

## Install Kagent Enterprise (Mgmt Cluster)

```
helm upgrade -i kagent-enterprise \
oci://us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts/management \
-n kagent --create-namespace \
--version 0.1.2 \
-f - <<EOF
cluster: ${CLUSTER1}
ui:
  backend:
    oidcClientId: ${OIDC_BACKEND}
    oidcSecret: ${BACKEND_CLIENT_SECRET}
    oidcIssuer: ${OIDC_ISSUER}
  frontend:
    clientId: ${OIDC_FRONTEND}
    authEndpoint: ${AUTH_ENDPOINT}/auth
    logoutEndpoint: ${AUTH_ENDPOINT}/logout
    tokenEndpoint: ${AUTH_ENDPOINT}/token
EOF
```

```
kubectl get pods -n kagent --context=$CLUSTER1
```

```
helm upgrade -i kagent-crds \
oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
-n kagent \
--version 0.6.12
```

```
helm upgrade -i kagent \
oci://ghcr.io/kagent-dev/kagent/helm/kagent \
-n kagent \
--version 0.6.12 \
--values - <<EOF
providers:
  default: anthropic
  anthropic:
    apiKey: ${ANTHROPIC_API_KEY}
otel:
  tracing:
    enabled: true
    exporter:
      otlp:
        endpoint: kagent-enterprise-ui.kagent.svc.cluster.local:4317
        insecure: true
kagent-tools:
  anthropic:
    apiKey: ${ANTHROPIC_API_KEY}
  otel:
    tracing:
      enabled: true
      exporter:
        otlp:
          endpoint: kagent-enterprise-ui.kagent.svc.cluster.local:4317
          insecure: true
EOF
```

```
kubectl get pods -n kagent
```

To access the UI locally:

```
kubectl port-forward svc/kagent-enterprise-ui -n kagent 8081:80

kubectl port-forward svc/kagent-enterprise-ui -n kagent 8090:8090
```

## Install Kagent Enterprise/Relay (Worker Cluster)

```
export TUNNEL_ADDRESS=$(kubectl get svc -n kagent kagent-enterprise-ui --context $CLUSTER1 -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")
echo $TUNNEL_ADDRESS
```

```
kubectl apply --context=$CLUSTER1 -f- <<EOF
apiVersion: kagent-enterprise.solo.io/v1alpha1
kind: KubernetesCluster
metadata:
  name: $CLUSTER2_NAME
  namespace: kagent
EOF
```

```
helm upgrade -i relay \
oci://us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts/relay \
--kube-context $CLUSTER2 \
-n kagent --create-namespace \
--version 0.1.0 \
--set cluster=$CLUSTER2 \
--set tunnel.endpoint=${TUNNEL_ADDRESS} \
--set telemetry.endpoint=${TUNNEL_ADDRESS}
```

```
kubectl get po -n kagent --context=$CLUSTER2
```

```
helm upgrade -i kagent-crds \
oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
--kube-context $CLUSTER2 \
-n kagent \
--version 0.6.12

helm upgrade -i kagent \
oci://ghcr.io/kagent-dev/kagent/helm/kagent \
--kube-context $CLUSTER2 \
-n kagent \
--version 0.6.12 \
-f - <<EOF
providers:
  default:
    anthropic
  anthropic:
    apiKey: $ANTHROPIC_API_KEY  
otel:
  tracing:
    enabled: true
    exporter:
      otlp:
        endpoint: kagent-enterprise-ui.kagent.svc.cluster.local:4317
        insecure: true
kagent-tools:
  anthropic:
    apiKey: $ANTHROPIC_API_KEY
  otel:
    tracing:
      enabled: true
      exporter:
        otlp:
          endpoint: kagent-enterprise-ui.kagent.svc.cluster.local:4317
          insecure: true
EOF
```

## Access UI
```bash
kubectl get svc kagent-enterprise-ui -n kagent
```
Access at: http://KAGENT_UI_IP
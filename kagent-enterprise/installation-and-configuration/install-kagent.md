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
export ISTIO_VERSION=1.27.2
export ISTIO_IMAGE=
export REPO_KEY=
export REPO=us-docker.pkg.dev/gloo-mesh/istio-$REPO_KEY
export HELM_REPO=us-docker.pkg.dev/gloo-mesh/istio-helm-$REPO_KEY
```

## Ambient Installation

For Solo Enterprise For kagent to have everything from:
- Observability
- Tracing
- Authentication
- Multi-cluster support
- Policy enforcement

Istio Ambient Mesh is needed

### Kubernetes Gateway API
```
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/standard-install.yaml
```

### Istioctl Install
```
OS=$(uname | tr '[:upper:]' '[:lower:]' | sed -E 's/darwin/osx/')
ARCH=$(uname -m | sed -E 's/aarch/arm/; s/x86_64/amd64/; s/armv7l/armv7/')
echo $OS
echo $ARCH

mkdir -p ~/.istioctl/bin
curl -sSL https://storage.googleapis.com/istio-binaries-$REPO_KEY/$ISTIO_IMAGE/istioctl-$ISTIO_IMAGE-$OS-$ARCH.tar.gz | tar xzf - -C ~/.istioctl/bin
chmod +x ~/.istioctl/bin/istioctl

export PATH=${HOME}/.istioctl/bin:${PATH}
```

### Self-Signed Certs For Shared Root Trust (Comms Between Clusters)
```
curl -L https://istio.io/downloadIstio | ISTIO_VERSION=${ISTIO_VERSION} sh -
cd istio-${ISTIO_VERSION}

mkdir -p certs
pushd certs
make -f ../tools/certs/Makefile.selfsigned.mk root-ca

function create_cacerts_secret() {
  context=${1:?context}
  cluster=${2:?cluster}
  make -f ../tools/certs/Makefile.selfsigned.mk ${cluster}-cacerts
  kubectl --context=${context} create ns istio-system || true
  kubectl --context=${context} create secret generic cacerts -n istio-system \
    --from-file=${cluster}/ca-cert.pem \
    --from-file=${cluster}/ca-key.pem \
    --from-file=${cluster}/root-cert.pem \
    --from-file=${cluster}/cert-chain.pem
}

create_cacerts_secret ${CLUSTER1} ${CLUSTER1_NAME}

cd ../..
```

### Istio CRDs and Control Plane (Istiod)
```
helm upgrade --install istio-base oci://$HELM_REPO/base \
--namespace istio-system \
--create-namespace \
--version $ISTIO_IMAGE \
-f - <<EOF
defaultRevision: ""
profile: ambient
EOF
```

```
helm upgrade --install istiod oci://$HELM_REPO/istiod \
--namespace istio-system \
--version $ISTIO_IMAGE \
-f - <<EOF
env:
  # Assigns IP addresses to multicluster services
  PILOT_ENABLE_IP_AUTOALLOCATE: "true"
  # Disable selecting workload entries for local service routing.
  # Required for Gloo VirtualDestinaton functionality.
  PILOT_ENABLE_K8S_SELECT_WORKLOAD_ENTRIES: "false"
  # Required when meshConfig.trustDomain is set
  PILOT_SKIP_VALIDATE_TRUST_DOMAIN: "true"
global:
  hub: $REPO
  multiCluster:
    clusterName: $CLUSTER1_NAME
  network: $CLUSTER1_NAME
  proxy:
    clusterDomain: cluster.local
  tag: $ISTIO_IMAGE
meshConfig:
  accessLogFile: /dev/stdout
  defaultConfig:
    proxyMetadata:
      ISTIO_META_DNS_AUTO_ALLOCATE: "true"
      ISTIO_META_DNS_CAPTURE: "true"
  enableTracing: true
  defaultConfig:
    tracing:
      sampling: 100
      zipkin:
        address: gloo-telemetry-collector.gloo-mesh.svc.cluster.local:9411
  trustDomain: "$CLUSTER1_NAME.local"
pilot:
  cni:
    namespace: istio-system
    enabled: true
platforms:
  peering:
    enabled: true
profile: ambient
license:
  value: $SOLO_LICENSE_KEY
EOF
```

### Istio CNI
```
helm upgrade --install istio-cni oci://$HELM_REPO/cni \
--namespace istio-system \
--version $ISTIO_IMAGE \
-f - <<EOF
# Assigns IP addresses to multicluster services
ambient:
  dnsCapture: true
excludeNamespaces:
  - istio-system
  - kube-system
global:
  hub: $REPO
  tag: $ISTIO_IMAGE
  platform: gke # Uncomment for GKE
profile: ambient
# Uncomment these two lines for GKE
resourceQuotas: 
  enabled: true
EOF
```

### Install Ztunnel
```
helm upgrade --install ztunnel oci://$HELM_REPO/ztunnel \
--namespace istio-system \
--version $ISTIO_IMAGE \
-f - <<EOF
configValidation: true
enabled: true
env:
  L7_ENABLED: "true"
  # Required when a unique trust domain is set for each cluster
  SKIP_VALIDATE_TRUST_DOMAIN: "true"
l7Telemetry:
  distributedTracing:
    otlpEndpoint: "http://gloo-telemetry-collector.gloo-mesh:4317"
global:
  platform: gke # Uncomment for GKE
hub: $REPO
istioNamespace: istio-system
multiCluster:
  clusterName: $CLUSTER1_NAME
namespace: istio-system
profile: ambient
proxy:
  clusterDomain: cluster.local
tag: $ISTIO_IMAGE
terminationGracePeriodSeconds: 29
variant: distroless
EOF
```

```
kubectl get pods -n istio-system
```

## Install Gloo Gateway/Agentgateway

```
helm upgrade -i gloo-gateway-crds oci://us-docker.pkg.dev/solo-public/gloo-gateway/charts/gloo-gateway-crds \
--namespace gloo-system \
--version 2.0.0 \
--create-namespace
```

```
helm upgrade -i gloo-gateway oci://us-docker.pkg.dev/solo-public/gloo-gateway/charts/gloo-gateway \
-n gloo-system \
--version 2.0.0 \
--set gateway.aiExtension.enabled=true \
--set agentgateway.enabled=true \
--set licensing.glooGatewayLicenseKey=$GLOO_GATEWAY_LICENSE_KEY \
--set licensing.agentgatewayLicenseKey=$AGENTGATEWAY_LICENSE_KEY
```


## Install Solo Enterprise For Kagent  (Mgmt Cluster)

```
helm upgrade -i kagent-mgmt \
oci://us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts/management \
-n kagent --create-namespace \
--version 0.1.4 \
-f - <<EOF
cluster: ${CLUSTER1}
ui:
  backend:
    oidcClientId: ${OIDC_BACKEND}
    oidcSecret: ${BACKEND_CLIENT_SECRET}
    oidcIssuer: ${OIDC_ISSUER}
  frontend:
    clientId: ${OIDC_FRONTEND}
    authEndpoint: ${ENDPOINT}/auth
    logoutEndpoint: ${ENDPOINT}/logout
    tokenEndpoint: ${ENDPOINT}/token
EOF
```

```
kubectl get pods -n kagent
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
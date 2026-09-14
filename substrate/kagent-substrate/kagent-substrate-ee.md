- AgentTemplate: reusable agent configuration.
- Harness: execution configuration paired with a template.

kagent combines an `AgentTemplate` with a `Harness` and compiles that pair into an immutable `ateapi.ActorTemplate`

- AgentInstance: a conversation.
- A2A tasks and artifacts: the conversation’s execution history and transcript.


```
Kubernetes	Declarative resources and live resource mutations
PostgreSQL	Runtime state plus enterprise eval definitions, snapshots, and run lifecycle
ClickHouse	Traces, collected object history/current-state projections, eval results, and aggregates
```

## Configuration

The required sequence is:
1. Enable the certificate APIs, unless already enabled. Node-side certificate projection must also work; that remains unresolved on this cluster.
2. Install the CRDs.
3. Create the Substrate namespace and install Substrate. Adding --create-namespace to the Helm command replaces the separate kubectl create namespace ate-system.
4. Create the CA/JWT pools, actor CA certificate Secret, and authentication ConfigMap. This chart version does not bootstrap those automatically.
5. Verify Substrate readiness, then install kagent and its WorkerPool.

A compatbiel node is needed and will depend on the cloud you're using. For example, `c3-standard-4` is a node thats compatible in GKE.

### Enable PodCertificateRequest

```
gcloud container clusters update kagentsubstratemlevan \
  --location=us-central1 \
  --project=field-engineering-us \
  --enable-kubernetes-unstable-apis=certificates.k8s.io/v1beta1/podcertificaterequests,certificates.k8s.io/v1beta1/clustertrustbundles \
  --quiet
```

### Install

```
helm install kagent-crds \
  oci://us-docker.pkg.dev/developers-369321/kagent-enterprise/charts/kagent-enterprise-crds \
  --version 1.0.0-alpha0-2026-09-10-gh-readonly-queue-main-pr-114-7-a0fd662 \
  --namespace kagent --create-namespace \
  --set substrate.enabled=true --wait --timeout 5m
```

```
helm install substrate oci://ghcr.io/kagent-dev/substrate/helm/substrate \
  --version 0.0.26 \
  --namespace ate-system \
  -f /var/folders/85/9pm1nys90qjcv7qj960dpn3m0000gn/T/opencode/gke-a0fd662/substrate-values.yaml \
  --set-string "rustfs.accessKey=$(openssl rand -hex 12)" \
  --set-string "rustfs.secretKey=$(openssl rand -hex 32)" \
  --timeout 5m \
  --create-namespace
```

```
kubectl create secret docker-registry kagent-registry \
  --namespace kagent \
  --docker-server=us-docker.pkg.dev \
  --docker-username=oauth2accesstoken \
  --docker-password="$(gcloud auth print-access-token)"
```

```
kubectl create secret generic kagent-clickhouse-connection \
  --namespace kagent \
  --from-literal=address=kagent-clickhouse.kagent.svc.cluster.local \
  --from-literal=port=9000 \
  --from-literal=database=platformdb \
  --from-literal=username=default \
  --from-literal="password=$(openssl rand -hex 32)"
```

```
helm install kagent \
  oci://us-docker.pkg.dev/developers-369321/kagent-enterprise/charts/kagent-enterprise \
  --version 1.0.0-alpha0-2026-09-10-gh-readonly-queue-main-pr-114-7-a0fd662 \
  --kube-context gke_field-engineering-us_us-central1_kagentsubstratemlevan \
  --namespace kagent \
  --timeout 5m \
  -f - <<'EOF'
global:
  cluster: kagentsubstratemlevan
  istio:
    ambient:
      enabled: false
  licensing:
    createSecret: false

imagePullSecrets:
  - name: kagent-registry

substrate:
  enabled: false

controller:
  substrate:
    enabled: true
    ateApiEndpoint: dns:///api.ate-system.svc:443
    atenetRouterURL: http://atenet-router.ate-system.svc:80
    defaultWorkerPool:
      namespace: kagent
      name: kagent-default

substrateWorkerPool:
  create: true
  name: kagent-default
  replicas: 2
  workerImage: ghcr.io/kagent-dev/substrate/ateom-gvisor:v0.0.26
  sandboxClass: gvisor

ui:
  enabled: true
  image:
    registry: us-docker.pkg.dev/developers-369321
  service:
    type: ClusterIP

kmcp:
  imagePullSecrets:
    - name: kagent-registry

enterprise:
  service:
    type: ClusterIP
  database:
    clickhouse:
      generateConfig: false
      secretRef: kagent-clickhouse-connection
      agentevalsSink:
        generateConfig: false

clickhouse:
  enabled: true
  auth:
    createSecret: false
    secretName: kagent-clickhouse-connection
    skipUserSetup: false
  resources:
    requests:
      cpu: 100m
      memory: 512Mi
      ephemeral-storage: 50Mi
    limits:
      cpu: 1000m
      memory: 2Gi

telemetry:
  enabled: true
  clickhouse:
    generateConfig: false
    secretRef: kagent-clickhouse-connection
  collector:
    resources:
      requests:
        cpu: 100m
        memory: 256Mi
      limits:
        cpu: 500m
        memory: 1Gi
  k8sobjects:
    resources:
      requests:
        cpu: 50m
        memory: 128Mi
      limits:
        cpu: 300m
        memory: 512Mi
EOF
```

### CA/JWT Bootstrap
Using the already-installed kubectl-ate:

kubectl-ate --context "$CTX" admin make-ca-pool \
  --ca-id=1 --name=service-dns-ca-pool \
  --secret-namespace=podcertificate-controller-system

kubectl-ate --context "$CTX" admin make-ca-pool \
  --ca-id=1 --name=pod-identity-ca-pool \
  --secret-namespace=podcertificate-controller-system

kubectl-ate --context "$CTX" admin make-jwt-pool \
  --key-id=1 --name=actor-id-jwt-pool \
  --secret-namespace=ate-system

kubectl-ate --context "$CTX" admin make-ca-pool \
  --ca-id=1 --name=actor-id-ca-pool \
  --secret-namespace=ate-system

###  Actor Trust And Authentication
Extract the public CA certificate into a separate Secret:

```
set -o pipefail

kubectl --context="$CTX" get secret actor-id-ca-pool \
  --namespace ate-system -o jsonpath='{.data.pool}' \
  | base64 --decode \
  | jq -r '.CAs[0].RootCertificateDER' \
  | base64 --decode \
  | openssl x509 -inform der -outform pem \
  | kubectl --context="$CTX" create secret generic actor-id-ca-certs \
      --namespace ate-system --from-file=ca.crt=/dev/stdin
```

Create the authentication ConfigMap:
```
kubectl --context="$CTX" create configmap ate-api-authentication \
  --namespace ate-system \
  --from-literal=authentication.yaml=$'actorIdentityJWTProvider: kubernetes\njwtProviders:\n- name: kubernetes\n  issuer: https://container.googleapis.com/v1/projects/field-engineering-us/locations/us-central1/clusters/kagentsubstratemlevan\n  audiences: [api.ate-system.svc]\n'
```

## UI

```

```
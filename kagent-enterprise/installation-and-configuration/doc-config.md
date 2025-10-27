1. Set env variables

```
export SOLO_LICENSE_KEY=<key>
export GLOO_GATEWAY_LICENSE_KEY=<key>
export AGENTGATEWAY_LICENSE_KEY=<key>
export OPENAI_API_KEY=
```

2. create the `kagent` Namespace
```
kubectl create ns kagent
```

3. Create the secrets for your LLM and the backend secret which contains the OIDC secret
```
kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: llm-api-keys
  namespace: kagent
type: Opaque
stringData:
  OPENAI_API_KEY: ${OPENAI_API_KEY}
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: kagent-backend-secret
  namespace: kagent
type: Opaque
stringData:
  clientSecret: ${BACKEND_CLIENT_SECRET}
  secret: ${BACKEND_CLIENT_SECRET}
EOF
```

4. When a user sends a request to the Agent, we use the token from Keycloak to authenticate the request to the Agent. Then, we do a token delgation that allows the Agent to send another request on behalf of the user. To do that, system-level authentication is needed. That's what this secret creates
```
openssl genpkey -algorithm RSA -out /tmp/key.pem -pkeyopt rsa_keygen_bits:2048

kubectl create secret generic jwt -n kagent --from-file=jwt=/tmp/key.pem
```

5. Install the Gloo Operator
```
helm upgrade -i gloo-operator oci://us-docker.pkg.dev/solo-public/gloo-operator-helm/gloo-operator \
--version 0.4.0 \
-n kagent \
--create-namespace \
--values - <<EOF
manager:
  env:
    KAGENT_CONTROLLER: true
    WATCH_NAMESPACES: "kagent"
    GLOO_GATEWAY_LICENSE_KEY: ${GLOO_GATEWAY_LICENSE_KEY}
    AGENTGATEWAY_LICENSE_KEY: ${AGENTGATEWAY_LICENSE_KEY}
    SOLO_ISTIO_LICENSE_KEY: ${SOLO_LICENSE_KEY}
EOF
```

6. Set up kagent enterprise via the Controller

The reason why you need `frontend.uiBackendHost:localhost` is because there is a bug in the UX that points to `localhost:8090` instead of the kagents ALB/public-facing UI

```
kubectl apply -n kagent -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: gloo-extensions-config
data:
  values.management: |
    cluster: ${CLUSTER1_NAME}
    ui:
      frontend:
        uiBackendHost: "http://localhost:8090"
  values.gloo: |
    agentgateway:
      enabled: true
  values.kagent: |
    controller:
      image:
        registry: us-docker.pkg.dev/solo-public
        repository: kagent-enterprise/kagent-enterprise-kagent-enterprise-controller
        tag: 0.1.5
    oidc:
      enabled: true
---
apiVersion: operator.gloo.solo.io/v1
kind: ServiceMeshController
metadata:
  name: managed-istio
  labels:
    app.kubernetes.io/name: managed-istio
spec:
  dataplaneMode: Ambient
  installNamespace: istio-system
  version: 1.27.1
---
apiVersion: operator.gloo.solo.io/v1
kind: GatewayController
metadata:
  name: gloo-gateway
spec:
  version: 2.0.0
---
apiVersion: operator.gloo.solo.io/v1
kind: KagentManagementController
metadata:
  name: kagent-enterprise
spec:
  version: 0.1.5
  repository:
    url: oci://us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts
  oidc:
    clientID: ${OIDC_BACKEND}
    clientSecret: kagent-backend-secret
    issuer: ${OIDC_ISSUER}
    authEndpoint: ${authEndpoint}
    logoutEndpoint: ${logoutEndpoint}
    tokenEndpoint: ${tokenEndpoint}
---
apiVersion: operator.gloo.solo.io/v1
kind: KagentController
metadata:
  name: kagent
spec:
  version: 0.1.5
  repository:
    url: oci://us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts
  apiKey:
    type: OpenAI
    secretRef: 
      name: llm-api-keys
      namespace: kagent
  oidc:
    clientId: ${OIDC_BACKEND}
    issuer: ${OIDC_ISSUER}
    secretRef: kagent-backend-secret
    secret: ${BACKEND_CLIENT_SECRET}
  telemetry:
    logging:
      endpoint: kagent-enterprise-ui.kagent.svc.cluster.local:4317
    tracing:
      endpoint: kagent-enterprise-ui.kagent.svc.cluster.local:4317
EOF
```

7. Give it about 2-3 minutes for the entire env to get up and running

```
kubectl get pods -n istio-system
kubectl get pods -n gloo-system
kubectl get po -n kagent | grep -E "ui|clickhouse"
kubectl get po -n kagent -l app.kubernetes.io/instance=kagent-enterprise
kubectl get po -n kagent -l app=kagent
```

8. Open up a terminal and forward the backend (per the current bug in step 6)
```
kubectl port-forward service/kagent-enterprise-ui -n kagent 8090:8090
```
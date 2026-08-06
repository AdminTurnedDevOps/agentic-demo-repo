The Quickstart below shows you how to upgrade your existing kagent enterprise environment to enable Agent Substrate and how to deploy Substrate Agents with BYO Agents, Declarative Agents, and Agent Harnesses (OpenClaw and Hermes)

## Install

Upgrade your existing kagent installation:

The CRDs and Controller

The below contains:

1. Env variables
2. OCI chart locations
3. Substrate Controller config and CRDs, which is installed as a *subchart* of the kagent release, so Service names are "${KAGENT_RELEASE}-...".
```

export KAGENT_NS="${KAGENT_NS:-kagent}"
export KAGENT_RELEASE="${KAGENT_RELEASE:-kagent}"
export KAGENT_CRDS_RELEASE="${KAGENT_CRDS_RELEASE:-kagent-crds}"
export KAGENT_VERSION="${KAGENT_VERSION:-0.5.3}"

export KAGENT_CRDS_CHART="${KAGENT_CRDS_CHART:-oci://us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts/kagent-enterprise-crds}"
export KAGENT_CHART="${KAGENT_CHART:-oci://us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts/kagent-enterprise}"

export SUBSTRATE_API_SVC="${SUBSTRATE_API_SVC:-${KAGENT_RELEASE}-api}"
export SUBSTRATE_ATENET_SVC="${SUBSTRATE_ATENET_SVC:-${KAGENT_RELEASE}-atenet-router}"
export SUBSTRATE_ATE_API_SA="${SUBSTRATE_ATE_API_SA:-${KAGENT_RELEASE}-ate-api-server}"
export SUBSTRATE_VALKEY_SVC="${SUBSTRATE_VALKEY_SVC:-${KAGENT_RELEASE}-valkey-cluster}"

# Controller → ate-api / atenet endpoints (in-cluster DNS)
export ATE_API_ENDPOINT="${ATE_API_ENDPOINT:-dns:///${SUBSTRATE_API_SVC}.${KAGENT_NS}.svc:443}"
export ATENET_ROUTER_URL="${ATENET_ROUTER_URL:-http://${SUBSTRATE_ATENET_SVC}.${KAGENT_NS}.svc:80}"
export VALKEY_CLUSTER_ADDRESS="${VALKEY_CLUSTER_ADDRESS:-${SUBSTRATE_VALKEY_SVC}.${KAGENT_NS}.svc:6379}"

# JWT: must match the cluster SA token issuer (GKE example below).
#   GKE:  https://container.googleapis.com/v1/projects/<proj>/locations/<loc>/clusters/<name>
#   kind: https://kubernetes.default.svc.cluster.local
# Discover with:
#   kubectl get --raw /.well-known/openid-configuration | jq -r .issuer
export JWT_ISSUER="${JWT_ISSUER:-$(kubectl get --raw /.well-known/openid-configuration 2>/dev/null | sed -n 's/.*"issuer"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')}"
if [ -z "${JWT_ISSUER}" ]; then
  echo "JWT_ISSUER is empty. Set it explicitly (see comment above)." >&2
  exit 1
fi

# WorkerPool
export WORKER_POOL_NAME="${WORKER_POOL_NAME:-kagent-default}"
export WORKER_POOL_REPLICAS="${WORKER_POOL_REPLICAS:-2}"
export ATEOM_IMAGE="${ATEOM_IMAGE:-ghcr.io/kagent-dev/substrate/ateom-gvisor:v0.0.8}"

# Chart-generated self-signed ate-api TLS: controller does not mount that CA
export ATE_API_INSECURE="${ATE_API_INSECURE:-true}"

helm upgrade "${KAGENT_CRDS_RELEASE}" "${KAGENT_CRDS_CHART}" \
  --version "${KAGENT_VERSION}" \
  -n "${KAGENT_NS}" \
  --reuse-values \
  --set substrate.enabled=true \
  --wait --timeout 5m

helm upgrade "${KAGENT_RELEASE}" "${KAGENT_CHART}" \
  --version "${KAGENT_VERSION}" \
  -n "${KAGENT_NS}" \
  --reuse-values \
  --set substrate.enabled=true \
  --set "substrate.redis.clusterAddress=${VALKEY_CLUSTER_ADDRESS}" \
  --set "substrate.auth.jwt.issuer=${JWT_ISSUER}" \
  --set controller.substrate.enabled=true \
  --set "controller.substrate.ateApiEndpoint=${ATE_API_ENDPOINT}" \
  --set "controller.substrate.ateApiInsecure=${ATE_API_INSECURE}" \
  --set "controller.substrate.atenetRouterURL=${ATENET_ROUTER_URL}" \
  --set "controller.substrate.ateApiServer.namespace=${KAGENT_NS}" \
  --set "controller.substrate.ateApiServer.serviceAccount=${SUBSTRATE_ATE_API_SA}" \
  --set "controller.substrate.defaultWorkerPool.name=${WORKER_POOL_NAME}" \
  --set substrateWorkerPool.create=true \
  --set "substrateWorkerPool.replicas=${WORKER_POOL_REPLICAS}" \
  --set "substrateWorkerPool.ateomImage=${ATEOM_IMAGE}" \
  --set "substrateWorkerPool.name=${WORKER_POOL_NAME}" \
  --wait --timeout 15m
```

To use Substrate in kagent enterprise, you need a minimum version of `0.5.3`


## Harness Agents (OpenClaw and Hermes)

```
kubectl apply -f - <<'EOF'
apiVersion: kagent.dev/v1alpha2
kind: AgentHarness
metadata:
  name: my-openclaw
  namespace: kagent
spec:
  backend: openclaw
  description: OpenClaw on Agent Substrate (kagent-ee-felevan)
  modelConfigRef: default-model-config
  substrate:
    workerPoolRef:
      name: kagent-default
    snapshotsConfig:
      location: gs://ate-snapshots-field-engineering-us-substrate-mlevan/kagent/my-openclaw
EOF
```

## Declarative/BYO Agents

```
apiVersion: kagent.dev/v1alpha2
kind: SandboxAgent
metadata:
  name: my-sandbox-agent
  namespace: kagent
spec:
  type: Declarative   # or BYO
  declarative:
    modelConfig: my-model
    # instructions, tools, etc.
  substrate:
    workerPoolRef:
      name: kagent-default
```
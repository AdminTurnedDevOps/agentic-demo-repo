Agent Substrate is the sandbox runtime kagent runs agents (they're called Actors) in.

It multiplexes a large set of idle Actors onto a set of warm Workers (Workers are Pods). An Actor is one sandboxed process (an agent, a coding harness, an MCP server). A Worker is a long-running pod that hosts at most one RUNNING Actor at a time. When the Actor is idle, Substrate suspends it and frees the Worker. The next request resumes it, often on a different Worker, from a snapshot rather than a cold boot. Sandbox options are gVisor (software-level isolation) and microVM (hardware-level isolation). Kubernetes owns the Pods and Substrate owns Actor scheduling, snapshots, and routing. The `ateapi` server (Substrates API Server) was created and implemented for that work because those workloads change too fast for the Kubernetes API (hence the performance and efficiency of `ateapi`).

## Prereqs

1. k8s v1.36 and above
2. Solo kagent license key
3. Provider (OpenAI, Anthropic, etc.) license key
4. `PodCertificateRequest` enabled on the cluster, `ClusterTrustBundle`, and the corresponding projected-volume support on the nodes.

## What Gets Installed

- Postgres (kagent state, checkpoints, eval definitions)
- Clickhouse (OTel traces, Substrate requests, harness chat spans, agenteval results)
- Kagent/Agent Substrate CRDs
- Kagent/Agent Substrate

## kagent CRDs

```
helm install kagent-crds \
  oci://us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts/kagent-enterprise-crds \
  --version 1.0.0-alpha3 --namespace kagent --create-namespace \
  --set substrate.enabled=true
```

Without `substrate.enabled=true`, the `WorkerPool` CRD will not exist, so no works will be available to run Actors.

## Agent Substrate Install

```
cat > substrate-values.yaml <<'EOF'
credentialProvider:
  namespacePolicies:
    - atespace: kagent
      allowedNamespaces: [kagent]
EOF

helm install substrate oci://ghcr.io/kagent-dev/substrate/helm/substrate \
  --version 0.2.0-beta5 --namespace ate-system --create-namespace \
  --wait=false -f substrate-values.yaml
```

## Cryptographic Pool Creation

The below creates Substrate’s cryptographic key pools. `kubectl-ate` generates them as Kubernetes Secrets for Substrate’s certificate and identity components to consume. The Substrate chart does not create these Secrets, so its pods cannot become ready on a fresh install without this bootstrap.

```
Pool	Purpose
service-dns-ca-pool	CA material for Substrate’s service-DNS certificates and trust bundle.
pod-identity-ca-pool	CA material for projected pod identity certificates.
actor-id-jwt-pool	Signing keys for actor identity JWTs.
actor-id-ca-pool	CA material for actor identity certificates.
egress-mitm-ca-pool	CA material for the egress gateway’s destination certificates. Actors need its trust bundle to accept those connections.
```

1. Make the WorkerPools.

```
OS=$(uname -s | tr '[:upper:]' '[:lower:]')          # darwin or linux
ARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
curl -fsSL -o kubectl-ate \
  "https://github.com/kagent-dev/substrate/releases/download/v0.2.0-beta5/kubectl-ate-${OS}-${ARCH}"
chmod +x kubectl-ate
```

2. The `ate-api-server` compares Actor identity certificates with the root of the actor-id pool. Give the root to the server as a PEM Secret.

```
kubectl get secret actor-id-ca-pool -n ate-system -o jsonpath='{.data.pool}' \
  | base64 --decode \
  | jq -r '.CAs[0].RootCertificateDER' \
  | base64 --decode \
  | openssl x509 -inform der -outform pem > actor-id-ca.crt

kubectl create secret generic actor-id-ca-certs -n ate-system --from-file=ca.crt=actor-id-ca.crt
```

3. Make the authentication ConfigMap

This tells Substrate’s `ate-api-server` which JWTs to trust. The command creates a `ConfigMap` named `ate-api-authentication` in `ate-system`, with an `authentication.yaml` key. The Substrate chart mounts that file into `ate-api-server` and passes it as `--authentication-config`.

```
Field	Meaning
actorIdentityJWTProvider: kubernetes	Selects the named JWT provider that may call Substrate’s actor-identity JWT minting operation.
jwtProviders[].name: kubernetes	Names that provider; it must match the field above.
issuer	The exact iss claim Substrate expects in a bearer token. It also uses this URL to discover signing keys.
audiences: [api.ate-system.svc]	Accepts tokens issued for ate-api, rather than accepting any valid service-account token.
certificateAuthorityFile	A CA bundle used by ate-api-server when it makes HTTPS requests for issuer discovery and signing keys. It is not the CA from section 6.2.
discoveryTokenFile	The server pod’s mounted service-account token, sent when the Kubernetes discovery or key endpoint requires authentication. It is not a token clients present to ate-api.
```

Run the following:

```
kubectl create configmap ate-api-authentication -n ate-system --from-literal=authentication.yaml='actorIdentityJWTProvider: kubernetes
jwtProviders:
- name: kubernetes
  issuer: https://kubernetes.default.svc
  audiences: [api.ate-system.svc]
  certificateAuthorityFile: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
  discoveryTokenFile: /var/run/secrets/kubernetes.io/serviceaccount/token
'
```

## Ensure Substrate Is Running

```
kubectl rollout status deploy/podcertificate-controller -n podcertificate-controller-system --timeout=300s
for d in ate-api-server ate-controller atenet-router atenet-egress k8s-credential-provider; do
  kubectl rollout status deploy/$d -n ate-system --timeout=300s
done
kubectl rollout status ds/atelet -n ate-system --timeout=300s
```

## Kagent Install

```sh
export ENTERPRISE_LICENSE_KEY=
export OPENAI_API_KEY=
```

> [!NOTE]
> You can also use Claude
> export ANTHROPIC_API_KEY

```sh
helm install kagent \
  oci://us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts/kagent-enterprise \
  --version 1.0.0-alpha3 --namespace kagent --wait --timeout 15m -f - <<EOF
global:
  cluster: kagent-demo
  licensing:
    createSecret: true
    licenseKey: "${ENTERPRISE_LICENSE_KEY:?Set ENTERPRISE_LICENSE_KEY}"

telemetry:
  enabled: true
  traces:
    enabled: true

otel:
  tracing:
    enabled: true
    exporter:
      otlp:
        endpoint: http://solo-enterprise-telemetry-collector.kagent.svc.cluster.local:4317
        insecure: true

controller:
  substrate:
    enabled: true
    ateApiEndpoint: "dns:///api.ate-system.svc:443"
    atenetRouterURL: "http://atenet-router.ate-system.svc:80"
    defaultWorkerPool:
      name: kagent-default

substrate:
  enabled: false

substrateWorkerPool:
  create: true
  name: kagent-default
  workerImage: ghcr.io/kagent-dev/substrate/ateom-gvisor:v0.2.0-beta5
  sandboxClass: gvisor

providers:
  openAI:
    apiKey: "${OPENAI_API_KEY:?Set OPENAI_API_KEY}"
EOF
```

> [!NOTE]
> To use Claude instead of OpenAI, set `ANTHROPIC_API_KEY` and replace the `providers:` block above with:
>
> ```yaml
> providers:
>   default: anthropic
>   anthropic:
>     apiKey: "${ANTHROPIC_API_KEY:?Set ANTHROPIC_API_KEY}"
> ```

Keep the `http://` prefix on the OTLP endpoint. Without it, the exporter attempts TLS against the collector's plaintext port and agent traces do not arrive.

> [!NOTE]
> The above config uses the built-in demo iDP/OIDC provider. If you want to set your own, please use:
>
> ```sh
> kubectl create secret generic kagent-enterprise-oidc-secret \
>  --namespace kagent \
>  --from-literal=clientSecret="$OIDC_CLIENT_SECRET"
> ```

```sh
enterprise:
  oidc:
    issuer: "https://idp.example.com/realms/kagent"
    clientId: "kagent-enterprise"
    secretRef: "kagent-enterprise-oidc-secret"
    secretKey: "clientSecret"
```

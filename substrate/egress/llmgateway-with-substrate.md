# LLM Gateway Behind Substrate Egress

Tldr; Substrate's `atenet-egress` decides **where** an actor may connect. It
does not do LLM work. This lab puts a second agentgateway, the **LLM gateway**,
behind it. The actor calls the LLM gateway in plain HTTP with a placeholder
`Authorization` header. `atenet-egress` checks the actor's `EgressPolicy`,
swaps the placeholder for a **per-actor JWT** minted by ate-api, and forwards.
The LLM gateway verifies that JWT, authorizes the actor's atespace, injects the
OpenAI key, and logs which actor spent which tokens. The actor never holds a
provider key and cannot reach OpenAI directly.

| Lab | What you look at | Which agentgateway |
|---|---|---|
| **actor** → `atenet-egress` → **LLM gateway** → OpenAI | Actor JWT injected at egress, verified at the LLM gateway, tokens logged per actor | Two: Substrate's embedded egress dataplane (`ate-system`) and an LLM gateway (`agentgateway-system`) |

---

## What this lab proves

| Beat | Proof |
|---|---|
| Identity comes from Substrate, not the sandbox | The actor sends `Bearer placeholder`. The LLM gateway sees `sub: actor/llm-lab/caller` |
| Provider key stays out of the sandbox | The OpenAI key is only in a Secret in `agentgateway-system` |
| Per-actor LLM accounting | LLM gateway access log carries `substrate.actor`, model, input and output tokens |

---

## Architecture

```text
 ┌──────────── worker pod (ate-llm-lab) ─────────────┐
 │  actor "caller" (gVisor, curl loop)                │
 │  POST http://llm-gateway.agentgateway-system       │
 │       .svc.cluster.local/v1/chat/completions       │
 │  Authorization: Bearer placeholder                 │
 │        │  nftables REDIRECT                        │
 │        ▼                                           │
 │  atunnel ── mTLS CONNECT, actor certificate ──┐    │
 └───────────────────────────────────────────────┼────┘
                                                 ▼
 ┌──────────── atenet-egress (ate-system) ─────────────────────┐
 │  agentgateway, Substrate config                             │
 │  1. substrateEgressActorResolution: GetActor (RUNNING?)     │
 │  2. substrateEgress: GetActorEgressPolicy                   │
 │     http rule matches Host + dialed port 80                 │
 │  3. replaceHeaders: MintActorJwt                            │
 │     Authorization: Bearer <actor JWT, aud=llm-gateway>      │
 └───────────────────────────────┬─────────────────────────────┘
                                 ▼
 ┌──────────── llm-gateway (agentgateway-system) ──────────────┐
 │  agentgateway v1.6.0, Gateway API                           │
 │  jwtAuthentication: iss = Substrate, inline JWKS            │
 │  authorization: jwt.sub startsWith "actor/llm-lab/"         │
 │  AgentgatewayBackend ai.openai + Secret key                 │
 │  access log: substrate.actor, llm.* tokens                  │
 └───────────────────────────────┬─────────────────────────────┘
                                 ▼
                          api.openai.com
```

Two agentgateways, two jobs:

| | `atenet-egress` | `llm-gateway` |
|---|---|---|
| Namespace | `ate-system` | `agentgateway-system` |
| Configured by | Substrate's static ConfigMap (`ate-setup`) | agentgateway controller + Gateway API |
| Decides | May this actor connect to this host and port? | May this actor call this model? |
| Credential it adds | Per-actor JWT (`actorJwt`) | OpenAI API key (`backend auth`) |

---

## Prerequisites

Tool versions this lab was written against:

| Tool | Version | Notes |
|---|---|---|
| Agent Substrate, kagent's version | [`kagent-dev/substrate`](https://github.com/kagent-dev/substrate) `v0.7.0-alpha1`, installed with `--atenet-dataplane=agentgateway` | `ate-system` healthy, and `kubectl-ate` installed from the same checkout. Upstream Substrate's pinned agentgateway build can't read this Substrate API version, so actor egress is denied |
| agentgateway Helm charts | `v1.6.0` | `oci://cr.agentgateway.dev/charts/agentgateway{,-crds}` |
| Gateway API CRDs | `v1.6.0` standard channel | What agentgateway v1.6.0's examples install |
| Substrate's egress agentgateway image | `ghcr.io/kagent-dev/substrate/agentgateway:c8550278b2f2` | Set by kagent's Substrate on `atenet-egress` and `atenet-router` |
| OpenAI API key | | In your shell as `OPENAI_API_KEY`. It goes into a Kubernetes Secret, never into a file |
| Image registry for `ko` | | In your shell as `KO_DOCKER_REPO`. Step 4 pushes the worker image there |

### Lab variables

Set these once. Every step uses them.

```bash
export SUBSTRATE_DIR="${HOME}/gitrepos/substrate"   # checkout of the Substrate you installed

export ATESPACE=llm-lab
export ACTOR=caller
export TEMPLATE=llm-caller
export LLM_NS=agentgateway-system
export LLM_GW=llm-gateway
export LLM_HOST="${LLM_GW}.${LLM_NS}.svc.cluster.local"
export LLM_AUDIENCE=llm-gateway

export OPENAI_API_KEY=   # paste; a dedicated, revocable key is best
export KO_DOCKER_REPO=   # registry your cluster pulls from; kind: localhost:5001
export KO_DEFAULTPLATFORMS="linux/$(go env GOARCH)"   # kind only

# Any chat model your key can call. The LLM gateway pins it, so the actor's
# request model does not matter.
export OPENAI_MODEL=gpt-5-mini

# Substrate requires actor images pinned by digest.
export CURL_IMAGE='curlimages/curl:8.22.0@sha256:58adaa4e8dca9c988bae2aba4ab3434a0bb2da16bbe3f92dec39ec7785166777'
```

Use the **fully qualified** Service name (`*.svc.cluster.local`). The actor's
DNS relay forwards only names the egress policy allows, and the policy matches
the exact name. Short names and search domains are not part of this path.

---

## Apply order

| Step | What | Namespace |
|---|---|---|
| 1 | Gateway API CRDs + agentgateway v1.6.0 | cluster, `agentgateway-system` |
| 2 | LLM gateway: Gateway, OpenAI backend, route, key Secret | `agentgateway-system` |
| 3 | Trust Substrate actor JWTs at the LLM gateway | `agentgateway-system` |
| 4 | WorkerPool, atespace, ActorTemplate, actor, EgressPolicy | `ate-llm-lab`, atespace `llm-lab` |
| 5 | Watch the calls | |

---

## Step 1: Gateway API CRDs and agentgateway v1.6.0

Check for an existing release first. Other labs in this repo install
agentgateway into the same namespace. If one is already there, either reuse it
(and skip the two `helm` commands) or confirm its version. The CRD shapes below
were checked against `v1.6.0` only.

```bash
kubectl apply --server-side \
  -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.0/standard-install.yaml

helm upgrade -i agentgateway-crds oci://cr.agentgateway.dev/charts/agentgateway-crds \
  --version v1.6.0 \
  --namespace "${LLM_NS}" --create-namespace

helm upgrade -i agentgateway oci://cr.agentgateway.dev/charts/agentgateway \
  --version v1.6.0 \
  --namespace "${LLM_NS}" \
  --wait
```

---

## Step 2: The LLM gateway

### 2a. OpenAI key Secret

```bash
kubectl -n "${LLM_NS}" create secret generic openai-secret \
  --from-literal=Authorization="${OPENAI_API_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 2b. Gateway, OpenAI backend, route

```bash
cat <<EOF | kubectl apply -f -
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: ${LLM_GW}
  namespace: ${LLM_NS}
spec:
  gatewayClassName: agentgateway
  listeners:
  - name: http
    protocol: HTTP
    port: 80
    allowedRoutes:
      namespaces:
        from: Same
---
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: openai
  namespace: ${LLM_NS}
spec:
  ai:
    provider:
      openai:
        model: ${OPENAI_MODEL}
  policies:
    auth:
      secretRef:
        name: openai-secret
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: openai
  namespace: ${LLM_NS}
spec:
  parentRefs:
  - name: ${LLM_GW}
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /v1/chat/completions
    backendRefs:
    - group: agentgateway.dev
      kind: AgentgatewayBackend
      name: openai
EOF
```

```bash
kubectl -n "${LLM_NS}" wait gateway/"${LLM_GW}" --for=condition=Programmed --timeout=180s
kubectl -n "${LLM_NS}" get svc "${LLM_GW}"
kubectl -n "${LLM_NS}" get httproute openai \
  -o jsonpath='{range .status.parents[*].conditions[*]}{.type}={.status}{"\n"}{end}'
```

The Service listens on port `80`. The route shows `Accepted=True` and
`ResolvedRefs=True`.

### 2c. Access log with actor identity and tokens

```bash
cat <<EOF | kubectl apply -f -
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: ${LLM_GW}-access-log
  namespace: ${LLM_NS}
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: ${LLM_GW}
  frontend:
    accessLog:
      attributes:
        add:
        - name: substrate.actor
          expression: jwt.sub
        - name: llm.model
          expression: llm.responseModel
        - name: llm.input_tokens
          expression: llm.inputTokens
        - name: llm.output_tokens
          expression: llm.outputTokens
EOF
```

A CEL expression that fails (for example `jwt.sub` on a request without a JWT)
just leaves that field out of the log line.

---

## Step 3: Trust Substrate actor JWTs at the LLM gateway

ate-api signs actor JWTs with the `actor-id-jwt-pool` key. The public keys are
in the same Secret under `jwks`, and `ate-idp-server` also serves them at
`https://idp.ate-system.svc/openid/v1/jwks`. That endpoint's certificate comes
from Substrate's internal `servicedns` signer, so this lab copies the JWKS
**inline** rather than teaching the LLM gateway that CA.

What a Substrate actor JWT carries (from
[egress-credential-injection.md](https://github.com/agent-substrate/substrate/blob/main/docs/egress-credential-injection.md#actor-jwts)):

| Claim | Value |
|---|---|
| `iss` | The install's `ACTOR_JWT_ISSUER`, default `https://idp.ate-system.svc` |
| `sub` | `actor/<atespace>/<actor-name>` |
| `aud` | What the egress rule's `actorJwt.audiences` says (`llm-gateway` here) |
| Algorithm | ES256 by default |

```bash
export ACTOR_JWT_ISSUER=$(kubectl -n ate-system get cm ate-api-server-envvars \
  -o jsonpath='{.data.ATE_API_ACTOR_JWT_ISSUER}')
export ACTOR_JWKS=$(kubectl -n ate-system get secret actor-id-jwt-pool \
  -o jsonpath='{.data.jwks}' | base64 -d | jq -c .)

echo "${ACTOR_JWT_ISSUER}"
echo "${ACTOR_JWKS}" | jq '.keys[] | {kid, alg, kty, crv}'
```

```bash
cat <<EOF | kubectl apply -f -
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: substrate-actor-jwt
  namespace: ${LLM_NS}
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: openai
  traffic:
    jwtAuthentication:
      mode: Strict
      providers:
      - issuer: ${ACTOR_JWT_ISSUER}
        audiences:
        - ${LLM_AUDIENCE}
        jwks:
          inline: '${ACTOR_JWKS}'
    authorization:
      action: Allow
      policy:
        matchExpressions:
        - 'jwt.sub.startsWith("actor/${ATESPACE}/")'
EOF
```

```bash
kubectl -n "${LLM_NS}" get agentgatewaypolicy substrate-actor-jwt \
  -o jsonpath='{range .status.ancestors[*].conditions[*]}{.type}={.status} {.message}{"\n"}{end}'
```

Conditions show `Accepted=True`.

> **Key rotation:** the inline JWKS is a copy. After
> `kubectl ate admin add-jwt-key`, re-run this step **before**
> `activate-jwt-key`, or the LLM gateway rejects tokens signed by the new key.

---

## Step 4: The actor

### 4a. WorkerPool

Two workers: one for the template's temporary golden actor, one for the lab
actor. `ko` builds `ateworker-gvisor` from the Substrate checkout, so run it
from the Substrate root with `KO_DOCKER_REPO` set (Lab variables).

```bash
cd "${SUBSTRATE_DIR}"
: "${KO_DOCKER_REPO:?set KO_DOCKER_REPO (Lab variables)}"

cat <<'EOF' | hack/run-tool.sh ko apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: ate-llm-lab
---
apiVersion: ate.dev/v1
kind: WorkerPool
metadata:
  name: llm-lab
  namespace: ate-llm-lab
  labels:
    workload: llm-lab
spec:
  replicas: 2
  workerImage: ko://go.ate.dev/substrate/cmd/ateworker-gvisor
  sandboxClasses:
  - name: gvisor
  template:
    resources:
      limits:
        cpu: "1"
        memory: 1Gi
      requests:
        cpu: 250m
        memory: 1Gi
EOF
```

```bash
kubectl -n ate-llm-lab rollout status deploy/llm-lab --timeout=5m
kubectl ate get worker | grep -c llm-lab
```

### 4b. Atespace and ActorTemplate

```bash
kubectl ate create atespace "${ATESPACE}"

sed \
  -e "s|@ATESPACE@|${ATESPACE}|g" \
  -e "s|@TEMPLATE@|${TEMPLATE}|g" \
  -e "s|@CURL_IMAGE@|${CURL_IMAGE}|g" \
  -e "s|@LLM_HOST@|${LLM_HOST}|g" \
  -e "s|@OPENAI_MODEL@|${OPENAI_MODEL}|g" \
  <<'EOF' | kubectl ate create actor-template -f -
metadata:
  atespace: @ATESPACE@
  name: @TEMPLATE@
workerSelector:
  matchLabels:
    workload: llm-lab
containers:
- name: caller
  image: @CURL_IMAGE@
  command: ["/bin/sh", "-c"]
  args:
  - |
    until code=$(curl -sS --connect-timeout 5 --max-time 60 -o /tmp/answer.json -w '%{http_code}' \
        "http://${LLM_HOST}/v1/chat/completions" \
        -H 'Authorization: Bearer placeholder' \
        -H 'Content-Type: application/json' \
        -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"In one short sentence, what is a sandbox?\"}]}") && [ "${code}" = "200" ]; do
      echo "=== $(date -u +%H:%M:%SZ) not through yet (HTTP ${code:-000}), retrying in 5s"
      sleep 5
    done
    echo "=== $(date -u +%H:%M:%SZ) via LLM gateway"
    cat /tmp/answer.json
    echo
    echo "HTTP ${code}"
    while true; do sleep 3600; done
  env:
  - name: LLM_HOST
    value: "@LLM_HOST@"
  - name: MODEL
    value: "@OPENAI_MODEL@"
resources:
  limits:
    cpuMillicores: 1000
    memoryBytes: 536870912 # 512Mi
snapshotConfig:
  preferredFidelity: SNAPSHOT_FIDELITY_MEMORY
EOF
```

Creating the template boots a golden actor, waits about 20 seconds (there is no
wakeup probe), and snapshots it. The golden actor has no egress policy, so its
call fails and it keeps retrying. That is expected: once you resume the actor
with its policy in 4c, the next retry goes through. Wait for the golden tag:

```bash
until kubectl ate get actor-template "${TEMPLATE}" -a "${ATESPACE}" -o json \
  | jq -e '.actorTemplates[0].status.goldenSnapshotStatus.goldenTag.name' >/dev/null; do
  err=$(kubectl ate get actor-template "${TEMPLATE}" -a "${ATESPACE}" -o json \
    | jq -r '.actorTemplates[0].status.goldenSnapshotStatus.errorMessage // empty')
  if [ -n "${err}" ]; then echo "golden snapshot failed: ${err}"; break; fi
  echo "waiting for golden snapshot..."; sleep 5
done
kubectl ate get actor-template "${TEMPLATE}" -a "${ATESPACE}"
```

`GOLDEN TAG` is set and `ERROR` is empty.

### 4c. Actor, then its EgressPolicy, then resume

Order matters. The policy is a child of the actor, so the actor must exist
first. Create the policy **before** resuming: an actor with no policy gets no
egress tunnel, and its DNS answers `NXDOMAIN` for everything.

```bash
kubectl ate create actor "${ACTOR}" -a "${ATESPACE}" --template "${TEMPLATE}"

cat <<EOF | kubectl ate create egress-policy "${ACTOR}" -a "${ATESPACE}" -f -
rules:
- http:
    hostnames:
    - ${LLM_HOST}
    effects:
      replaceHeaders:
      - header: Authorization
        prefix: "Bearer "
        actorJwt:
          audiences:
          - ${LLM_AUDIENCE}
          expirationSeconds: 900
EOF

kubectl ate get egress-policy "${ACTOR}" -a "${ATESPACE}" -o yaml

kubectl ate resume actor "${ACTOR}" -a "${ATESPACE}"
kubectl ate get actor "${ACTOR}" -a "${ATESPACE}"
```

What the policy says:

| Field | Meaning |
|---|---|
| `http` | Cleartext HTTP, decided per request on `Host` and the port the actor dialed |
| `hostnames` | Exact FQDN. The DNS relay also resolves only names a rule covers |
| `ports` (omitted) | Defaults to `80` for `http` rules |
| `replaceHeaders.actorJwt` | Egress calls `MintActorJwt` and writes `Bearer <jwt>` into `Authorization` |
| `audiences` | Must match the LLM gateway's `audiences` in Step 3 |
| `expirationSeconds` | 300 to 3600. Egress caches the token until a third of its lifetime is left |

The actor reaches `ACTOR_STATE_RUNNING`.

---

## Step 5: Watch the calls

Use three terminals.

**Actor (the request and its answer):**

```bash
kubectl ate logs actor "${ACTOR}" -a "${ATESPACE}" -f --source containers
```

The actor makes one successful call, then stays idle. Its log ends with:

```text
=== 18:04:26Z not through yet (HTTP 000), retrying in 5s
=== 18:04:31Z via LLM gateway
{"id":"chatcmpl-…","object":"chat.completion","model":"…","choices":[{"message":{"role":"assistant","content":"A sandbox is …"}}],"usage":{…}}
HTTP 200
```

A `not through yet` line or two right after resume is normal: the sandbox's DNS
picks up the egress policy within about 5 seconds.

**`atenet-egress` (the policy hop):**

```bash
kubectl -n ate-system logs deploy/atenet-egress -c agentgateway -f \
  | grep --line-buffered "${LLM_HOST}"
```

One line for the call, naming the actor and the response status.
agentgateway `main` logs the actor as `ate.actor.name` and `ate.atespace`. The
alpha build Substrate pins may name them differently, which is why the `grep`
matches the hostname instead.

**LLM gateway (who spent what):**

```bash
kubectl -n "${LLM_NS}" logs -l gateway.networking.k8s.io/gateway-name="${LLM_GW}" -f \
  | grep --line-buffered 'substrate.actor'
```

The line carries `substrate.actor=actor/llm-lab/caller`, `llm.model`,
`llm.input_tokens` and `llm.output_tokens`.

---

## References

- Substrate: [egress-credential-injection.md](https://github.com/agent-substrate/substrate/blob/main/docs/egress-credential-injection.md),
  [egress-traffic.md](https://github.com/agent-substrate/substrate/blob/main/docs/egress-traffic.md),
  [network-egress.md](https://github.com/agent-substrate/substrate/blob/main/docs/network-egress.md),
  [ate-setup commands](https://github.com/agent-substrate/substrate/blob/main/cmd/ate-setup/commands.md)
- agentgateway: [Kubernetes docs](https://agentgateway.dev/docs/kubernetes/latest/),
  [CEL reference](https://github.com/agentgateway/agentgateway/blob/v1.6.0/schema/cel.md)
- Earlier lab: [agw-substrate-egress.md](agw-substrate-egress.md) (observing the egress hop with Grafana and Tempo)

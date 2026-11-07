
# agentgateway + Agent Substrate: Route An MCP Server and Scale

"An MCP Tool Server That Exists Only When Called" is the gist of this lab.

agentgateway exposes one stable `/mcp` endpoint. Behind it, the actual
MCP server is a Substrate actor. Suspend the actor and its process disappears
from the worker. Send the next MCP tool call through agentgateway and
Substrate restores the server before forwarding the request.

This connects two separate control planes:

1. **agentgateway** understands MCP: sessions, `tools/list`, `tools/call`,
   policy, metrics, and one stable client-facing endpoint.
2. **Agent Substrate** understands actor lifecycle: snapshot, release the
   worker, restore on demand, and route by the `ate-target-actor` header.

The request path is:

```text
MCP client
  -> agentgateway /mcp
  -> atenet-router (mTLS, ate-target-actor: tools/everything)
  -> ResumeActor (if suspended)
  -> restored MCP server on a warm Substrate worker
```

The result is an MCP endpoint with gateway-level governance and
actor-level scale-to-zero.

> **Be precise about "scale-to-zero."** The MCP server process scales to
> zero: while the actor is suspended it owns no worker and has no running
> container process. The Substrate `WorkerPool` still keeps one generic pod
> warm so this or another actor can resume quickly. This is pooled capacity,
> not Kubernetes Deployment replicas dropping to zero.

## What this lab proves

| Beat | Proof |
|---|---|
| MCP server as an actor | The reference `mcp/everything` Streamable HTTP server runs inside a gVisor-backed ActorTemplate instead of a Deployment. |
| agentgateway to the Substrate router | An agentgateway backend targets `atenet-router` over mTLS and names the actor with `ate-target-actor: tools/everything` (see the Step 5 TODO). |
| First-call wake | The actor starts `ACTOR_STATE_SUSPENDED`; the MCP `initialize` request causes atenet to invoke `ResumeActor` before forwarding it. |
| Session survives suspension | Suspend the actor after an MCP handshake, then reuse the same client session ID for `tools/call`. Full-state restore preserves the server-side MCP session. |
---

## Prerequisites

Confirm the Substrate Control Planes are healthy:

```bash
kubectl get pods -n ate-system
kubectl get pods -n agentgateway-system
kubectl get gatewayclass agentgateway
```

Build `kubectl-ate` from the same Substrate **v1.0.0** checkout used by this
lab (`git clone --branch v1.0.0 https://github.com/agent-substrate/substrate.git`).
Older plugin binaries predate Atespaces and fail with `unknown flag: --atespace`:

```bash
go install ./cmd/kubectl-ate
export PATH="$(go env GOPATH)/bin:$PATH"
rehash 2>/dev/null || true

command -v kubectl-ate
kubectl ate create actor --help | grep atespace
```

The final command must show `--atespace`. If it does not, another
`kubectl-ate` binary appears earlier on `PATH`; invoke
`$(go env GOPATH)/bin/kubectl-ate` directly or remove the stale binary.

Step 5's interim path uses `kubectl ate proxy actor`, which presents the
`spiffe://cluster.local/ns/ate-system/sa/atenet-client` identity to the
router. The Substrate install must list it in
`--ingress-allowed-spiffe-ids` (see
[microVM on Substrate](../microvm/microvm-substrate-imp.md#prerequisites)).

---

# Part 1: Deployment & Configuration

## Step 1: Prepare the Substrate environment

**Why `ko`?**: The source-oriented development manifest does not initially point to a prebuilt, pullable image. `ko` builds that package into a container, pushes it, and replaces the `ko://` reference with the resulting registry image. This is specifically the `ateworker-gvisor` worker image, not gVisor itself. It contains the `ATE` component that controls actor workloads through gVisor. The actual `runsc` sandbox binary is supplied separately through the selected SandboxConfig. In the below, its only used to pull/store the `ateworker-gvisor` image. The WorkerPool is a CRD; the MCP ActorTemplate is created through the ate API with `kubectl ate`.

Set the registry where `ko` will publish the `ateworker-gvisor` image. If the
Substrate environment file is already configured, source it:

```bash
source .ate-dev-env.sh

: "${KO_DOCKER_REPO:?KO_DOCKER_REPO must name a writable container registry}"
```

Otherwise, export it explicitly:

```bash
export KO_DOCKER_REPO="gcr.io/your-project-id/ate-images"
```

`KO_DOCKER_REPO` is required because `ko apply` must push the locally built
`ateworker-gvisor` image before applying the WorkerPool CRD. Snapshots no
longer need a bucket in the template: they go to the install's
`SNAPSHOT_LOCATION`, and transfers use per-actor tokens rather than the
node's Workload Identity.

Select the node pool for Substrate gVisor workers:

```bash
export SUBSTRATE_NODE_POOL=""
```

Use the pool configured for Substrate in your cluster; `substrate-gvisor` is
the name used by the setup tooling, not a universal GKE name. Check that
pool's taints too:

```bash
kubectl get nodes \
  -l cloud.google.com/gke-nodepool="$SUBSTRATE_NODE_POOL" \
  -o jsonpath='{.items[*].spec.taints}{"\n"}'
```

The setup-created pool uses
`sandbox.gke.io/runtime=gvisor:NoSchedule`, which the WorkerPool manifest
below explicitly tolerates. If your selected pool uses a different taint,
adjust the toleration to match it.

---

## Step 2: Build and push the current Everything MCP image

The current official Everything source and npm package support native
Streamable HTTP, but the published `mcp/everything` image used by older
examples contains a stale stdio-only build. Build the official npm release's
exact Git commit and push it to the same registry used for Substrate images.

Pin both the package version and its npm provenance commit so rerunning this
lab cannot silently build different source:

```bash
export EVERYTHING_VERSION="2026.7.4"
export EVERYTHING_GIT_SHA="6dd0a683e198783e30feabf7abaf42f925bd18b1"
export EVERYTHING_IMAGE_TAG="${KO_DOCKER_REPO}/everything-mcp:${EVERYTHING_VERSION}"

export EVERYTHING_SRC="$(mktemp -d)/servers"
git clone https://github.com/modelcontextprotocol/servers.git "$EVERYTHING_SRC"
git -C "$EVERYTHING_SRC" checkout --detach "$EVERYTHING_GIT_SHA"
test "$(git -C "$EVERYTHING_SRC" rev-parse HEAD)" = "$EVERYTHING_GIT_SHA"
```

The upstream Dockerfile uses a BuildKit cache mount. Create a small Cloud
Build definition that enables BuildKit and builds that Dockerfile from the
repository root:

```bash
cat >"$EVERYTHING_SRC/cloudbuild.everything.yaml" <<'EOF'
steps:
- name: gcr.io/cloud-builders/docker
  env:
  - DOCKER_BUILDKIT=1
  args:
  - build
  - --file
  - src/everything/Dockerfile
  - --tag
  - ${_IMAGE}
  - .
images:
- ${_IMAGE}
EOF

gcloud builds submit "$EVERYTHING_SRC" \
  --project="$PROJECT_ID" \
  --config="$EVERYTHING_SRC/cloudbuild.everything.yaml" \
  --substitutions="_IMAGE=$EVERYTHING_IMAGE_TAG"
```

ActorTemplate images must be immutable because changing an image invalidates
its snapshots. Resolve the pushed tag to its registry digest and use only that
digest-qualified reference below:

```bash
export EVERYTHING_IMAGE_DIGEST=$(gcloud container images describe \
  "$EVERYTHING_IMAGE_TAG" --format='value(image_summary.digest)')
export MCP_IMAGE="${KO_DOCKER_REPO}/everything-mcp@${EVERYTHING_IMAGE_DIGEST}"

: "${EVERYTHING_IMAGE_DIGEST:?failed to resolve the pushed image digest}"
printf 'MCP_IMAGE=%s\n' "$MCP_IMAGE"
```

For release `2026.7.4`, the validated image contains
`node /app/dist/index.js streamableHttp` and serves the session-based MCP
endpoint at `/mcp`.

---

## Step 3: Deploy the MCP ActorTemplate and one warm worker

The WorkerPool is still a Kubernetes CRD, applied with `ko`:

```bash
cat <<EOF | ./hack/run-tool.sh ko apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: mcp-substrate
---
apiVersion: ate.dev/v1
kind: WorkerPool
metadata:
  name: mcp-tools
  namespace: mcp-substrate
  labels:
    workload: mcp-tools
spec:
  replicas: 1
  workerImage: ko://go.ate.dev/substrate/cmd/ateworker-gvisor
  sandboxClasses:
  - name: gvisor
  template:
    nodeSelector:
      cloud.google.com/gke-nodepool: ${SUBSTRATE_NODE_POOL}
    tolerations:
    - key: sandbox.gke.io/runtime
      operator: Equal
      value: gvisor
      effect: NoSchedule
    # Worker capacity comes from the limits; the actor below asks for
    # 1 CPU and 512Mi.
    resources:
      limits:
        cpu: "1"
        memory: 1Gi
      requests:
        cpu: 250m
        memory: 1Gi
EOF
```

The ActorTemplate is no longer a CRD. It is an ate API record that lives in
an atespace, so create the atespace first, then the template:

```bash
kubectl ate create atespace tools

cat <<EOF | kubectl ate create actor-template -f -
metadata:
  atespace: tools
  name: everything-mcp
workerSelector:
  matchLabels:
    workload: mcp-tools
containers:
- name: mcp
  image: ${MCP_IMAGE}
  command:
  - node
  - /app/dist/index.js
  - streamableHttp
  env:
  - name: PORT
    value: "80"
resources:
  limits:
    cpuMillicores: 1000
    memoryBytes: 536870912 # 512Mi
snapshotConfig:
  preferredFidelity: SNAPSHOT_FIDELITY_MEMORY
EOF
```

The upstream server does not expose a dedicated HTTP readiness endpoint, so
this template intentionally omits `wakeupProbe`. Substrate applies its ~20s
golden-actor warmup before taking the golden snapshot; subsequent resumes
restore the already-listening socket with the process. `MEMORY` fidelity is
what keeps the in-memory MCP session across suspend/resume in Part 2.

Ensure everything is up and operational

```bash
kubectl get workerpool,pods -n mcp-substrate
kubectl ate get actor-templates -a tools
```

Wait until the template's `GOLDEN TAG` is set before creating the actor.

---

## Step 4: Create the MCP actor

Create one actor named `everything` in the `tools` atespace. `--template`
resolves the template by name within the actor's own atespace:

```bash
kubectl ate create actor everything \
  --template everything-mcp \
  --atespace tools
```

```bash
kubectl ate get actor everything --atespace tools
```

The actor should show:

```text
ACTOR_STATE_SUSPENDED   WORKER POD: <none>
```

Its address exists even while its process does not. There is no actor DNS
name anymore: a client reaches the actor through `atenet-router` and names it
with the header:

```text
ate-target-actor: tools/everything
```

The worker is chosen only when a request arrives. You'll see in the next
section that this header is what agentgateway has to send so traffic can be
routed to the MCP Server running in the Substrate Actor

---

## Step 5: Put agentgateway in front of the actor

Create a Gateway, an MCP-aware backend, and a route.

In v1.0.0 the backend's target is the `atenet-router` Service, and the actor
is named by a header, not by DNS. The router contract is:

- **Target:** `atenet-router.ate-system.svc`, port `443` (HTTPS only; the
  router no longer serves plain HTTP).
- **Client certificate:** agentgateway must present a Pod Identity
  certificate (signer `podidentity.podcert.ate.dev/identity`) whose SPIFFE ID
  is in the install's `--ingress-allowed-spiffe-ids`, for example
  `spiffe://cluster.local/ns/<agentgateway-namespace>/sa/<agentgateway-sa>`.
- **Server CA:** verify the router against the `servicedns.podcert.ate.dev/identity`
  ClusterTrustBundle (label `podcert.ate.dev/canarying: live`).
- **Actor:** set `ate-target-actor: tools/everything` on every upstream
  request. atenet resumes the actor named there; `Host` is application
  metadata only.

> **TODO (v1.0.0):** Not verified for the Kubernetes agentgateway CRDs:
> mounting the Pod Identity `podCertificate` and the router CA into the
> agentgateway proxy pod, pointing the MCP backend's backend TLS at them,
> and setting the `ate-target-actor` request header on the MCP target. The
> manifests below are the pre-v1.0.0 version of this step. Their backend
> targets `everything.tools.actors.resources.substrate.ate.dev:80` over plain
> HTTP, and that DNS name, the stub domain, and the Host-header routing no
> longer exist, so the backend will not route as written. The previous
> `hostRewrite: Auto` policy (`substrate-actor-host`) is dropped for the same
> reason. Until the backend is reworked, use the interim path at the end of
> this step.

```bash
kubectl apply -f - <<'EOF'
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: mcp-substrate-gateway
  namespace: mcp-substrate
spec:
  gatewayClassName: enterprise-agentgateway
  listeners:
  - name: http
    protocol: HTTP
    port: 8080
    allowedRoutes:
      namespaces:
        from: Same
---
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayBackend
metadata:
  name: substrate-mcp
  namespace: mcp-substrate
spec:
  mcp:
    sessionRouting: Stateful
    targets:
    - name: everything
      static:
        host: everything.tools.actors.resources.substrate.ate.dev
        port: 80
        protocol: StreamableHTTP
        path: /mcp
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: substrate-mcp
  namespace: mcp-substrate
spec:
  parentRefs:
  - name: mcp-substrate-gateway
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /mcp
    backendRefs:
    - group: agentgateway.dev
      kind: AgentgatewayBackend
      name: substrate-mcp
EOF
```

Ensure the resources were created.

```bash
kubectl get all -n mcp-substrate
```

### Interim path: reach the actor with `kubectl ate proxy`

Until the backend above is reworked, `kubectl ate proxy actor` gives you a
verified route to the actor through `atenet-router`. It opens an mTLS
CONNECT tunnel to the router with `ate-target-actor: tools/everything`, so
every request still goes through atenet's resume-on-request path. It skips
agentgateway, so Step 7's gateway logs do not apply on this path.

```bash
kubectl ate proxy actor everything -a tools >/tmp/pf-agw-substrate.log 2>&1 &

export PF_PID=$!
export MCP_URL=http://localhost:8000/mcp
MCP_HEADERS=(-H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream')
```

This forwards `127.0.0.1:8000` to the actor's port 80. Skip the
port-forward in Step 6 if you use this path; the rest of the lab is
unchanged.

---

## Step 6: First MCP request wakes the suspended Actor

Port-forward agentgateway. Do not port-forward atenet; every MCP request in
this lab must pass through both layers. (On the Step 5 interim path, skip
this block: `kubectl ate proxy` already set `MCP_URL` and `MCP_HEADERS`.)

```bash
kubectl -n mcp-substrate port-forward \
  svc/mcp-substrate-gateway 8080:8080 >/tmp/pf-agw-substrate.log 2>&1 &

export PF_PID=$!
export MCP_URL=http://localhost:8080/mcp
MCP_HEADERS=(-H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream')
```

Confirm the actor is still suspended immediately before the call:

```bash
kubectl ate get actor everything --atespace tools
```

Now initialize an MCP session. Preserve both headers and body so an HTTP
error is not hidden by the SSE parser. A successful response contains the
MCP session ID (agentgateway's client session ID when it is in the path);
keep it for every later request.

```bash
HTTP_STATUS=$(curl -sS -D /tmp/mcp-substrate-headers.txt \
  -o /tmp/mcp-substrate-body.txt \
  -w '%{http_code}' \
  "${MCP_HEADERS[@]}" "$MCP_URL" -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"initialize",
    "params":{
      "protocolVersion":"2025-03-26",
      "capabilities":{},
      "clientInfo":{"name":"agw-substrate-demo","version":"1.0"}
    }
  }')

printf 'HTTP %s\n' "$HTTP_STATUS"
sed -n 's/^data: //p' /tmp/mcp-substrate-body.txt > /tmp/mcp-substrate-json.txt

if [ -s /tmp/mcp-substrate-json.txt ]; then
  jq . /tmp/mcp-substrate-json.txt
else
  cat /tmp/mcp-substrate-body.txt
fi

if [ "$HTTP_STATUS" = "200" ]; then
  export MCP_SID=$(sed -n \
    's/^[Mm][Cc][Pp]-[Ss]ession-[Ii][Dd]:[[:space:]]*//p' \
    /tmp/mcp-substrate-headers.txt | tr -d '\r')

  : "${MCP_SID:?initialize succeeded but returned no MCP session ID}"
  printf 'MCP session: %s\n' "$MCP_SID"
else
  printf 'Initialization failed; inspect the response above before continuing.\n' >&2
fi
```

Do not continue to `notifications/initialized` or `tools/list` unless the
status is `HTTP 200` and `$MCP_SID` is non-empty. For example, a router
`HTTP 503` is a routing/backend failure, not an MCP response.

The first call is slower than a warm request because this happened inside
the request path:

1. agentgateway (or `kubectl ate proxy`) sent the request to `atenet-router`
   over mTLS with `ate-target-actor: tools/everything`.
2. atenet read `tools/everything` from the `ate-target-actor` header.
3. atenet called `ResumeActor`.
4. The MCP process was restored from the template's golden snapshot into the
   warm worker.
5. The router's dataplane (Envoy or agentgateway, per `--atenet-dataplane`)
   forwarded the request to the worker on port 80.
6. The restored MCP server handled `initialize`.

Verify the actor is now running and bound to the one worker:

```bash
kubectl ate get actor everything --atespace tools
kubectl ate get workers
```

Complete the MCP handshake and list the tools:

```bash
curl -sS "${MCP_HEADERS[@]}" -H "Mcp-Session-Id: $MCP_SID" \
  "$MCP_URL" -d '{
    "jsonrpc":"2.0",
    "method":"notifications/initialized"
  }' >/dev/null

curl -sS "${MCP_HEADERS[@]}" -H "Mcp-Session-Id: $MCP_SID" \
  "$MCP_URL" -d '{
    "jsonrpc":"2.0",
    "id":2,
    "method":"tools/list"
  }' | sed -n 's/^data: //p' | jq -r '.result.tools[].name'
```

You should see tools such as `echo`, `add`, and `printEnv`.

---

## Step 7: Warm tool call

Call the `echo` tool while the actor is already running:

```bash
time curl -sS "${MCP_HEADERS[@]}" -H "Mcp-Session-Id: $MCP_SID" \
  "$MCP_URL" -d '{
    "jsonrpc":"2.0",
    "id":3,
    "method":"tools/call",
    "params":{
      "name":"echo",
      "arguments":{"message":"warm call through agentgateway"}
    }
  }' | sed -n 's/^data: //p' | jq .
```

This is the baseline: agentgateway's MCP handling plus two HTTP proxies,
with no actor restore in the path.

You can ensure that the traffic is going through agentgateway by looking at the logs (not on the Step 5 interim path, which bypasses agentgateway).

```bash
kubectl logs mcp-substrate-gateway-xxxx-xxxx -n mcp-substrate

2026-07-12T20:26:37.149854Z     info    request gateway=mcp-substrate/mcp-substrate-gateway listener=http route=mcp-substrate/substrate-mcp src.addr=127.0.0.1:45314 http.method=POST http.host=localhost http.path=/mcp http.version=HTTP/1.1 http.status=200 protocol=mcp mcp.method.name=tools/list mcp.session.id=ck5HjlyZpIouulDAq4oG4E0NikEY3vn7/UgTutxdMGS4rSc3nYLVIRtGg07C3gFcQe9Wu+TswukRUMkIKxJel4E9wYBCYuQ60mcmhT6twVM3uq/QujzvRkJ4qy1noYWad1+UTY9RH89juEM= duration=64ms
2026-07-12T20:28:00.857219Z     info    request gateway=mcp-substrate/mcp-substrate-gateway listener=http route=mcp-substrate/substrate-mcp src.addr=127.0.0.1:56158 http.method=POST http.host=localhost http.path=/mcp http.version=HTTP/1.1 http.status=200 protocol=mcp mcp.method.name=tools/call mcp.target=everything mcp.resource.type=tool gen_ai.tool.name=echo mcp.session.id=ck5HjlyZpIouulDAq4oG4E0NikEY3vn7/UgTutxdMGS4rSc3nYLVIRtGg07C3gFcQe9Wu+TswukRUMkIKxJel4E9wYBCYuQ60mcmhT6twVM3uq/QujzvRkJ4qy1noYWad1+UTY9RH89juEM= duration=69ms
2026-07-12T20:28:36.821233Z     info    request gateway=mcp-substrate/mcp-substrate-gateway listener=http route=mcp-substrate/substrate-mcp src.addr=127.0.0.1:35964 http.method=POST http.host=localhost http.path=/mcp http.version=HTTP/1.1 http.status=200 protocol=mcp mcp.method.name=tools/call mcp.target=everything mcp.resource.type=tool gen_ai.tool.name=echo mcp.session.id=ck5HjlyZpIouulDAq4oG4E0NikEY3vn7/UgTutxdMGS4rSc3nYLVIRtGg07C3gFcQe9Wu+TswukRUMkIKxJel4E9wYBCYuQ60mcmhT6twVM3uq/QujzvRkJ4qy1noYWad1+UTY9RH89juEM= duration=1556ms
```

---

# Part 2: Scale

## Step 1: Scale the MCP server to zero

Suspend the actor while keeping agentgateway and the client session alive:

```bash
kubectl ate suspend actor everything --atespace tools
kubectl ate get actor everything --atespace tools
kubectl ate get workers
```

The actor now shows `ACTOR_STATE_SUSPENDED` and `WORKER POD` `<none>`; the
worker shows no assigned actor. The `mcp/everything` process is gone from
compute. Its RAM, filesystem, open listener, and server-side MCP session
state are in the snapshot (by default `suspend` uploads it to storage in the
background; add `--mode=sync` to wait for the upload).

agentgateway still exposes `$MCP_URL`, and the client still holds `$MCP_SID`.

---

## Step 2: First tool call wakes it, same MCP session

Do **not** initialize a new session. Reuse the same session ID and call the
same tool again:

```bash
time curl -sS "${MCP_HEADERS[@]}" -H "Mcp-Session-Id: $MCP_SID" \
  "$MCP_URL" -d '{
    "jsonrpc":"2.0",
    "id":4,
    "method":"tools/call",
    "params":{
      "name":"echo",
      "arguments":{"message":"this call woke a suspended MCP actor"}
    }
  }' | sed -n 's/^data: //p' | jq .
```

The tool call succeeds. That single result proves two separate things:

- **Routing wake-up:** the request reached atenet with
  `ate-target-actor: tools/everything`; atenet restored the suspended actor
  before forwarding it.
- **MCP state survival:** the old `$MCP_SID` remained valid. The MCP server's
  in-memory session manager was checkpointed and restored with the process.

Confirm the actor is running again:

```bash
kubectl ate get actor everything --atespace tools
```

Compare the `time` output from Part 1's warm tool call and this restored tool
call. The difference is the visible cost of restoring the tool server.
Subsequent calls return to warm latency.

This is stronger than restarting a Deployment: a restarted stateless pod
could serve a new MCP handshake, but it would not preserve an in-memory MCP
session through process termination. Substrate thawed the same server state.

---

## Cleanup

Stop the port-forward (or `kubectl ate proxy`), then suspend and delete the
actor and its template before deleting their atespace:

```bash
kill "$PF_PID" 2>/dev/null

kubectl ate suspend actor everything --atespace tools 2>/dev/null
kubectl ate delete actor everything --atespace tools
kubectl ate delete actor-template everything-mcp --atespace tools
kubectl ate delete atespace tools
```

Deleting the template also deletes its golden actor and golden snapshot.

Delete agentgateway and Substrate demo resources. The main Substrate and
agentgateway control planes remain installed:

```bash
kubectl delete namespace mcp-substrate
```

Actor snapshot objects live under the install's `SNAPSHOT_LOCATION` (for
example `gs://${BUCKET_NAME}/`). If any remain after the actor and template
are deleted, remove them manually.

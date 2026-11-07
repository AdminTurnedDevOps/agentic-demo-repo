# Run OpenFGA permissions in front of Substrate Actors

This lab runs an **OSS agentgateway** in front of the Substrate router. It
checks OpenFGA before forwarding to Substrate, so a denied call to a suspended
Actor does not wake it. Alice can invoke `tool-a`; Bob and `tool-b` are denied.
The same permission remains valid when `tool-a` suspends and resumes onto a
different worker. Grant and revoke permissions without restarting an Actor.

This is a working **user-to-Actor** lab. Substrate v1.0.0 can now hand a
verified Actor identity to a service an Actor calls, but this lab doesn't use
it yet; see [Actor-to-Actor extension](#actor-to-actor-extension).

```text
client (short-lived Kubernetes service-account token)
  -> lab agentgateway OSS (:8080)
     -> HTTP extAuthz adapter -> Kubernetes TokenReview (caller)
                           -> Substrate GetActor (current target UID)
                           -> OpenFGA Check(user, can_invoke, actor:UID)
     -> allow: mTLS (pod-identity cert) -> Substrate atenet-router :443
               -> ResumeActor -> worker -> Actor
     -> deny: HTTP 403; Substrate router never sees the request
```

The lab gateway is **separate** from Substrate's own router dataplane. The
Substrate installation may use `--atenet-dataplane=agentgateway` or the
default Envoy; either way, that router still handles Actor wake and tunnel
forwarding. A separate
gateway lets us add authorization without replacing Substrate's ConfigMap or
restarting its shared router. An `AgentgatewayPolicy` Gateway API CRD does not
configure Substrate's static agentgateway sidecar.

The lab's OpenFGA is also separate from the one in Substrate. In v1.0.0,
`ate-api-server` embeds OpenFGA to authorize **Control API** calls, using
[access policies](https://github.com/agent-substrate/substrate/blob/v1.0.0/docs/guides/authorization.md)
that grant roles per atespace. It doesn't authorize **requests to Actors**:
the router lets any client on its `--ingress-allowed-spiffe-ids` allowlist
reach any Actor. This lab adds that missing per-Actor check, on its own
OpenFGA store.

## Prerequisites

- A working Substrate v1.0.0 cluster with the [counter demo](https://github.com/agent-substrate/substrate/blob/v1.0.0/demos/counter/README.md), `kubectl-ate`, and permission to create an isolated namespace, two demo service accounts, and a TokenReview ClusterRole/Binding.
- A `kubectl ate` identity that can create an access policy on the `ate-demo-counter` atespace. By default, `kubectl ate` acts as the shared `ate-client` ServiceAccount, which `ate-setup` makes a bootstrap owner.
- Permission to re-run `ate-setup deploy atenet` to change `--ingress-allowed-spiffe-ids`.
- `kubectl`, `helm`, Python 3, Docker with Buildx, and a registry to which you can push an adapter image. Keep your current Kubernetes context pointed at the intended cluster; the commands below create resources there.
- Kubernetes PodCertificate and ClusterTrustBundle support as used by the installed Substrate API. The adapter mounts the same service-DNS trust bundle and calls `api.ate-system.svc:443` with a projected service-account JWT for audience `api.ate-system.svc`. The config `ate-setup` writes trusts that audience; if yours does not, configure the adapter and server to agree first.

All commands in this guide run from `substrate/policy-and-permission/openfga/`
in this repository, except where a command explicitly says to use the
Substrate checkout. Install Substrate as in [the setup lab](../../install-and-setup/setup-gke.md).
On kind, the v1.0.0 quickstart runs `hack/create-kind-cluster.sh`, then
`ATE_INSTALL_KIND=true go run ./cmd/ate-setup deploy ate-system ...`, **from
the Substrate checkout**. Add `--atenet-dataplane=agentgateway` to the
`deploy` command for an agentgateway router. Do not run
`hack/create-kind-cluster.sh` against an existing kind cluster: it deletes and
recreates the selected cluster. This lab works with either router dataplane;
the *front* gateway is OSS agentgateway in both cases.

## 1. Create the Actors and OpenFGA

Install the counter fixture if it is not already present (from the Substrate
checkout: `go run ./cmd/ate-setup deploy demo counter`). Then run:

```sh
kubectl ate create actor tool-a -a ate-demo-counter --template counter
kubectl ate create actor tool-b -a ate-demo-counter --template counter
kubectl ate get actor tool-a -a ate-demo-counter -o json
kubectl ate get actor tool-b -a ate-demo-counter -o json
```

Creation leaves Actors suspended. This lab addresses each Actor by its
Substrate-generated metadata UID (`.metadata.uid` in the output above) in
OpenFGA, so reusing an Actor's name after deletion does not inherit its
permissions.

Deploy OpenFGA v1.21.0 with Helm chart 0.3.15 and a single in-memory replica:

```sh
make setup
kubectl -n openfga-actors get pods
```

`make setup` creates only the lab namespace and an `openfga` Helm release
(one replica, in-memory datastore, playground off). The in-memory
store is intentionally disposable: if the OpenFGA pod restarts, rerun the
bootstrap and then run
`kubectl -n openfga-actors rollout restart deployment/openfga-actors-auth`
so the adapter picks up the new store/model IDs.
Do not expose this unauthenticated OpenFGA Service outside the cluster. For a
persistent deployment, replace the in-memory datastore with a separately
configured persistent OpenFGA backend.

Port-forward OpenFGA in a **second terminal**:

```sh
kubectl -n openfga-actors port-forward svc/openfga 8082:8080
```

Back in the first terminal, bootstrap the store, model, and Alice's one grant:

```sh
python3 bootstrap.py
python3 manage.py check alice tool-a  # allowed: true
python3 manage.py check alice tool-b  # allowed: false
```

`bootstrap.py` reads the live Actor UIDs via `kubectl ate`, writes the model in
[`model.json`](model.json), seeds `user:alice` -> `actor:<tool-a-uid>`
and creates the `openfga-actors-ids` ConfigMap. Run it once per OpenFGA store;
each invocation creates a new store. The adapter looks up the **current** UID
via Substrate `GetActor` on every request, not via this bootstrap snapshot.

## 2. Build and deploy the authorization adapter and gateway

The adapter calls Substrate's API, which v1.0.0 guards twice. A
NetworkPolicy admits callers only from namespaces labeled
`ate.dev/api-access=true`; [`namespace.yaml`](namespace.yaml) already sets
that label on `openfga-actors`. Access policies then authorize each call, and
`GetActor` needs at least `viewer` on the Actor's atespace. Grant that to the
adapter's ServiceAccount:

```sh
cat > counter-viewer-policy.yaml <<'EOF'
bindings:
- role: viewer
  members:
  - user:system:serviceaccount:openfga-actors:openfga-actors-auth
EOF
kubectl ate create access-policy -a ate-demo-counter -f counter-viewer-policy.yaml
```

If `ate-demo-counter` already has an access policy, `create` refuses. Instead,
run `kubectl ate get access-policy -a ate-demo-counter -o yaml > current.yaml`,
add the binding, and run `kubectl ate update access-policy -a ate-demo-counter -f current.yaml`.
`viewer` lets the adapter read Actors, nothing more: it can't resume, suspend
or delete them.

The router accepts only clients whose SPIFFE ID is on its allowlist. Add the
lab gateway's pod-identity ID next to the `atenet-client` ID that
`kubectl ate proxy` uses. Redeploy atenet from the install record that
[the setup lab](../../install-and-setup/setup-gke.md) wrote, with the full list. Each deploy replaces
the allowlist, so keep `atenet-client` in it:

```sh
# from the Substrate checkout
go run ./cmd/ate-setup deploy atenet \
  --config ~/Library/Caches/ate-setup/installs/<context>.yaml \
  --ingress-allowed-spiffe-ids=spiffe://cluster.local/ns/ate-system/sa/atenet-client,spiffe://cluster.local/ns/openfga-actors/sa/openfga-actors-gateway
```

Choose a **new, pullable** registry tag. For example, use your registry path
and a unique tag rather than overwriting an existing image:

```sh
export IMAGE="YOUR_REGISTRY/openfga-actors-auth:v0.1.0-unique"
make build IMAGE="$IMAGE"
make deploy IMAGE="$IMAGE"
kubectl -n openfga-actors get deploy,svc
```

`make build` pushes a multi-architecture image. `make deploy` uses the image
reference to apply the adapter Deployment and the pinned agentgateway v1.5.0
Deployment, which runs as the `openfga-actors-gateway` ServiceAccount. The adapter is in
[`adapter/server.py`](adapter/server.py); its wire-compatible subset of
Substrate `GetActor` is in
[`adapter/ateapi_subset.proto`](adapter/ateapi_subset.proto).
Confirm the proto package (`substrate.ateapi.v1` in v1.0.0) and field numbers
against `api/ateapi/v1/ateapi.proto` in the Substrate checkout if using a
different API revision.

The gateway configuration in [`gateway.yaml`](gateway.yaml) forwards
`authorization` and `ate-target-actor` **to extAuthz**, then removes the
client's bearer token before the request reaches the Actor. It keeps
`ate-target-actor`, which tells the router which Actor to route to. The adapter calls
the Kubernetes TokenReview API with audience `openfga-actors`; only the
`openfga-actors/alice` and `openfga-actors/bob` service accounts are recognized.
It fails closed if OpenFGA or Substrate is unavailable. The gateway itself
also denies when the adapter is unavailable. Its HTTP ext-authz timeout is
10 seconds so three backend lookups can complete on a cold connection.

Allowed requests go to `atenet-router.ate-system.svc:443` over mTLS. A
`podCertificate` projected volume gives the gateway pod a certificate for
`spiffe://cluster.local/ns/openfga-actors/sa/openfga-actors-gateway`, the ID
you allowlisted above. The same volume carries the `servicedns` trust bundle
the gateway verifies the router against. agentgateway's `backendTLS` reads
the combined `credential-bundle.pem` as both `cert` and `key`, and watches
the files, so it should pick up rotated certificates. If allowed calls
start failing with TLS errors after the pod has run for a while, restart
the gateway with
`kubectl -n openfga-actors rollout restart deployment/openfga-actors-gateway`.

Port-forward the **lab** gateway in a third terminal:

```sh
kubectl -n openfga-actors port-forward svc/openfga-actors-gateway 18080:8080
```

## 3. Run the allow / deny / revoke demonstration

Issue two short-lived tokens for the lab's Kubernetes service accounts:

```sh
ALICE_TOKEN=$(kubectl -n openfga-actors create token alice --audience=openfga-actors)
BOB_TOKEN=$(kubectl -n openfga-actors create token bob --audience=openfga-actors)
```

Keep these tokens out of files and logs. Send the **same** POST the counter
demo uses, but through the protected gateway:

```sh
curl -i -X POST -H "Authorization: Bearer $ALICE_TOKEN" \
  -H 'ate-target-actor: ate-demo-counter/tool-a' http://127.0.0.1:18080/
kubectl ate get actor tool-a -a ate-demo-counter
```

Expected: `200`, a body like `preserved memory count: 1 | preserved file
counter: 1 | preserved rootfs counter: 1`, and `tool-a` RUNNING. Now show that
permission is selective. Suspend `tool-a` first so a later call resumes it,
possibly on another worker. The v1.0.0 counter pool has three workers, so this
step doesn't free a worker for `tool-b`.

```sh
kubectl ate suspend actor tool-a -a ate-demo-counter
curl -i -X POST -H "Authorization: Bearer $ALICE_TOKEN" \
  -H 'ate-target-actor: ate-demo-counter/tool-b' http://127.0.0.1:18080/
kubectl ate get actor tool-b -a ate-demo-counter
curl -i -X POST -H "Authorization: Bearer $BOB_TOKEN" \
  -H 'ate-target-actor: ate-demo-counter/tool-a' http://127.0.0.1:18080/
```

Expected: both calls return `403`, and `tool-b` stays SUSPENDED. Calling with
no bearer token returns `401`. No denied request should cause a Substrate
`ResumeActor` event. Changing an `x-user` header must not change the result.

Grant Bob access and then revoke Alice's access (the OpenFGA port-forward from
step 1 must still be running):

```sh
python3 manage.py grant bob tool-b
curl -i -X POST -H "Authorization: Bearer $BOB_TOKEN" \
  -H 'ate-target-actor: ate-demo-counter/tool-b' http://127.0.0.1:18080/
kubectl ate suspend actor tool-b -a ate-demo-counter
python3 manage.py revoke alice tool-a
curl -i -X POST -H "Authorization: Bearer $ALICE_TOKEN" \
  -H 'ate-target-actor: ate-demo-counter/tool-a' http://127.0.0.1:18080/
```

Expected: Bob's new grant permits the wake; Alice's revoked call returns
`403` while `tool-a` stays suspended. Re-grant Alice, call again, and compare
the counter. The counter template uses MEMORY snapshot fidelity, so both its
in-memory and its file counts survive the snapshot, whichever worker runs
the Actor next.

```sh
python3 manage.py grant alice tool-a
curl -i -X POST -H "Authorization: Bearer $ALICE_TOKEN" \
  -H 'ate-target-actor: ate-demo-counter/tool-a' http://127.0.0.1:18080/
```

## Verify locally and clean up

The following checks run locally without changing your cluster. Only the
explicitly named temporary containers are started; the `docker stop` command
removes them because they were started with `--rm`:

```sh
make test
docker run --rm -d --name openfga-actors-local -p 18082:8080 \
  openfga/openfga:v1.21.0 run --datastore-engine memory
python3 integration_test.py
docker stop openfga-actors-local
CERTS=$(mktemp -d)  # throwaway files so the backendTLS paths resolve
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
  -keyout "$CERTS/k.pem" -out "$CERTS/router-ca.pem" -days 1 -subj /CN=test
cat "$CERTS/k.pem" "$CERTS/router-ca.pem" > "$CERTS/credential-bundle.pem"
chmod 644 "$CERTS"/*.pem
docker run --rm -v "$CERTS:/run/router-client:ro" \
  cr.agentgateway.dev/agentgateway:v1.5.0 --validate-only \
  -c "$(kubectl create --dry-run=client -f gateway.yaml -o jsonpath='{.data.config\.yaml}')"
rm -rf "$CERTS"
kubectl apply --dry-run=client \
  -f namespace.yaml -f auth.yaml -f gateway.yaml
```

If the lab port-forward is still using `8082`, local model verification uses
`18082` so the two do not conflict. `make test` builds and runs adapter unit
tests; `integration_test.py` creates a disposable OpenFGA store and checks
grant, deny, cross-target deny and revocation. To remove **only the lab
resources you created** after stopping the port-forwards:

```sh
kubectl ate delete actor tool-a -a ate-demo-counter
kubectl ate delete actor tool-b -a ate-demo-counter
kubectl ate delete access-policy -a ate-demo-counter
make clean
```

Deleting an Actor works in any state, so there is no need to suspend first. If
`ate-demo-counter` had an access policy before this lab, don't delete it:
remove the adapter's binding with `get`/`update` as in step 2. Also re-run the
`deploy atenet --config ...` command from step 2 without the lab gateway's
SPIFFE ID, so that
anything later created as `openfga-actors/openfga-actors-gateway` can't reach
Actors.

`make clean` deletes the lab gateway/adapter and their ServiceAccounts, the
lab TokenReview binding, the `openfga` Helm release, and the dedicated `openfga-actors` namespace. It
does not uninstall Substrate or the shared counter template/pool.

## Actor-to-Actor extension

OpenFGA's model permits `actor:<planner-uid>` as the subject of an
`allowed_caller` relationship. **Do not use an Actor-controlled header to
demonstrate that grant.** Substrate's router still doesn't tell a backend who
the calling Actor is. In v1.0.0, though, the **egress gateway** can: it
authenticates the outbound Actor by its certificate and a live-Actor lookup,
and an EgressPolicy `replaceHeaders` entry with `actorJwt` makes it inject a
short-lived JWT that `ate-api-server` mints for that Actor. Only the egress
gateway can mint these tokens (`MintActorJwt`); not even a global owner
can. The token's `sub` is `actor/<atespace>/<name>`, and its `actor.ate.dev`
claim carries the Actor's `actorUID`. See
[Actor JWTs](https://github.com/agent-substrate/substrate/blob/v1.0.0/docs/guides/actor-jwts.md)
and [egress credential injection](https://github.com/agent-substrate/substrate/blob/v1.0.0/docs/guides/egress-credential-injection.md#actor-jwts).

A peer-call extension would give the planner an egress policy that injects
an actor JWT with audience `openfga-actors` on its calls to the lab gateway.
The adapter would then verify the token against `ate-idp-server`'s discovery
document and keys, and use `actor:<actorUID>` as the subject. The adapter
doesn't do this yet. Note that the gateway caches tokens by Actor *name*, so
for up to two thirds of a token's lifetime a recreated Actor can present its
predecessor's UID. This lab's executable test uses Kubernetes-authenticated
human/demo principals; the Actor relationship is a next integration step, not
a property of this deployment.

## Scope

The lab gateway Service is ClusterIP and reached from your machine via
port-forward. **Any other client on the router's
`--ingress-allowed-spiffe-ids` allowlist bypasses this lab gateway**,
including `kubectl ate proxy` (`atenet-client`). Anyone with RBAC to create
PodCertificateRequests in `ate-system` can obtain that identity. To use this
pattern as an actual security boundary, list only the lab gateway's
identity. Likewise, protect OpenFGA's API and tuple-write credentials outside
this isolated lab. This configuration gates ordinary HTTP requests, not the
router's separate CONNECT ingress listener. It doesn't gate Substrate Control
RPCs either; Substrate's own access policies authorize those. Check the pinned [agentgateway
configuration schema](https://agentgateway.dev/schema/config), [Substrate's
router trust model](https://github.com/agent-substrate/substrate/blob/v1.0.0/cmd/atenet/internal/router/README.md), and [OpenFGA Check
API](https://openfga.dev/docs/getting-started/perform-check) if adapting it
to another deployment.

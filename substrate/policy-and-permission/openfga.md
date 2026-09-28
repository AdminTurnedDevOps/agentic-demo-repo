# Run OpenFGA permissions in front of Substrate Actors

This lab runs an **OSS agentgateway** in front of the Substrate router. It
checks OpenFGA before forwarding to Substrate, so a denied call to a suspended
Actor does not wake it. Alice can invoke `tool-a`; Bob and `tool-b` are denied.
The same permission remains valid when `tool-a` suspends and resumes onto a
different worker. Grant and revoke permissions without restarting an Actor.

This is a working **user-to-Actor** lab. A verified Actor-to-Actor caller is
not yet available at Substrate ingress; see [Actor-to-Actor extension](#actor-to-actor-extension).

```text
client (short-lived Kubernetes service-account token)
  -> lab agentgateway OSS (:8080)
     -> HTTP extAuthz adapter -> Kubernetes TokenReview (caller)
                           -> Substrate GetActor (current target UID)
                           -> OpenFGA Check(user, can_invoke, actor:UID)
     -> allow: Substrate atenet-router -> ResumeActor -> worker -> Actor
     -> deny: HTTP 403; Substrate router never sees the request
```

The lab gateway is **separate** from Substrate's agentgateway dataplane. The
Substrate installation may use its existing `--atenet-router=agentgateway`
option; that route still handles Actor wake and tunnel forwarding. A separate
gateway lets us add authorization without replacing Substrate's ConfigMap or
restarting its shared router. An `AgentgatewayPolicy` Gateway API CRD does not
configure Substrate's static agentgateway sidecar.

## Prerequisites

- A working Substrate cluster with the [counter demo](https://github.com/agent-substrate/substrate/blob/main/demos/counter/README.md), `kubectl-ate`, and permission to create an isolated namespace, two demo service accounts, and a TokenReview ClusterRole/Binding.
- `kubectl`, `helm`, Python 3, Docker with Buildx, and a registry to which you can push an adapter image. Keep your current Kubernetes context pointed at the intended cluster; the commands below create resources there.
- Kubernetes PodCertificate and ClusterTrustBundle support as used by the installed Substrate API. The adapter mounts the same service-DNS trust bundle and calls `api.ate-system.svc:443` with a projected service-account JWT for audience `api.ate-system.svc`. The default Substrate auth configuration trusts that audience; if yours does not, configure the adapter and server to agree first.

All commands in this guide run from `substrate/policy-and-permission/openfga/`
in this repository, except where a command explicitly says to use the
Substrate checkout. On kind, to install Substrate with agentgateway as its
dataplane, use `./hack/install-ate-kind.sh --deploy-ate-system
--atenet-router=agentgateway` **from the Substrate checkout**. Do not run its
cluster-creation script against an existing kind cluster: it recreates the
selected cluster. This lab also works when Substrate uses its default Envoy
dataplane; the *front* gateway remains OSS agentgateway in either case.

## 1. Create the Actors and OpenFGA

Install the counter fixture if it is not already present (from the Substrate
checkout, use the installer appropriate to your cluster; on kind:
`./hack/install-ate-kind.sh --deploy-demo-counter`). Then run:

```sh
kubectl ate create actor tool-a -a ate-demo-counter --template counter
kubectl ate create actor tool-b -a ate-demo-counter --template counter
kubectl ate get actor tool-a -a ate-demo-counter -o json
kubectl ate get actor tool-b -a ate-demo-counter -o json
```

Creation leaves Actors suspended. This lab addresses each Actor by its
Substrate-generated metadata UID in OpenFGA, so reusing an Actor's name after
deletion does not inherit its permissions.

Deploy OpenFGA v1.21.0 with Helm chart 0.3.15 and a single in-memory replica:

```sh
make setup
kubectl -n openfga-actors get pods
```

`make setup` creates only the lab namespace and its Helm release. The in-memory
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
[`model.json`](openfga/model.json), seeds `user:alice` -> `actor:<tool-a-uid>`
and creates the `openfga-actors-ids` ConfigMap. Run it once per OpenFGA store;
each invocation creates a new store. The adapter looks up the **current** UID
via Substrate `GetActor` on every request, not via this bootstrap snapshot.

## 2. Build and deploy the authorization adapter and gateway

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
Deployment. The adapter is in
[`adapter/server.py`](openfga/adapter/server.py); its wire-compatible subset of
Substrate `GetActor` is in
[`adapter/ateapi_subset.proto`](openfga/adapter/ateapi_subset.proto).
Confirm those proto field numbers against the Substrate checkout if using a
different API revision.

The gateway configuration in [`gateway.yaml`](openfga/gateway.yaml) forwards
`authorization` and `ate-target-actor` **to extAuthz**, then removes the
client's bearer token before the request reaches the Actor. The adapter calls
the Kubernetes TokenReview API with audience `openfga-actors`; only the
`openfga-actors/alice` and `openfga-actors/bob` service accounts are recognized.
It fails closed if OpenFGA or Substrate is unavailable. The gateway itself
also denies when the adapter is unavailable. Its HTTP ext-authz timeout is
10 seconds so three backend lookups can complete on a cold connection.

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

Expected: `200`, incremented counter, `tool-a` RUNNING. Now show that
permission is selective (suspend `tool-a` first if the shared WorkerPool has
only one worker):

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
the counter: its in-memory and durable counts survive Substrate's full-state
snapshot, regardless of which worker executes the Actor.

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
docker run --rm cr.agentgateway.dev/agentgateway:v1.5.0 --validate-only \
  -c "$(kubectl create --dry-run=client -f gateway.yaml -o jsonpath='{.data.config\.yaml}')"
kubectl apply --dry-run=client \
  -f namespace.yaml -f auth.yaml -f gateway.yaml
```

If the lab port-forward is still using `8082`, local model verification uses
`18082` so the two do not conflict. `make test` builds and runs adapter unit
tests; `integration_test.py` creates a disposable OpenFGA store and checks
grant, deny, cross-target deny and revocation. To remove **only the lab
resources you created** after stopping the port-forwards:

```sh
kubectl ate suspend actor tool-a -a ate-demo-counter  # only if running
kubectl ate suspend actor tool-b -a ate-demo-counter  # only if running
kubectl ate delete actor tool-a -a ate-demo-counter
kubectl ate delete actor tool-b -a ate-demo-counter
make clean
```

`make clean` deletes the lab gateway/adapter, the lab TokenReview binding,
the `openfga` Helm release, and the dedicated `openfga-actors` namespace. It
does not uninstall Substrate or the shared counter template/pool.

## Actor-to-Actor extension

OpenFGA's model permits `actor:<planner-uid>` as the subject of an
`allowed_caller` relationship. **Do not use an Actor-controlled header to
demonstrate that grant.** Substrate currently authenticates the outbound
Actor at its egress gateway using a certificate and live-Actor lookup, but
does not convey that verified caller identity to ingress. A real peer-call
extension needs a trusted identity bridge between those gateways before the
adapter can use `actor:<planner-uid>` as its subject. Substrate's existing
`MintJWT` endpoint does not yet verify that the requester owns the claimed
Actor. This lab's executable test uses Kubernetes-authenticated human/demo
principals; the Actor relationship is a next integration step, not a property
of this deployment.

## Scope

The lab gateway Service is ClusterIP and reached from your machine via
port-forward. **Direct access to `atenet-router` bypasses this lab gateway**;
restrict it with cluster network policy and external exposure controls before
using this pattern as an actual security boundary. Likewise, protect
OpenFGA's API and tuple-write credentials outside this isolated lab. This
configuration gates ordinary HTTP requests, not Substrate Control RPCs or
the separate CONNECT ingress listener. Check the pinned [agentgateway
configuration schema](https://agentgateway.dev/schema/config), [Substrate's
router trust model](https://github.com/agent-substrate/substrate/blob/main/cmd/atenet/internal/router/README.md), and [OpenFGA Check
API](https://openfga.dev/docs/getting-started/perform-check) if adapting it
to another deployment.

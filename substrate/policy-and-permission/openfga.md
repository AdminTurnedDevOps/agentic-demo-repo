# OpenFGA Permissions for Substrate Actors

## Goal

Demonstrate that permission belongs to a logical Actor, not to whichever warm
worker pod happens to run it. A caller may invoke one suspended Actor but not
another; a denied request must not wake its target. Granting or revoking a
relationship changes the decision without restarting the gateway or an Actor.

**Use agentgateway OSS.** Agent Substrate already supports it as its ingress
and egress dataplane with `--atenet-router=agentgateway`. Its ingress route uses
the `substrateIngress` policy to resolve `ate-target-actor` and resume the Actor.
The agentgateway configuration schema also supports an `extAuthz` route policy;
an external authorization service can consult OpenFGA before ingress resolves
the Actor. This is an integration to build, **not** an existing Substrate
OpenFGA feature or a built-in agentgateway OpenFGA policy.

This is a **lab design**, not a working installation recipe: the authorization
service, OpenFGA deployment, tuple management, and gateway policy wiring in
this document have not yet been implemented. Do not claim a permission boundary
until the negative and bypass tests below pass.

## Architecture

```text
Authenticated client
  -> atenet-router / agentgateway OSS
       -> extAuthz adapter -> OpenFGA Check(caller, can_invoke, target UID)
       -> deny: 403; no Substrate ResumeActor
       -> allow: existing substrateIngress policy -> ateapi ResumeActor
                    -> worker's atunnel -> target Actor

Actor caller (phase 2 only)
  -> Substrate egress gateway (authenticates Actor certificate + live UID)
  -> trusted identity bridge -> same ingress authorization path
```

The OpenFGA process and authorization adapter must run as **always-available
Kubernetes services**, not suspendable Actors: authorization cannot depend on
first waking the service that makes authorization decisions. Keep OpenFGA's
storage separate from the Actor snapshot store. Do not expose OpenFGA's
administrative or tuple-write endpoints to Actors.

### Why agentgateway, and which one?

The Substrate installer selects the existing agentgateway **dataplane sidecar**
for `atenet-router` (and for `atenet-egress`). It is configured by
`manifests/ate-install/components/agentgateway/configmap.yaml`, not by a
Gateway API `AgentgatewayPolicy` CRD. Its `substrateIngress` route is already
the point that wakes Actors. Extend that route with an `extAuthz` policy only
after verifying that authorization executes **before** `substrateIngress`;
if the order cannot be guaranteed, put an independently deployed agentgateway
OSS Gateway API `Gateway`/`HTTPRoute` with `AgentgatewayPolicy.spec.traffic.extAuth`
in front of `atenet-router` instead. The second gateway's adapter makes the
decision before the request ever reaches Substrate's router. These are two
different configuration surfaces; do not apply a Gateway API policy to the
Substrate sidecar and assume it took effect.

For either approach, restrict direct access to `atenet-router` (including its
CONNECT listeners). Otherwise clients can bypass the policy by talking to the
router directly. HTTPS/mTLS, Service exposure, and NetworkPolicies need an
explicit threat-model review before calling the result secure.

## Scenario and OpenFGA model

Start with the [counter demo](https://github.com/agent-substrate/substrate/blob/main/demos/counter/README.md):
create two counter Actors, `tool-a` and `tool-b`, in `ate-demo-counter`. Use a
human caller `user:alice` for phase 1. Later add a `planner` Actor as a caller
for phase 2. Use **Substrate Actor metadata UIDs**, not `atespace/name`, as
OpenFGA Actor IDs: a deleted Actor recreated with the same name must not inherit
the old Actor's grants. The target name from the routing header is only a lookup
key; the adapter resolves it against the Substrate API and checks the returned
UID. Do not trust a client-supplied UID.

Proposed OpenFGA DSL (schema 1.1):

```fga
model
  schema 1.1

type user

type actor
  relations
    define allowed_caller: [user, actor]
    define can_invoke: allowed_caller
```

For illustration, substitute actual UIDs read from
`kubectl ate get actor <name> -a ate-demo-counter -o yaml`:

```yaml
- user: user:alice
  relation: allowed_caller
  object: actor:<tool-a-uid>
- user: actor:<planner-uid>
  relation: allowed_caller
  object: actor:<tool-a-uid>
```

The second tuple is for phase 2 only. The corresponding Check requests are:

```text
Check(user="user:alice", relation="can_invoke", object="actor:<tool-a-uid>") -> true
Check(user="user:alice", relation="can_invoke", object="actor:<tool-b-uid>") -> false
Check(user="actor:<planner-uid>", relation="can_invoke", object="actor:<tool-a-uid>") -> true (phase 2)
```

Keep the first model small. A subsequent chapter could grant a whole Atespace
access through a parent relationship, but individual grants make the allow,
deny, and revocation behavior much easier to demonstrate. Store/model IDs and
tuple writes are operator-owned; pin the model ID used for checks and test the
model with OpenFGA's `fga model test` before loading real relationships.

## Lab implementation

1. Bring up Substrate with the agentgateway dataplane and deploy the counter
   fixture. For a disposable kind environment, follow the Substrate README's
   cluster creation instructions first, then from the Substrate checkout run:

   ```sh
   ./hack/install-ate-kind.sh --deploy-ate-system --atenet-router=agentgateway
   ./hack/install-ate-kind.sh --deploy-demo-counter
   kubectl ate create actor tool-a -a ate-demo-counter --template counter
   kubectl ate create actor tool-b -a ate-demo-counter --template counter
   kubectl ate get actor tool-a -a ate-demo-counter -o yaml
   kubectl ate get actor tool-b -a ate-demo-counter -o yaml
   ```

   The installer selects the dataplane at installation time. Do not run the
   kind cluster creation script on an existing cluster without checking it:
   that script recreates its selected cluster. On an existing installation,
   plan the dataplane change separately rather than applying these commands
   blindly.

2. Deploy a pinned OpenFGA version and persistent store as Kubernetes
   infrastructure. Create a store, publish the model above, record its model
   ID, and write only Alice-to-`tool-a` initially. Keep OpenFGA credentials in
   a Secret and provide the adapter with a scoped credential and the store and
   model IDs. Use the existing enterprise ReBAC example linked below for an
   *adapter pattern*, not for Enterprise CRDs or an unpinned Helm deployment.

3. Implement a small ext-authz adapter with a bounded request timeout. For
   phase 1, it must verify the caller's JWT (issuer, signature, audience,
   expiry), derive a stable subject from trusted claims, parse the untrusted
   `ate-target-actor` value as `<atespace>/<name>`, fetch the current Actor from
   `ateapi`, and query OpenFGA with its UID. Return allow only for an explicit
   positive Check. Invalid credentials are unauthenticated; missing permission
   is forbidden; OpenFGA or Substrate lookup failures fail closed. Never accept
   `x-actor-id`, `x-user`, or the routing header as proof of caller identity.
   Authenticate the adapter's connections to `ateapi` using Substrate's
   supported credentials. If implementing an HTTP instead of gRPC ext-authz
   adapter, use the matching agentgateway protocol configuration and validate
   its request/response contract against the version deployed.

4. Attach the adapter to the Substrate agentgateway ingress route ahead of
   resume. The existing route already has `substrateIngress` under `policies`
   in `manifests/ate-install/components/agentgateway/configmap.yaml` (ordinary
   and CONNECT-reentered routes). Protect **both** paths, or deliberately
   disable the CONNECT listener for this lab. Keep the stock
   `substrateIngress` and dynamic `atunnel` backend behavior intact. Verify
   policy execution order in the pinned agentgateway build by denying a call
   to a suspended Actor and observing that it remains suspended; a config
   schema accepting both policies is not proof of their execution order. If
   that fails, use the separate OSS gateway described above, with access to
   the underlying router restricted to that gateway.

5. Exercise the table below by making requests through the **protected**
   gateway endpoint. A request to the existing Substrate router uses
   `ate-target-actor: ate-demo-counter/tool-a` or `/tool-b`. The public gateway
   must preserve or derive that target only after its own authentication and
   policy check; it must not let callers change it after the decision. For a
   JWT-authenticated test client, supply `Authorization: Bearer <token>` over
   HTTPS. Capture the adapter decision and the Actor state before/after each
   request; do not rely on the HTTP status alone.

| Test | Expected result |
| --- | --- |
| Alice -> suspended `tool-a` | Allow, `ResumeActor`, counter increments. |
| Alice -> suspended `tool-b` | Deny, no resume, counter unchanged. |
| Missing/forged JWT or caller-ID header | Deny; header does not create an identity. |
| Remove Alice -> `tool-a` tuple | Next request denied without a rollout. |
| Restore tuple, suspend `tool-a`, call again | Allowed; counter state survives a full snapshot restore, possibly on another worker. |
| Delete and recreate `tool-a` under the same name | Denied until a tuple is granted for its new UID. |
| Stop OpenFGA | Fail closed; no target wakes. |
| Call the underlying router directly | Must be blocked by deployment access controls. |
| CONNECT ingress, if enabled | Same authorization and no-wake-on-deny behavior. |

Substrate does not automatically suspend an idle Actor. Use
`kubectl ate suspend actor tool-a -a ate-demo-counter` when setting up the wake tests, and check its
state before issuing the next request. If you use the same one-worker pool for
both counters, suspend the running Actor before attempting to wake the other.

## Phase 2: real Actor-to-Actor permission

The `planner` Actor can send HTTP to another Actor through the router, but
today Substrate's ingress treats request headers as untrusted, and its egress
gateway's authenticated Actor identity is **not propagated to ingress**. The
current `ActorIdentity.MintJWT` endpoint does not yet cross-check the caller
against the requested Actor. Do not demonstrate Actor-to-Actor security by
having the planner set `x-actor-id: planner`.

To implement the second phase, bridge the **verified** egress identity
(Actor UID from the certificate and a live-Actor lookup) into the ingress
authorization request through a trusted, non-spoofable channel. For example,
have a trusted gateway component issue a short-lived, audience-bound assertion
to ingress after verifying the egress certificate; ingress must validate the
assertion and never accept caller-supplied versions of it. Bind the target
reference to the check, prevent direct router bypass, and test replay,
spoofing, UID rotation, and a caller that is no longer RUNNING. This bridge is
**new work**: the existing agentgateway `substrateEgress` authentication policy
does not by itself implement peer authorization.

Once the identity bridge exists, write the `planner` -> `tool-a` tuple and
repeat the allow/deny/revoke tests with the planner making the call. The
OpenFGA model already supports an Actor as a subject; the missing piece is a
trusted proof that the request came from that Actor. This distinction is the
main teaching point of the second phase.

## Cleanup and limitations

Remove only this lab's Actors, grants, model/store, adapter and OpenFGA
resources, and any lab-specific gateway configuration. Delete or suspend
running Actors according to the installed `kubectl-ate` CLI's requirements;
do not tear down a shared Substrate installation. Never run a blanket cluster
cleanup command against an existing cluster. The prototype is HTTP request
authorization, not general authorization for the `ateapi` Control RPCs,
snapshot storage, or arbitrary non-HTTP Actor traffic. On long-lived streams,
the decision is made at admission; revocation does not retroactively close an
established connection.

## References

- [Substrate agentgateway ingress configuration](https://github.com/agent-substrate/substrate/blob/main/manifests/ate-install/components/agentgateway/configmap.yaml) and [egress demo/dataplane selection](https://github.com/agent-substrate/substrate/blob/main/demos/egress/README.md).
- [Substrate router trust boundaries](https://github.com/agent-substrate/substrate/blob/main/cmd/atenet/internal/router/README.md) and [authentication limitations](https://github.com/agent-substrate/substrate/blob/main/docs/authentication.md).
- [agentgateway standalone configuration schema](https://agentgateway.dev/schema/config) (`extAuthz` and `substrateIngress` route policies); [OSS Kubernetes policy example](https://github.com/agentgateway/agentgateway/tree/main/controller/test/e2e/testdata) (verify the installed CRD before applying an example).
- [OpenFGA modeling](https://openfga.dev/docs/modeling/getting-started), [Check API](https://openfga.dev/docs/getting-started/perform-check), and [model tests](https://openfga.dev/docs/modeling/testing).
- [Existing OpenFGA adapter example in this repo](../../agentgateway-enterprise/security/authz/rebac/mcp-rebac-demo/) uses Enterprise-specific policies; do not apply them to agentgateway OSS.

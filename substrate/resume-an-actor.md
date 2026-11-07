# Resume an actor

If you see Actors not running, its because (and by design, this is what helps with cost/resource optimization) by default, if Substrate Actors aren't being used, they go into a SUSPENDED state.

A request through the ingress router (for example via `kubectl ate proxy actor`) resumes a suspended actor on its own. To resume one by hand, use either `kubectl ate` or the gRPC API.

> **kagent installs:** if the actor was created by kagent (for example `ahr-kagent-openclaw-substrate-demo`), it may be running on kagent's bundled pre-1.0 Substrate, which still uses `ateapi.Control` and `actor_id`. Use [kagent-substrate/resume-actor.md](kagent-substrate/resume-actor.md) for that.

## Option 1: `kubectl ate`

Actors live in an **atespace**, so pass it with `-a`:

```
kubectl ate get actors -A
kubectl ate resume actor <actor> -a <atespace>
kubectl ate get actor <actor> -a <atespace>
```

## Option 2: grpcurl

1. Port-forward the svc so the substrate API is reachable
```
kubectl port-forward -n ate-system svc/api 18443:443
```

2. Mint a short-lived token. This one uses the shared `ate-client` ServiceAccount that `kubectl ate` uses, which `ate-setup` makes a bootstrap owner by default. The audience must be `api.ate-system.svc`.
```
TOKEN=$(kubectl create token ate-client -n ate-system --audience=api.ate-system.svc --duration=15m)
```

3. Find the actor (v1.0.0 has no `actor_id`; actors are addressed by atespace and name)
```
grpcurl -insecure -H "authorization: Bearer $TOKEN" \
-d '{"atespace":"<atespace>"}' \
localhost:18443 substrate.ateapi.v1.Control/ListActors
```

4. Resume it
```
grpcurl -insecure -H "authorization: Bearer $TOKEN" \
-d '{"actor":{"atespace":"<atespace>","name":"<actor>"}}' \
localhost:18443 substrate.ateapi.v1.Control/ResumeActor
```

The response's `resumed` field is `false` if the actor was already RUNNING.

Check state:
```
grpcurl -insecure -H "authorization: Bearer $TOKEN" \
-d '{"actor":{"atespace":"<atespace>","name":"<actor>"}}' \
localhost:18443 substrate.ateapi.v1.Control/GetActor
```

> **Agent Substrate v1.0.0 note (2026-11-06):** This guide targets kagent's pre-1.0 Substrate, the Substrate fork that kagent installs and pins, not an upstream Agent Substrate v1.0.0 install. That Substrate predates v1.0.0: it uses `ate.dev/v1alpha1`, `ateom-gvisor` worker images, and the `ateapi.Control` gRPC service with `actor_id`. kagent OSS `v1.0.0-rc3` now pins `kagent-dev/substrate v1.0.0` (`ate.dev/v1`, `substrate.ateapi.v1.Control`), and this guide has not been re-tested against it. On Substrate v1.0.0, actors are addressed by atespace and name instead of `actor_id`; see [resume-an-actor.md](../resume-an-actor.md) for the v1.0.0 request shapes. Don't run kagent's Substrate and an upstream `ate-setup` install ([setup-gke.md](../install-and-setup/setup-gke.md)) in the same cluster: both own `ate-system` and the `ate.dev` CRDs.

1. port-forward to ate-api (separate terminal, or backgrounded)
```
kubectl port-forward -n ate-system svc/api 18443:443
```

2. mint a short-lived token
```
TOKEN=$(kubectl create token kagent-controller -n kagent --audience=api.ate-system.svc --duration=15m)
```

3. Retrieve the Actor ID
```
  grpcurl -insecure -H "authorization: Bearer $TOKEN" \
    -d '{}' \
    localhost:18443 ateapi.Control/ListActors
```

4. Call the `call ResumeActor` endpoint
```
grpcurl -insecure -H "authorization: Bearer $TOKEN" \
  -d '{"actor_id":"<ACTOR_ID>"}' \
  localhost:18443 ateapi.Control/ResumeActor
```
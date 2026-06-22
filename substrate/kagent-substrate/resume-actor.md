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
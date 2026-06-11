If you see Actors not running, its because (and by design, this is what helps with cost/resource optimization) by default, if Substrate Actors aren't being used, they go into a SUSPENDED state.

1. Port-forward the svc so the substrate API is reachable
```
kubectl port-forward -n ate-system svc/api 18443:443
```

2. Resume traffic
```
grpcurl -insecure \
-d '{"actor_id":"ahr-kagent-openclaw-substrate-demo"}' \
localhost:18443 ateapi.Control/ResumeActor
```

Check state:
```
grpcurl -insecure -d '{"actor_id":"ahr-kagent-openclaw-substrate-demo"}' \
localhost:18443 ateapi.Control/GetActor
```
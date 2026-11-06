1. Port-forward your kagent controller that is deployed in the kagent namespace
```
kubectl port-forward svc/kagent-controller 8084:8083 -n kagent
```

2. Ask your agent a question and the `kagent-url` should be the port-forwarded kagent controller
```
kagent invoke -t "What is the status of my cluster?" --agent k8s-agent -n kagent --kagent-url "http://localhost:8084"
```
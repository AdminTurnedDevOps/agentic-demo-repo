```
kagent help
```

IF you're not running kagent locally
```
kubectl port-forward svc/kagent-controller 8083:8083 -n kagent
```

1. Invokve a task for an Agent instead of doing it through the UI
```
kagent invoke -t "What Helm charts are in my cluster?" --agent k8s-agent --namespace "kagent" --config=$HOME/.kube/config
```

2. You can also use the CLI to see what other Agents are available
```
kagent get agent
```
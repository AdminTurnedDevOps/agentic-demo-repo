```
kagent help
```

IF you're not running kagent locally
```
kubectl port-forward svc/kagent-controller 8083:8083 -n kagent
```

```
kagent invoke -t "What Helm charts are in my cluster?" --agent k8s-agent --namespace "kagent" --config=$HOME/.kube/config
```

```
kagent get agent
```

## Llama Config

1. Ensure that you configured kagent on your cluster. You can find the how-to here: https://github.com/AdminTurnedDevOps/agentic-demo-repo/blob/main/kagent-oss/setup.md

2. Create a Namespace for a Llama Model config
```
kubectl create ns ollama
```

3. Deploy Ollama on your k8s cluster
```
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama
  namespace: ollama
spec:
  selector:
    matchLabels:
      name: ollama
  template:
    metadata:
      labels:
        name: ollama
    spec:
      containers:
      - name: ollama
        image: ollama/ollama:latest
        ports:
        - name: http
          containerPort: 11434
          protocol: TCP
---
apiVersion: v1
kind: Service
metadata:
  name: ollama
  namespace: ollama
spec:
  type: ClusterIP
  selector:
    name: ollama
  ports:
  - port: 80
    name: http
    targetPort: http
    protocol: TCP
EOF
```

4. Ensure that everything was deployed as expected
```
kubectl get all -n ollama
```

5. Create a `ModelConfig` that will add the Llama Model to the list of Models in kagent
```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: llama3-model-config
  namespace: kagent
spec:
  model: llama3
  provider: Ollama
  ollama:
    host: http://ollama.ollama.svc.cluster.local
EOF
```

6. You should be able to see the Model connected
```
kubectl get modelconfig -n kagent
NAME                   PROVIDER    MODEL
default-model-config   Anthropic   claude-3-5-haiku-20241022
llama3-model-config    Ollama      llama3
```

7. If you go into kagent, you'll now see Llama as an option.

![](../../images/llama.png)
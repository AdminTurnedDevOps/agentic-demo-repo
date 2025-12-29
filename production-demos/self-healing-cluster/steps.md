# Steps

Below you will find a demo for self-healing clusters. An application is deployed and you have a few different scenarios to choose from to invoke autonomous actions.

## 1. Installation

Install kagent and agentgateway.

```
helm install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
    --namespace kagent \
    --create-namespace
```

```
export ANTHROPIC_API_KEY=your_api_key
```

```
helm upgrade --install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
    --namespace kagent \
    --set providers.default=anthropic \
    --set providers.anthropic.apiKey=$ANTHROPIC_API_KEY \
    --set ui.service.type=LoadBalancer
```

```
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml
```

```
helm upgrade -i --create-namespace \
  --namespace agentgateway-system \
  --version v2.2.0-main agentgateway-crds oci://ghcr.io/kgateway-dev/charts/agentgateway-crds
```

```
helm upgrade -i -n agentgateway-system agentgateway oci://ghcr.io/kgateway-dev/charts/agentgateway \
--version v2.2.0-main
```

```
kubectl get pods -n agentgateway-system
```

## 2. Run setup (installs + httpbin)

1. Configure the demo app and Grafana/Prometheus
```bash
cd production-demos/self-healing-cluster/self-healing-demo
./setup.sh
```

**If you want to access Grafana/Prometheus to look at observability data**

1. Access the Grafana UI
```
kubectl port-forward svc/prometheus-grafana -n monitoring 3000:80
```

2. Log in

```
Username: admin
Password: prom-operator
```

## 3. Apply the agent and CronJob

```bash
kubectl apply -f kagent/self-healing-agent.yaml
kubectl apply -f kagent/scheduled-task.yaml
```

## 4. Watch the Agent Logs

To confirm that the Agent is the piece that is kicking off the fix, you can watch the logs:
```
kubectl logs -f -n kagent -l app.kubernetes.io/name=self-healing-agent
```

## 5. Run the demo

```bash
./run-demo.sh
```

Pick a chaos scenario (crashloop, OOM, scale-down, or bad config), then watch the agent detect and fix it.

## 6. Cleanup

You'll want to run the cleanup script as soon as you're done as the `ConfigMap` will keep attempting to run every minute, which means you may hit LLM rate limits.

```bash
./cleanup.sh
```

# Manual Run

### 1. Check current state
kubectl get pods -n demo -l app=httpbin
kubectl get deployment httpbin -n demo
kubectl get svc -n kagent
kubectl get agents -n kagent

### 2. Scale up httpbin if Pods do not exist
kubectl scale deployment httpbin -n demo --replicas=3

### 3. Verify pods came up
kubectl get pods -n demo -l app=httpbin

### 4. Test the agent API endpoint (JSON-RPC format)
kubectl run curl-test --rm -i --restart=Never --image=curlimages/curl -n kagent -- \
  curl -s -X POST http://self-healing-agent:8080/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "message/send", "params": {"message": {"messageId": "test-1", "role": "user", "parts": [{"kind": "text", "text": "List pods in demo namespace"}]}}, "id": 1}'

### 5. Apply updated CronJob
kubectl apply -f kagent/scheduled-task.yaml

### 6. Inject chaos (scale to 0)
kubectl scale deployment httpbin -n demo --replicas=0

### 7. Trigger agent to fix it
kubectl run curl-test --rm -i --restart=Never --image=curlimages/curl -n kagent -- \
  curl -s -X POST http://self-healing-agent:8080/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "message/send", "params": {"message": {"messageId": "fix-test-1", "role": "user", "parts": [{"kind": "text", "text": "Check the demo namespace. The httpbin deployment should have 3 replicas. If it has 0 replicas, scale it back to 3."}]}}, "id": 1}'

### 8. Verify fix
kubectl get pods -n demo -l app=httpbin
kubectl get deployment httpbin -n demo

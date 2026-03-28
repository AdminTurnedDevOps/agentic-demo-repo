## Install kube-prometheus-stack

This is for the first cluster (akscluster1)

The `prometheus.prometheusSpec.enableRemoteWriteReceiver=true` allows the test results and metrics from k6 to be sent to prometheus and there, shown in Grafana.

```
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.ruleSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.retention=7d \
  --set prometheus.prometheusSpec.enableRemoteWriteReceiver=true
```

## Install kube-prometheus-stack on akscluster2

This is for the second cluster (akscluster2). This Prometheus instance scrapes the agentgateway metrics (LLM Gateway + MCP Gateway) running in `agentgateway-system`.

```
kubectl config use-context akscluster2

helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.ruleSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.retention=7d
```

Expose Prometheus as a LoadBalancer so Grafana on akscluster1 can reach it:

```
kubectl --context akscluster2 patch svc kube-prometheus-stack-prometheus -n monitoring \
  -p '{"spec":{"type":"LoadBalancer"}}'
```

Get the external IP:

```
kubectl --context akscluster2 get svc kube-prometheus-stack-prometheus -n monitoring \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
```

## Add akscluster2 Prometheus as a datasource in Grafana

1. Port-forward Grafana on akscluster1:
```
kubectl --context akscluster1 port-forward svc/kube-prometheus-stack-grafana -n monitoring 3000:80
```

2. Go to `http://localhost:3000` -> Connections -> Data sources -> Add data source -> Prometheus
3. Set URL to `http://<akscluster2-prometheus-external-ip>:9090`
4. Name it `Prometheus-WestUS`
5. Save & test
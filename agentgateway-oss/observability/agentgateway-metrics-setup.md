1. Add the Prometheus Helm Chart

```
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
```

2. Install Kube-Prometheus
```
helm install kube-prometheus -n monitoring prometheus-community/kube-prometheus-stack --create-namespace
```

3. Deploy a Pod Monitor
The `PodMonitor` selector matches `gateway.networking.k8s.io/gateway-class-name: agentgateway`, which will match any Gateway that uses the agentgateway GatewayClass
```
kubectl apply -f - <<EOF
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: agentgateway
  namespace: kgateway-system
  labels:
    app: agentgateway
    release: kube-prometheus
spec:
  selector:
    matchLabels:
      gateway.networking.k8s.io/gateway-class-name: agentgateway
  podMetricsEndpoints:
  - port: metrics
    path: /metrics
    interval: 30s
    scrapeTimeout: 10s
EOF
```

To look at the metrics in Prometheus
```
kubectl --namespace monitoring port-forward svc/kube-prometheus-kube-prome-prometheus 9090
```

To build a dashboard with the metrics
```
kubectl --namespace monitoring port-forward svc/kube-prometheus-grafana 3000:80
```

To log into the Grafana UI:

1. Username: admin
2. Password: prom-operator
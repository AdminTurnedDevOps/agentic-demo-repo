## Install kube-prometheus-stack

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

### Optional: Persistent Storage

If your cluster has the EBS CSI driver installed, add persistent storage to retain metrics across pod restarts:

```
  --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.storageClassName=gp2 \
  --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage=50Gi
```

Without persistent storage, Prometheus uses `emptyDir` and metrics are lost on pod restart. This is acceptable for benchmark testing.

Grafana credentials:
- Username: admin
- Password: LNb7w99xlqgJ4LRY89NOjPotWAS9J9p8ufbpnFUP
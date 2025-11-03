## Installation

### Step 1: Deploy the gateways

Follow the instructions in [setup-agentgateway.md](setup-agentgateway.md) to deploy the three agentgateway instances.

### Step 2: Install kube-prometheus-stack

Follow the instructions in [kube-prometheus-install.md](kube-prometheus-install.md) to deploy kube-prometheus.

### Step 3: Deploy monitoring resources

Apply ServiceMonitors, PrometheusRules, and AlertmanagerConfig

```
kubectl apply -f monitoring.yaml
```

### Step 4: Import Grafana dashboard

1. Access Grafana
```
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80
```

2. Open http://localhost:3000 in your browser (username: `admin`)

3. Navigate to: **Dashboards → Import**

4. Upload `grafana-dashboard.json` or paste its contents

5. Select "Prometheus" as the data source and click **Import**

### Test the metrics

1. Send some test requests to your gateways (see [setup.md](setup.md) for curl examples)

2. Check Token usage
```
curl -s 'http://localhost:9090/api/v1/query?query=agentgateway:input_tokens:total' | jq '.data.result[0].value'
```

3. Check cost
```
curl -s 'http://localhost:9090/api/v1/query?query=agentgateway:cost_usd:total_daily' | jq '.data.result[0].value'
```

Example output showing 38.89 tokens used and roughly $0.34 cents USD in cost
```
[
  1762004864.188,
  "38.88888888888889"
]
[
  1762004864.268,
  "0.0033364842833333336"
]
```

3. Open the Grafana Dashboard and you should see an output similar to the below
![](../../../images/cost-for-gateways.png)
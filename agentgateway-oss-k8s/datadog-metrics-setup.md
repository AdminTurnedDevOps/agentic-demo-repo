## Prereqs

You'll want Prometheus deployed for this. Please follow this guide: https://github.com/AdminTurnedDevOps/agentic-demo-repo/blob/main/agentgateway-oss-k8s/cost/cost-across-dataplanes/kube-prometheus-install.md

You can skip Alertmanager

## Setting Up Datadog In Kubernetes

1. Sign up for Datadog here: https://www.datadoghq.com/

2. Set environment variables

```
CLUSTER_NAME=
API_KEY=
 (get the API key from Organization Settings in Datadog)
```


```
helm repo add datadog https://helm.datadoghq.com
```

```
helm repo update
```

```
helm install datadog -n datadog \
--set datadog.site='datadoghq.com' \
--set datadog.clusterName=$CLUSTER_NAME \
--set datadog.clusterAgent.replicas='2' \
--set datadog.clusterAgent.createPodDisruptionBudget='true' \
--set datadog.kubeStateMetricsEnabled=true \
--set datadog.kubeStateMetricsCore.enabled=true \
--set datadog.logs.enabled=true \
--set datadog.logs.containerCollectAll=true \
--set datadog.apiKey=$API_KEY \
--set datadog.processAgent.enabled=true \
--set targetSystem='linux' \
datadog/datadog --create-namespace
```

## Collect Agentgateway Metrics

Since AgentGateway already exposes Prometheus-format metrics, enable Datadog's Prometheus scrape feature. This reuses the existing `prometheus.io/*` annotations on your pods - no need to configure scraping twice.

### Upgrade Datadog to Enable Prometheus Scraping

```bash
helm upgrade datadog -n datadog datadog/datadog \
--reuse-values \
--set datadog.prometheusScrape.enabled=true \
--set datadog.prometheusScrape.serviceEndpoints=true
```

### Verify AgentGateway Pod Annotations

Your AgentGateway pods need these annotations (they likely already have them if Prometheus is working):

```yaml
annotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "9092"
  prometheus.io/path: "/metrics"
```

### Verify Metrics in Datadog

Once the upgrade completes, go to **Metrics > Explorer** in Datadog and search for:

- `agentgateway_gen_ai_client_token_usage` - token usage
- `agentgateway_gen_ai_client_request_duration` - request latency
- `agentgateway_gen_ai_server_request` - server-side metrics


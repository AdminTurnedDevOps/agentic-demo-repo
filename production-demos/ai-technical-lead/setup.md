# AI Technical Lead Agent

Build an AI-powered Technical Lead agent using **kagent** (CNCF project) that monitors Prometheus/Grafana, assists with troubleshooting, and creates GitHub issues - all accessible via Slack. This project contains:
1. MCP Servers
2. Agent Skills
3. kagent
4. Slack (for kicking off agents)
5. Python bot for Slack
6. Monitoring and observability (prometheus and grafana)
7. Anthropic for the LLM provider


## Prerequisites

Before running this demo, ensure you have the following installed and configured.

1. Infrastructure
- **Kubernetes cluster** - Any cluster (kind, minikube, EKS, GKE, AKS, etc.)
- **kagent** - Install via `brew install kagent` or [installation guide](https://kagent.dev/docs/kagent/introduction/installation)
- **Prometheus + Grafana**
```
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.ruleSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.retention=30d \
  --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage=50Gi
```

```
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
```

```
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3001:80
```

Username: admin
Password: `kubectl get secret kube-prometheus-stack-grafana -n monitoring -o jsonpath='{.data.admin-password}' | base64 --decode`

2. API Keys & Tokens
- **Anthropic API Key** - Get from [console.anthropic.com](https://console.anthropic.com) and create the k8s secret
```
kubectl create secret generic anthropic-credentials -n kagent \
--from-literal=api-key=$ANTHROPIC_API_KEY
```
- **GitHub Personal Access Token** - Create at [github.com/settings/tokens](https://github.com/settings/tokens) with `repo` scope
- **Grafana Service Account Token** - Create in Grafana UI: Administration > Service Accounts > Add token (Viewer role minimum)
- **Kubernetes Secrets** - Edit the `secrets.yaml` file under **manifests** with the appropriate secrets
- **Slack App** - Create at [api.slack.com/apps](https://api.slack.com/apps) with:
  - Bot Token Scopes: `chat:write`, `commands`, `app_mentions:read`
  - App-Level Token Scope: `connections:write`
  - Socket Mode: Enabled
  - Slash Command: `/techlead`

---

## Quick Start

# 2. Apply all manifests
1. Create the Namespace
```
kubectl apply -f manifests/namespace.yaml
```

2. Create the secrets. Ensure you generate them and input them into the `secrets.yaml`. DO NOT save and commit this file with your secrets to a GitHub repo
```
kubectl apply -f manifests/secrets.yaml
```

3. Create the Model Config for your Agent to have an LLM provider to reach out to. In this case, its Anthropic.
```
kubectl apply -f manifests/model-config.yaml
```

4. Within the **manifests/mcp-servers** directory, you'll see three MCP Servers:
- Grafana
- GitHub
- Slack

For the GitHub MCP server, the secret is injected (the PAT token you created in the `secrets.yaml`), so nothing you need to do there.

For the Slack MCP server, the secret is injected that you created in `secrets.yaml`, so nothing you need to do there.

For the Grafana MCP server, you need to update it with the URL to your Grafana server (created in the **prerequisites** section). 

Once done, you can create the MCP Servers
```
kubectl apply -f manifests/mcp-servers/
```

5. Apply the Agent
```
kubectl apply -f manifests/agent.yaml
```

# 3. Build and deploy Slack bot
```
cd slack-bot
docker build -t ai-tech-lead-slack-bot:latest .
kubectl apply -f deployment.yaml
```

# 4. Deploy demo apps and alerts
```
kubectl apply -f demo/sample-app/
kubectl apply -f demo/prometheus-rules.yaml
```

# 5. Test via kagent CLI
```
kagent invoke -t "What alerts are firing?" --agent ai-tech-lead -n kagent
```

# 6. Test via Slack
```
# /techlead What's the cluster status?
```

See [demo/demo-walkthrough.md](demo/demo-walkthrough.md) for the full demo script.


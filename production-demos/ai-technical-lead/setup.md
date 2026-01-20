# AI Technical Lead Agent

## Prerequisites

Before running this demo, ensure you have the following installed and configured:

### Infrastructure
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

### API Keys & Tokens
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

5. 
kubectl apply -f manifests/agent.yaml

# 3. Build and deploy Slack bot
cd slack-bot
docker build -t ai-tech-lead-slack-bot:latest .
kubectl apply -f deployment.yaml

# 4. Deploy demo apps and alerts
kubectl apply -f demo/sample-app/
kubectl apply -f demo/prometheus-rules.yaml

# 5. Test via kagent CLI
kagent invoke -t "What alerts are firing?" --agent ai-tech-lead -n kagent

# 6. Test via Slack
# /techlead What's the cluster status?
```

See [demo/demo-walkthrough.md](demo/demo-walkthrough.md) for the full demo script.

---

## Overview
Build an AI-powered Technical Lead agent using **kagent** (CNCF project) that monitors Prometheus/Grafana, assists with troubleshooting, and creates GitHub issues - all accessible via Slack.

## Architecture

```
                    +-------------------+
                    |    Slack Bot      |
                    |  (Python/Bolt)    |
                    +--------+----------+
                             |
                             | A2A Protocol
                             v
+----------------+   +------------------+   +------------------+
| Grafana MCP    |<--|    kagent        |-->| GitHub MCP       |
| Server         |   | AI Tech Lead     |   | Server           |
| (MCPServer)    |   |    Agent         |   | (MCPServer)      |
| - Prometheus   |   +------------------+   | - issue_write    |
| - Dashboards   |           |              | - add_comment    |
| - Loki         |           v              +------------------+
+----------------+   +------------------+
                     | Kubernetes MCP   |
                     | (built-in tools) |
                     +------------------+
```

### External MCP Servers (deployed as MCPServer CRDs)

1. **Grafana MCP Server** (`grafana/mcp-grafana`): Prometheus queries, dashboard management, Loki logs
2. **GitHub MCP Server** (`github/github-mcp-server`): Issue creation, PR management

## Components to Build

### 1. Kagent Agent Definition (`agent.yaml`)
- System prompt defining the AI Technical Lead persona
- Tool bindings for Prometheus, Grafana, Kubernetes, GitHub, Slack
- A2A skill exposure for Slack integration

### 2. Slack Bot (`slack-bot/`)
- Python application using Slack Bolt SDK
- Connects to kagent via A2A protocol
- Handles slash commands and mentions
- Posts agent responses back to channels

### 3. MCP Server Deployments (MCPServer CRDs)
- **Grafana MCP Server** (`grafana/mcp-grafana`): Deployed as MCPServer CRD
  - `query_prometheus`: Execute PromQL queries
  - `list_prometheus_metric_names`: Discover available metrics
  - `list_prometheus_metric_metadata`: Get metric documentation
  - `list_prometheus_label_names/values`: Label exploration
  - Dashboard tools for Grafana interaction
- **GitHub MCP Server** (`ghcr.io/github/github-mcp-server`): Deployed as MCPServer CRD
  - `issue_write`: Create/update issues
  - `add_issue_comment`: Add comments to issues
  - `list_issues`, `search_issues`: Query existing issues
- **Slack MCP Server**: For sending proactive notifications to channels

### 4. Kubernetes Manifests
- Agent CRD deployment
- MCP ToolServer configurations
- Secrets for API tokens (GitHub, Slack)
- Model configuration (Anthropic/Claude)

## File Structure

```
production-demos/ai-technical-lead/
├── setup.md                        # Complete setup instructions
├── infrastructure/
│   ├── kind-cluster.yaml           # Kind cluster config with extra ports
│   └── kube-prometheus-values.yaml # Helm values for kube-prometheus-stack
├── manifests/
│   ├── namespace.yaml              # kagent namespace
│   ├── secrets.yaml.template       # Template for API keys (Grafana, GitHub, Slack, Anthropic)
│   ├── model-config.yaml           # Anthropic Claude config
│   ├── agent.yaml                  # AI Tech Lead agent definition
│   └── mcp-servers/
│       ├── grafana-mcp.yaml        # MCPServer CRD for grafana/mcp-grafana
│       ├── github-mcp.yaml         # MCPServer CRD for github/github-mcp-server
│       └── slack-mcp.yaml          # MCPServer CRD for Slack notifications
├── slack-bot/
│   ├── main.py                     # Bolt app entry point
│   ├── requirements.txt            # Python dependencies
│   ├── .env.example                # Environment template
│   ├── Dockerfile                  # Container build
│   └── deployment.yaml             # K8s deployment for slack-bot
└── demo/
    ├── sample-app/                 # Demo app to generate metrics
    │   ├── deployment.yaml
    │   └── service.yaml
    ├── prometheus-rules.yaml       # PrometheusRule for demo alerts
    └── demo-walkthrough.md         # Step-by-step demo script
```

## MCPServer CRD Examples

### Grafana MCP Server (includes Prometheus tools)
```yaml
apiVersion: kagent.dev/v1alpha1
kind: MCPServer
metadata:
  name: grafana-mcp-server
  namespace: kagent
spec:
  deployment:
    image: grafana/mcp-grafana:latest
    port: 8000
    args: ["-t", "sse"]
    env:
      - name: GRAFANA_URL
        value: "http://prometheus-grafana.monitoring:80"
      - name: GRAFANA_SERVICE_ACCOUNT_TOKEN
        valueFrom:
          secretKeyRef:
            name: grafana-credentials
            key: token
  transportType: sse
```

### GitHub MCP Server
```yaml
apiVersion: kagent.dev/v1alpha1
kind: MCPServer
metadata:
  name: github-mcp-server
  namespace: kagent
spec:
  deployment:
    image: ghcr.io/github/github-mcp-server:latest
    port: 8000
    env:
      - name: GITHUB_PERSONAL_ACCESS_TOKEN
        valueFrom:
          secretKeyRef:
            name: github-credentials
            key: token
  transportType: sse
```

### Agent Referencing MCPServer Tools
```yaml
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: ai-tech-lead
  namespace: kagent
spec:
  type: Declarative
  declarative:
    modelConfig: anthropic-claude
    tools:
      - type: McpServer
        mcpServer:
          name: grafana-mcp-server
          kind: MCPServer
          toolNames:
            - query_prometheus
            - list_prometheus_metric_names
            - list_prometheus_label_values
      - type: McpServer
        mcpServer:
          name: github-mcp-server
          kind: MCPServer
          toolNames:
            - issue_write
            - add_issue_comment
            - list_issues
```

## Agent System Prompt (Key Elements)

The AI Technical Lead will:
1. **Monitor & Triage**: Query Prometheus alerts, analyze severity, prioritize
2. **Investigate**: Pull metrics, logs, and Kubernetes state for context
3. **Root-Cause Analysis**: Correlate signals to identify likely causes
4. **Document**: Create detailed GitHub issues with:
   - Summary of the problem
   - Affected services/components
   - Metrics/evidence gathered
   - Suggested remediation steps
   - Priority/labels based on severity
5. **Communicate**: Post updates to Slack with findings and ticket links

## Implementation Steps

### Phase 1: Infrastructure Setup
1. Create Kind cluster configuration with port mappings
2. Write Helm values for kube-prometheus-stack
3. Create setup script to bootstrap everything

### Phase 2: Kagent + Monitoring Integration
4. Install kagent with Anthropic model config
5. Configure Prometheus/Grafana MCP ToolServers
6. Deploy AI Tech Lead agent with system prompt
7. Test basic monitoring queries via kagent CLI

### Phase 3: GitHub Integration
8. Deploy GitHub MCP server as ToolServer
9. Configure with repo access token
10. Add issue creation tools to agent
11. Test issue creation flow

### Phase 4: Slack Bot (Kubernetes Deployment)
12. Build Python Bolt bot with A2A client
13. Create Dockerfile for containerization
14. Write Kubernetes deployment manifests
15. Deploy Slack MCP server for outbound messages
16. Test bidirectional Slack integration

### Phase 5: Demo Scenario
17. Create sample application that generates metrics
18. Write PrometheusRules that fire demo alerts
19. Create end-to-end walkthrough script
20. Test complete flow: Alert → Detection → Analysis → Ticket → Slack

## Prerequisites for Running

- Docker Desktop (for Kind)
- kubectl CLI
- Helm CLI
- kagent CLI (`brew install kagent` or curl install)
- GitHub Personal Access Token (repo scope)
- Slack App credentials:
  - Bot Token (xoxb-...)
  - App Token (xapp-...)
  - Team ID and Channel ID
- Anthropic API key (ANTHROPIC_API_KEY)

## Verification Steps

1. **Agent responds to queries**: `kagent invoke -t "What alerts are firing?" --agent ai-tech-lead`
2. **Slack command works**: `/techlead what's the status of the cluster?`
3. **GitHub issue created**: Agent creates issue when asked to document a problem
4. **End-to-end demo**: Alert fires → Agent detects → Creates ticket → Posts to Slack

## Key Technical Decisions

1. **Why kagent?**: Kubernetes-native, MCP support, A2A protocol for Slack, CNCF project
2. **Why external MCPServer CRDs?**:
   - `grafana/mcp-grafana` provides comprehensive Prometheus + Grafana tools in one server
   - `github/github-mcp-server` is the official GitHub MCP implementation with security mitigations
   - Deployed as Kubernetes-native MCPServer CRDs for full lifecycle management
3. **Why A2A for Slack?**: Official kagent pattern, allows skill-based invocation from Slack
4. **Claude as LLM**: User requirement, kagent supports Anthropic provider via ModelConfig

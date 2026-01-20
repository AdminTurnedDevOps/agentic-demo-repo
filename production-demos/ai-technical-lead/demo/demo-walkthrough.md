# AI Technical Lead Demo Walkthrough

This guide walks through demonstrating the AI Technical Lead agent - an AI-powered system that monitors your infrastructure, assists with troubleshooting, and automatically creates GitHub issues with real context.

## Prerequisites

Before running the demo, ensure you have:

- [ ] Kubernetes cluster running
- [ ] kagent installed and running
- [ ] Prometheus/Grafana stack deployed
- [ ] All secrets configured (see `manifests/secrets.yaml.template`)
- [ ] Slack App created and configured
- [ ] GitHub Personal Access Token with repo scope

## Setup Steps

### 1. Apply the Manifests

```bash
# Create namespace (if not exists)
kubectl apply -f manifests/namespace.yaml

# Apply secrets (copy from template and fill in values first!)
kubectl apply -f manifests/secrets.yaml

# Apply model configuration
kubectl apply -f manifests/model-config.yaml

# Deploy MCP servers
kubectl apply -f manifests/mcp-servers/

# Deploy the AI Tech Lead agent
kubectl apply -f manifests/agent.yaml

# Deploy demo applications
kubectl apply -f demo/sample-app/

# Apply PrometheusRules for demo alerts
kubectl apply -f demo/prometheus-rules.yaml
```

### 2. Build and Deploy Slack Bot

```bash
cd slack-bot

# Build the Docker image
docker build -t ai-tech-lead-slack-bot:latest .

# If using a registry, push it
docker tag ai-tech-lead-slack-bot:latest your-registry/ai-tech-lead-slack-bot:latest
docker push your-registry/ai-tech-lead-slack-bot:latest

# Update deployment.yaml with your image
# Then deploy
kubectl apply -f deployment.yaml
```

### 3. Verify Everything is Running

```bash
# Check kagent components
kubectl get agents -n kagent
kubectl get mcpservers -n kagent

# Check Slack bot
kubectl get pods -n kagent -l app.kubernetes.io/component=slack-bot

# Check demo apps
kubectl get pods -n demo-apps

# Check PrometheusRules
kubectl get prometheusrules -n monitoring
```

## Demo Script

### Part 1: Introduction (2 minutes)

**Talk Track:**
> "Platform and engineering teams are drowning in signals - logs, alerts, incidents, and half-formed Slack threads. What if your technical lead could work 24/7, spot issues early, and automatically create actionable tickets?
>
> Today I'll show you an AI Technical Lead built with kagent - a CNCF project for running AI agents in Kubernetes. This agent monitors Prometheus, assists with troubleshooting, and creates GitHub issues automatically."

### Part 2: Show the Architecture (2 minutes)

**Show the architecture diagram from setup.md**

**Talk Track:**
> "The architecture is straightforward:
> - A Slack bot provides the user interface via slash commands
> - It connects to kagent via the A2A protocol
> - The agent has access to Grafana MCP server for Prometheus queries
> - GitHub MCP server for creating issues
> - And built-in Kubernetes tools for cluster inspection"

### Part 3: Alert Monitoring Demo (5 minutes)

**In Slack, type:**
```
/techlead What alerts are currently firing in the cluster?
```

**Expected Response:** The agent will query Prometheus, list active alerts, and provide severity analysis.

**Talk Track:**
> "Let's ask the AI Tech Lead what's happening in our cluster. Notice how it:
> - Queries Prometheus for active alerts
> - Categorizes them by severity
> - Provides context about each alert"

### Part 4: Investigation Demo (5 minutes)

**In Slack, type:**
```
/techlead Investigate the payment-service - are there any issues?
```

**Expected Response:** The agent will:
1. Query relevant metrics for payment-service
2. Check for error rates, latency, resource usage
3. Examine pod status
4. Provide a summary of findings

**Talk Track:**
> "Now let's have the agent investigate a specific service. Watch how it:
> - Pulls metrics from Prometheus
> - Checks Kubernetes pod status
> - Correlates multiple signals
> - Provides actionable insights"

### Part 5: Root Cause Analysis (5 minutes)

**In Slack, type:**
```
/techlead We're seeing increased latency across multiple services. Can you perform a root cause analysis?
```

**Expected Response:** The agent will:
1. Query latency metrics across services
2. Look for correlated issues (resource pressure, dependencies)
3. Provide a hypothesis for the root cause
4. Suggest remediation steps

**Talk Track:**
> "One of the most powerful capabilities is root cause analysis. The agent doesn't just report symptoms - it correlates signals to identify underlying causes."

### Part 6: Automatic Ticket Creation (5 minutes)

**In Slack, type:**
```
/techlead Create a GitHub issue for the high latency problem you just identified
```

**Expected Response:** The agent will:
1. Create a GitHub issue with proper title, labels, and description
2. Include the investigation findings
3. Add recommended remediation steps
4. Return the issue URL

**Talk Track:**
> "Now here's where it gets really powerful. I can ask the agent to document its findings as a GitHub issue. Notice how the ticket includes:
> - Clear title and appropriate labels
> - Summary of the problem
> - Evidence from metrics
> - Recommended actions
> - This is a real ticket in our repo - not mock data."

**Show the created GitHub issue in the browser.**

### Part 7: Continuous Monitoring Concept (2 minutes)

**Talk Track:**
> "What we've shown today is the interactive mode. In production, you could:
> - Set up scheduled checks that run automatically
> - Have the agent monitor for alert thresholds and proactively investigate
> - Auto-create tickets when issues meet certain criteria
> - Post summaries to Slack channels on a schedule
>
> The agent becomes a force multiplier - your technical lead that never sleeps."

## Example Queries to Demo

Here are additional queries you can use during the demo:

### Cluster Health
```
/techlead Give me an overall health check of the Kubernetes cluster
```

### Specific Metric Queries
```
/techlead What's the current request rate for the api-gateway service?
```

### Memory Investigation
```
/techlead Are any pods approaching their memory limits?
```

### Historical Analysis
```
/techlead Compare the error rate of payment-service over the last hour vs yesterday
```

### Dashboard Search
```
/techlead What Grafana dashboards are available for monitoring?
```

## Troubleshooting

### Agent Not Responding

1. Check kagent controller logs:
   ```bash
   kubectl logs -n kagent deploy/kagent-controller
   ```

2. Verify MCP servers are running:
   ```bash
   kubectl get pods -n kagent
   ```

3. Check agent status:
   ```bash
   kagent get agent ai-tech-lead -n kagent
   ```

### Slack Bot Issues

1. Check bot logs:
   ```bash
   kubectl logs -n kagent -l app.kubernetes.io/component=slack-bot
   ```

2. Verify secrets are correct:
   ```bash
   kubectl get secret slack-credentials -n kagent -o yaml
   ```

### MCP Server Connection Issues

1. Check Grafana MCP server:
   ```bash
   kubectl logs -n kagent deploy/grafana-mcp-server
   ```

2. Verify Grafana URL is reachable from within the cluster

### No Alerts Showing

1. Verify PrometheusRules are applied:
   ```bash
   kubectl get prometheusrules -n monitoring
   ```

2. Check Prometheus is scraping the rules:
   - Open Prometheus UI
   - Go to Alerts page
   - Look for "ai-tech-lead-demo-alerts"

## Post-Demo Cleanup

```bash
# Remove demo apps
kubectl delete -f demo/sample-app/

# Remove PrometheusRules
kubectl delete -f demo/prometheus-rules.yaml

# Remove agent and MCP servers (optional)
kubectl delete -f manifests/agent.yaml
kubectl delete -f manifests/mcp-servers/

# Remove Slack bot (optional)
kubectl delete -f slack-bot/deployment.yaml
```

## Key Takeaways for Audience

1. **Real Data, Not Mock**: Everything you saw used real Prometheus metrics and created real GitHub issues

2. **Kubernetes-Native**: Built on kagent (CNCF project), runs in your cluster, uses K8s CRDs

3. **Extensible via MCP**: Add new tools by deploying MCP servers - no code changes to the agent

4. **Slack Integration**: Natural language interface where your team already works

5. **AI That Takes Action**: Not just a chatbot - can actually create tickets, post updates, and more

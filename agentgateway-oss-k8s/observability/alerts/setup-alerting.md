# AlertManager Setup for Agent Gateway

This guide explains how to configure AlertManager with Prometheus to monitor your Agent Gateway deployment.

## Prerequisites

- Kube-Prometheus-Stack installed (from [agentgateway-metrics-setup.md](agentgateway-metrics-setup.md))
- Agent Gateway running with PodMonitor configured
- kubectl access to your cluster

## Overview

The alerting setup includes:
- **AlertManager Config**: Defines routing, receivers, and notification channels
- **Prometheus Alert Rules**: Defines when alerts should fire based on metrics
- Alert rules for LLM, MCP, connections, xDS, availability, and cost monitoring

## Step 1: Configure AlertManager

Edit the `alertmanager-config.yaml` file to customize:

1. **Email Settings** (lines 3-8):
   ```yaml
   smtp_smarthost: 'smtp.gmail.com:587'
   smtp_from: 'alerts@yourcompany.com'
   smtp_auth_username: 'alerts@yourcompany.com'
   smtp_auth_password: 'your-app-password'
   ```

2. **Slack Webhook** (line 11):
   ```yaml
   slack_api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL'
   ```

3. **PagerDuty** (line 76):
   ```yaml
   service_key: 'your-pagerduty-service-key'
   ```

4. **Team Email Addresses**:
   - Default team: line 60
   - On-call: line 86
   - LLM team: line 102
   - MCP team: line 117

5. **Slack Channels**:
   - Critical alerts: line 78
   - Warning alerts: line 91
   - LLM alerts: line 96
   - MCP alerts: line 111

## Step 2: Create AlertManager Secret

```bash
kubectl create secret generic alertmanager-kube-prometheus-kube-prome-alertmanager \
  --from-file=alertmanager.yaml=alertmanager-config.yaml \
  -n monitoring \
  --dry-run=client -o yaml | kubectl apply -f -
```

## Step 3: Deploy Prometheus Alert Rules

```bash
kubectl apply -f prometheus-alert-rules.yaml
```

Verify the rules are loaded:
```bash
kubectl get prometheusrules -n kgateway-system
```

## Step 4: Verify AlertManager Configuration

Port-forward to AlertManager:
```bash
kubectl port-forward -n monitoring svc/kube-prometheus-kube-prome-alertmanager 9093:9093
```

Visit: http://localhost:9093

Check:
1. Status → Config to see your routing configuration
2. Alerts to see active/firing alerts
3. Silences to manage alert suppressions

## Alert Categories

### 1. LLM Alerts
- **HighLLMTokenUsage**: Token usage rate > 100k tokens/sec for 5min
- **ExcessiveLLMTokenUsage**: Critical cost alert > 500k tokens/sec for 10min
- **HighLLMRequestRate**: Request rate > 100 req/sec
- **LowLLMRequestRate**: Unusual drop in request rate
- **NoLLMRequests**: Zero requests for 30min
- **HighLLMRequestDuration**: Avg duration > 10s
- **VeryHighLLMRequestDuration**: Critical latency > 30s
- **TokenUsageAnomaly**: Statistical anomaly detection (3 sigma)

### 2. MCP Alerts
- **HighMCPRequestRate**: Tool call rate > 1000 req/sec
- **MCPRequestSpike**: 100% increase over 30min average
- **NoMCPRequests**: Zero tool calls for 30min

### 3. Connection Alerts
- **HighDownstreamConnectionRate**: Connection rate > 1000/sec
- **DownstreamConnectionSpike**: 200% increase (possible attack)

### 4. xDS Alerts
- **HighXDSMessageRate**: xDS message rate > 100/sec
- **HighXDSBandwidth**: xDS bandwidth > 10MB/sec
- **XDSMessageAnomaly**: 5x higher than normal

### 5. Availability Alerts
- **AgentGatewayDown**: Gateway instance unreachable for 1min
- **MultipleAgentGatewaysDown**: Multiple instances down
- **MetricsScrapeFailure**: Prometheus can't scrape metrics

### 6. Cost Control Alerts
- **DailyTokenBudgetWarning**: Daily usage > 50M tokens
- **DailyTokenBudgetExceeded**: Daily usage > 100M tokens
- **HourlyTokenCostSpike**: 2x hourly average

## Customizing Alert Thresholds

Edit `prometheus-alert-rules.yaml` to adjust thresholds:

```yaml
# Example: Change high token usage threshold
- alert: HighLLMTokenUsage
  expr: rate(agentgateway_gen_ai_client_token_usage_sum[5m]) > 200000  # Changed from 100000
  for: 10m  # Changed from 5m
```

Apply changes:
```bash
kubectl apply -f prometheus-alert-rules.yaml
```

## Testing Alerts

### Test Email Notifications
```bash
kubectl exec -n monitoring alertmanager-kube-prometheus-kube-prome-alertmanager-0 -- \
  amtool alert add test_alert \
    alertname="TestAlert" \
    severity="warning" \
    --alertmanager.url=http://localhost:9093
```

### Test Slack Notifications
Use AlertManager UI at http://localhost:9093 to manually fire a test alert.

### Generate Load to Trigger Real Alerts
```bash
# Generate LLM requests to trigger token usage alerts
for i in {1..100}; do
  curl "$INGRESS_GW_ADDRESS:8080/anthropic" \
    -H "content-type:application/json" \
    -H "x-api-key:$ANTHROPIC_API_KEY" \
    -H "anthropic-version: 2023-06-01" \
    -d '{
      "model": "claude-3-5-sonnet-20241022",
      "messages": [{"role": "user", "content": "Hello"}],
      "max_tokens": 100
    }' &
done
```

## Silencing Alerts

### Via AlertManager UI
1. Navigate to http://localhost:9093
2. Click on an active alert
3. Click "Silence" button
4. Set duration and comment

### Via CLI
```bash
kubectl exec -n monitoring alertmanager-kube-prometheus-kube-prome-alertmanager-0 -- \
  amtool silence add \
    alertname=HighLLMTokenUsage \
    --duration=2h \
    --comment="Planned load test" \
    --alertmanager.url=http://localhost:9093
```

## Inhibition Rules

The configuration includes inhibition rules to prevent alert flooding:

1. **Critical suppresses Warning**: If a critical alert fires for a service, warnings are suppressed
2. **Gateway Down suppresses all**: If AgentGateway is down, all other alerts are suppressed

## Alert Routing

Alerts are routed based on:
- **Severity**: `critical` → PagerDuty + Slack + Email, `warning` → Slack
- **Component**: `llm` → LLM team, `mcp` → MCP team
- **Default**: All unmatched alerts → default email

## Monitoring Best Practices

1. **Start with Warning levels**: Don't set critical thresholds too aggressive initially
2. **Tune based on baseline**: Run for 1-2 weeks and adjust thresholds based on actual usage
3. **Use anomaly detection**: Statistical alerts catch unusual patterns
4. **Set up runbooks**: Document response procedures for each alert
5. **Review regularly**: Weekly review of alert frequency and false positives
6. **Cost alerts are critical**: Token usage can quickly become expensive

## Troubleshooting

### Alerts not firing
```bash
# Check if Prometheus sees the alert rules
kubectl exec -n monitoring prometheus-kube-prometheus-kube-prome-prometheus-0 -- \
  promtool check rules /etc/prometheus/rules/prometheus-agentgateway-alerts-rulefiles-0/*.yaml

# Check Prometheus UI
kubectl port-forward -n monitoring svc/kube-prometheus-kube-prome-prometheus 9090:9090
# Visit: http://localhost:9090/alerts
```

### Notifications not sending
```bash
# Check AlertManager logs
kubectl logs -n monitoring alertmanager-kube-prometheus-kube-prome-alertmanager-0

# Test SMTP connection
kubectl exec -n monitoring alertmanager-kube-prometheus-kube-prome-alertmanager-0 -- \
  wget --spider smtp://smtp.gmail.com:587
```

### Wrong routing
Check AlertManager routing tree:
1. Port-forward: `kubectl port-forward -n monitoring svc/kube-prometheus-kube-prome-alertmanager 9093:9093`
2. Visit: http://localhost:9093/#/status
3. Review "Config" section

## Additional Resources

- [AlertManager Documentation](https://prometheus.io/docs/alerting/latest/alertmanager/)
- [Prometheus Alerting Rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
- [Agent Gateway Observability Docs](https://agentgateway.dev/docs/llm/observability/)

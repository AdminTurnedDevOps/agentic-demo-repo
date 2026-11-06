# kagent SRE Team Demo: Observability + K8s Agent

## Overview

This demo showcases how kagent's **Observability Agent** and **K8s Agent** can work together as an AI-powered SRE team to detect and resolve production issues in Kubernetes.

**Demo Scenario: "The Memory Leak Crisis"**

An application is deployed to Kubernetes but is experiencing:
- Memory issues causing OOMKills
- High resource utilization
- Frequent pod restarts
- Application instability

The **Observability Agent** uses Prometheus (via kube-prometheus) to detect the issues, and the **K8s Agent** diagnoses and fixes them.

## What are these agents?

### Observability Agent
The kagent **Observability Agent** is a pre-built agent that integrates with Prometheus to:
- Query PromQL metrics
- Analyze resource utilization (CPU, memory, network)
- Detect anomalies in pod health
- Identify performance bottlenecks
- Monitor cluster-wide metrics

### K8s Agent
The kagent **K8s Agent** is a pre-built agent that can:
- Read and analyze Kubernetes resources (pods, deployments, services, etc.)
- Diagnose issues using kubectl commands
- Apply fixes by patching/updating resources
- Monitor rollout status
- Verify cluster health

## Demo Files

| File | Purpose |
|------|---------|
| `broken-app.yaml` | The "broken" application deployment (intentionally misconfigured) |
| `demo-script.md` | Step-by-step demo walkthrough |
| `prompts.md` | Ready-to-use prompts for the kagent UI |
| `cleanup.sh` | Script to reset the demo environment |

## Quick Start

1. Deploy the broken application:
   ```bash
   kubectl apply -f broken-app.yaml
   ```

2. Wait 1-2 minutes for the application to start failing

3. Open kagent UI and follow `prompts.md`

## Expected Demo Flow

1. **Deploy broken app** → Application starts with bad resource limits
2. **Observability Agent** → Detects memory pressure, restarts, OOMKills via Prometheus
3. **K8s Agent** → Investigates pods, identifies root cause, applies fix
4. **Verify** → Both agents confirm the application is now healthy

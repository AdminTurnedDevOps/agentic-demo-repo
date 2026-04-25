An SRE Agent needs 4 implementations to perform effectively:

1. A proper prompt/system message. This will give the direction for the Agent to take.
2. Agent Skills that are designed to turn your Agent into an SRE and observability expert.
3. A good LLM for your particular use case. This could be a main provider like Anthropic/OpenAI or your own, fine-tuned local Model.
4. Targets

The reason why is because an Agent (and AI in general) is only as good as the information you provide for it to work in a specific way.

This `.md` file breaks down what you need to build an effective SRE Agent.

## Prompt

```
You are an expert Site Reliability Engineer (SRE) agent operating in a cloud-native, 
Kubernetes-first environment. Your primary responsibilities are incident response, 
reliability engineering, observability analysis, and proactive risk mitigation.

## Identity & Scope

You have deep expertise in:
- Kubernetes cluster operations (workloads, networking, storage, RBAC)
- Service mesh (Istio)
- AI Gateway (agentgateway)
- Observability stacks (Prometheus, Grafana, OpenTelemetry, Datadog)
- Cloud platforms (AWS, GCP, Azure)
- CI/CD pipelines and GitOps workflows (Argo CD, Flux)
- Incident management and postmortem culture
- SLI/SLO/SLA definition and error budget management

## Behavior & Decision-Making

- Always prioritize service restoration over root cause analysis during an active incident.
- Follow a structured triage process: detect → contain → diagnose → remediate → document.
- Never make destructive changes (delete, drain, cordon, scale to zero) without first 
  stating the action, its impact, and requesting explicit confirmation unless you are 
  operating in auto-remediation mode.
- When diagnosing, gather signals from multiple observability sources before concluding.
- Prefer reversible actions over irreversible ones.
- Apply the principle of minimal blast radius: scope changes to the smallest affected 
  surface first.

## Incident Response Protocol

When an incident is triggered, follow this sequence:
1. Acknowledge and classify severity (SEV1–SEV4).
2. Identify affected services, namespaces, or infrastructure components.
3. Pull relevant metrics, logs, and traces. Summarize anomalies.
4. Propose a remediation plan with ranked options (fastest recovery first).
5. Execute approved actions, narrating each step.
6. Confirm service health post-remediation via health checks and SLO dashboards.
7. Draft an incident timeline for postmortem use.

## Postmortem & Learning

After resolution:
- Produce a blameless postmortem draft with: summary, timeline, root cause, 
  contributing factors, action items, and SLO impact.
- Identify whether existing runbooks need updating.
- Flag any toil that could be automated to prevent recurrence.

## Constraints

- Do not expose secrets, credentials, or internal IPs in any output.
- All kubectl, CLI, or API commands must be shown before execution and logged after.
- If confidence in a diagnosis is below 80%, state uncertainty explicitly and 
  recommend escalation or additional data gathering.
- Always operate within defined error budgets — do not approve changes that would 
  burn remaining error budget during an active freeze window.

## Communication Style

- Be direct and concise during active incidents. Bullet points over prose.
- In planning or postmortem contexts, use structured markdown with clear sections.
- Surface the most critical information first. Avoid burying the lead.
- When recommending a course of action, state: what, why, risk level, and rollback plan.
```

## ConfigMap Setup

Save the prompt above to a file, then create the ConfigMap in the `kagent` namespace:

```bash
cat > /tmp/sre-prompt.txt <<'EOF'
You are an expert Site Reliability Engineer (SRE) agent operating in a cloud-native, 
Kubernetes-first environment. Your primary responsibilities are incident response, 
reliability engineering, observability analysis, and proactive risk mitigation.

## Identity & Scope

You have deep expertise in:
- Kubernetes cluster operations (workloads, networking, storage, RBAC)
- Service mesh (Istio)
- AI Gateway (agentgateway)
- Observability stacks (Prometheus, Grafana, OpenTelemetry, Datadog)
- Cloud platforms (AWS, GCP, Azure)
- CI/CD pipelines and GitOps workflows (Argo CD, Flux)
- Incident management and postmortem culture
- SLI/SLO/SLA definition and error budget management

## Behavior & Decision-Making

- Always prioritize service restoration over root cause analysis during an active incident.
- Follow a structured triage process: detect → contain → diagnose → remediate → document.
- Never make destructive changes (delete, drain, cordon, scale to zero) without first 
  stating the action, its impact, and requesting explicit confirmation unless you are 
  operating in auto-remediation mode.
- When diagnosing, gather signals from multiple observability sources before concluding.
- Prefer reversible actions over irreversible ones.
- Apply the principle of minimal blast radius: scope changes to the smallest affected 
  surface first.

## Incident Response Protocol

When an incident is triggered, follow this sequence:
1. Acknowledge and classify severity (SEV1–SEV4).
2. Identify affected services, namespaces, or infrastructure components.
3. Pull relevant metrics, logs, and traces. Summarize anomalies.
4. Propose a remediation plan with ranked options (fastest recovery first).
5. Execute approved actions, narrating each step.
6. Confirm service health post-remediation via health checks and SLO dashboards.
7. Draft an incident timeline for postmortem use.

## Postmortem & Learning

After resolution:
- Produce a blameless postmortem draft with: summary, timeline, root cause, 
  contributing factors, action items, and SLO impact.
- Identify whether existing runbooks need updating.
- Flag any toil that could be automated to prevent recurrence.

## Constraints

- Do not expose secrets, credentials, or internal IPs in any output.
- All kubectl, CLI, or API commands must be shown before execution and logged after.
- If confidence in a diagnosis is below 80%, state uncertainty explicitly and 
  recommend escalation or additional data gathering.
- Always operate within defined error budgets — do not approve changes that would 
  burn remaining error budget during an active freeze window.

## Communication Style

- Be direct and concise during active incidents. Bullet points over prose.
- In planning or postmortem contexts, use structured markdown with clear sections.
- Surface the most critical information first. Avoid burying the lead.
- When recommending a course of action, state: what, why, risk level, and rollback plan.
EOF
```

```
kubectl create configmap my-sre-prompt \
  --namespace kagent \
  --from-file=prompt=/tmp/sre-prompt.txt
```

Verify:

```bash
kubectl get configmap my-sre-prompt -n kagent -o yaml
```

## SRE Skill

The Skill within `production-demos/your-sre-agent/sre-skill` contains:
1. A SKILL.md
2. A reference guide that points to the Google SRE handbook

This Skill is designed to ensure that your Agent has the information it needs at runtime to perform SRE actions.

## The Agent

The Agent will have 5 key aspects:
1. It will use the Go runtime for faster startup and lower resource consumption in comparison to Python Agents.
2. A system message/prompt that tells the Agent exactly what it should be doing. This will be stored in a configmap so its reusable.
3. MCP Server tools to perform specific actions based on what the Agent needs.
4. A specialized Agent Skill for SRE work.
5. Memory. The goal is to ensure that your Agent can "remember" issues that have occurred before, along with the ability to pick up where it left off.

```
export ANTHROPIC_API_KEY=

kubectl create secret generic kagent-anthropic --from-literal=ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY -n kagent
```

```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: anthropic-model-config
  namespace: kagent
spec:
  apiKeySecret: kagent-anthropic
  apiKeySecretKey: ANTHROPIC_API_KEY
  model: claude-opus-4-7
  provider: Anthropic
  anthropic: {}
EOF
```

```
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: sre-agent
  namespace: kagent
spec:
  description: An SRE and observability agent for cloud-native environments
  type: Declarative
  declarative:
    runtime: go
    modelConfig: anthropic-model-config
    promptTemplate:
      dataSources:
        - kind: ConfigMap
          name: my-sre-prompt
    systemMessage: |-
      You're a friendly and helpful agent that uses the Kubernetes tool to help for SRE related k8s tasks.

      {{include "my-custom-prompts/k8s-specific-rules"}}
    tools:
    - type: McpServer
      mcpServer:
        name: kagent-tool-server
        kind: RemoteMCPServer
        toolNames:
        - k8s_describe_resource
        - k8s_get_pod_logs
        - k8s_get_events
        - k8s_execute_command
        - k8s_get_resources
        - k8s_get_resource_yaml
  skills:
    gitRefs:
      - url: https://github.com/AdminTurnedDevOps/agentic-demo-repo.git
        ref: main
        path: production-demos/your-sre-agent/sre-skill
EOF
```

```
Run the SRE diagnostic workflow on namespace default
```

## SRE Scenario: Broken Environment

These scenarios create intentionally broken deployments to test your SRE agent's diagnostic capabilities.

### Scenario 1: Pending Pod - Resource Starvation

Deploy a pod requesting resources no cluster can satisfy. The pod will be stuck in `Pending` forever.

**What breaks:** Scheduler cannot find a node with 128Gi memory and 64 CPUs.

**What the agent should find:**
- Pod stuck in `Pending` state
- `kubectl describe pod` shows `FailedScheduling` event
- Event message: "Insufficient cpu" / "Insufficient memory"

**Fix:** Reduce resource requests to realistic values.

```bash
kubectl create namespace sre-demo
```

```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hungry-app
  namespace: sre-demo
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hungry-app
  template:
    metadata:
      labels:
        app: hungry-app
    spec:
      containers:
      - name: app
        image: nginx:1.27.0
        resources:
          requests:
            memory: "128Gi"
            cpu: "64"
          limits:
            memory: "128Gi"
            cpu: "64"
EOF
```

**Verify it's broken:**

```bash
kubectl get pods -n sre-demo
# STATUS: Pending

kubectl describe pod -n sre-demo -l app=hungry-app | grep -A5 Events
# FailedScheduling: 0/X nodes are available: X Insufficient cpu, X Insufficient memory.
```

**Prompt for SRE Agent:**

```
The hungry-app deployment in the sre-demo namespace is not running. Users report the application 
is unavailable.

Investigate why the pod is not starting, identify the root cause, and fix it so the application 
runs successfully.
```

**Expected agent behavior:**
- Get pods, see `Pending` status
- Describe pod or get events, find `FailedScheduling`
- Identify resource requests (128Gi memory, 64 CPU) exceed cluster capacity
- Patch deployment with realistic values (e.g., 256Mi memory, 250m CPU)

---

### Scenario 2: Cascading Failure (App + Redis Dependency)

This scenario creates a multi-layer failure:
1. Redis StatefulSet references a nonexistent StorageClass
2. Redis PVC stays `Pending`, so Redis pod never starts
3. Web app depends on Redis, crashes on startup (CrashLoopBackOff)

**What breaks:** The root cause is buried - app crashes mask the real issue (bad StorageClass).

**What the agent should find:**
1. App pods in `CrashLoopBackOff`
2. App logs show "connection refused" to Redis
3. Redis pod in `Pending`
4. Redis PVC in `Pending` with event: "storageclass 'premium-ssd-turbo' not found"

**Fix:** Create the StorageClass or change PVC to use an existing one.

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: sre-demo
---
# Redis StatefulSet with BAD StorageClass
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
  namespace: sre-demo
spec:
  serviceName: redis
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7.2.4
        ports:
        - containerPort: 6379
        volumeMounts:
        - name: data
          mountPath: /data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: premium-ssd-turbo  # DOES NOT EXIST
      resources:
        requests:
          storage: 1Gi
---
# Redis Service
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: sre-demo
spec:
  selector:
    app: redis
  ports:
  - port: 6379
    targetPort: 6379
---
# Web App that depends on Redis
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app
  namespace: sre-demo
spec:
  replicas: 2
  selector:
    matchLabels:
      app: web-app
  template:
    metadata:
      labels:
        app: web-app
    spec:
      containers:
      - name: app
        image: redis:7.2.4  # Using redis image to test connectivity
        command: ["sh", "-c"]
        args:
        - |
          echo "Waiting for Redis..."
          until redis-cli -h redis ping; do
            echo "Redis not ready, retrying in 2s..."
            sleep 2
          done
          echo "Connected to Redis!"
          sleep infinity
        resources:
          requests:
            memory: "64Mi"
            cpu: "100m"
          limits:
            memory: "128Mi"
            cpu: "200m"
EOF
```

**Verify it's broken:**

```bash
# App pods crash
kubectl get pods -n sre-demo -l app=web-app
# STATUS: CrashLoopBackOff (after a few restarts)

# Redis pod stuck
kubectl get pods -n sre-demo -l app=redis
# STATUS: Pending

# PVC stuck
kubectl get pvc -n sre-demo
# STATUS: Pending

# Root cause in PVC events
kubectl describe pvc -n sre-demo | grep -A3 Events
# storageclass.storage.k8s.io "premium-ssd-turbo" not found
```

**Prompt for SRE Agent:**

```
The web-app deployment in the sre-demo namespace is failing. Users report the application is 
returning errors and cannot serve requests.

Investigate all unhealthy resources in the namespace, trace the root cause (it may involve 
multiple components), and fix the issue so web-app runs successfully.
```

**Expected agent behavior:**
- Get pods, see web-app running but failing, redis-0 `Pending`
- Check web-app logs, find "Connection refused" to Redis
- Investigate Redis StatefulSet, find pod `Pending`
- Check PVC status, find `Pending`
- Check PVC events or describe PVC, find `storageclass "premium-ssd-turbo" not found`
- Trace dependency chain: web-app → Redis → PVC → StorageClass
- List available StorageClasses
- Fix by deleting stuck PVC and patching StatefulSet to use valid StorageClass (or create the missing one)

---

### Cleanup

```bash
kubectl delete namespace sre-demo
```


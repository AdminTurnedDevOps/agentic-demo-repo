# Self-Healing Infrastructure: CrashLoopBackOff Triage

This demo implements the "CrashLoopBackOff Triage" scenario using the **kagent** framework, demonstrating how agent skills enable autonomous root-cause analysis for pod failures.

## Scenario

A pod is stuck in `CrashLoopBackOff`. Instead of basic log checking, the agent uses a specialized **Triage Skill** to perform comprehensive root-cause analysis (RCA) covering:

1. **Event Inspection** - Check for OOMKills, Liveness Probe failures
2. **Log Extraction** - Identify specific error strings and patterns
3. **Network Validation** - Verify dependent services are reachable

## Files Created

| File | Description |
|------|-------------|
| `triage-skill.yaml` | Skill definition with multi-step RCA workflow |
| `sre-triage-agent.yaml` | Autonomous SRE Agent with skill integration |
| `broken-app.yaml` | 5 intentionally broken deployments for testing |
| `run-triage.sh` | Execution workflow script |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              kagent Namespace                               │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    Skill: k8s-crash-triage                            │  │
│  │                                                                       │  │
│  │  Workflow Steps:                                                      │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                   │  │
│  │  │ Step 1      │  │ Step 2      │  │ Step 3      │                   │  │
│  │  │ Events      │─▶│ Logs        │─▶│ Network     │                   │  │
│  │  │ Inspection  │  │ Extraction  │  │ Validation  │                   │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                   │  │
│  │         │                │                │                          │  │
│  │         └────────────────┴────────────────┘                          │  │
│  │                          │                                           │  │
│  │                          ▼                                           │  │
│  │                 ┌─────────────────┐                                  │  │
│  │                 │ Correlation &   │                                  │  │
│  │                 │ RCA Report      │                                  │  │
│  │                 └─────────────────┘                                  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                      │                                      │
│                                      ▼                                      │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    Agent: autonomous-sre                              │  │
│  │                                                                       │  │
│  │  "When CrashLoopBackOff detected → Invoke triage skill automatically" │  │
│  │                                                                       │  │
│  │  Skills: [k8s-crash-triage]                                          │  │
│  │  Tools:  [k8s_get_resources, k8s_get_pod_logs, k8s_get_events, ...]  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          broken-apps Namespace                              │
│                                                                             │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │ Scenario 1  │ │ Scenario 2  │ │ Scenario 3  │ │ Scenario 4  │ ...       │
│  │ Missing Env │ │ OOMKilled   │ │ No DB Conn  │ │ Probe Fail  │           │
│  │ (Config)    │ │ (Memory)    │ │ (Network)   │ │ (Health)    │           │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘           │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Skill Workflow

The triage skill executes a 3-step diagnostic workflow:

### Step 1: Event Inspection
```bash
kubectl get events --field-selector involvedObject.name={pod} -n {namespace}
kubectl describe pod {pod} -n {namespace}
```

**Looking for:**
- OOMKilled (exit code 137)
- Liveness/Readiness probe failures
- FailedScheduling
- ImagePullBackOff

### Step 2: Log Extraction
```bash
kubectl logs {pod} -n {namespace} --tail=100
kubectl logs {pod} -n {namespace} --previous --tail=100
```

**Looking for:**
- Error patterns and stack traces
- Connection refused/timeout
- Missing environment variables
- Permission denied

### Step 3: Network Validation
```bash
kubectl get endpoints -n {namespace}
kubectl get svc -n {namespace}
kubectl auth can-i get pods -n {namespace}
```

**Looking for:**
- Missing service endpoints
- DNS resolution issues
- RBAC permission problems

## Correlation Rules

The skill correlates findings across all steps:

| Event Pattern | Log Pattern | Root Cause | Fix |
|--------------|-------------|------------|-----|
| OOMKilled (exit 137) | MemoryError | Memory limit too low | Increase memory limits |
| Liveness probe failed | Connection timeout | Dependency issue | Fix dependency or probe |
| Exit code 1 | "env VAR not set" | Missing config | Add environment variable |
| ImagePullBackOff | N/A | Image issue | Fix image name/auth |

## Chaos Scenarios

Five intentionally broken deployments for testing:

| # | Scenario | Deployment | Root Cause | Fix |
|---|----------|------------|------------|-----|
| 1 | config | api-server-missing-env | Missing DATABASE_URL | Add env var |
| 2 | memory | memory-hog-oom | OOMKilled (32Mi limit) | Increase to 256Mi |
| 3 | network | web-app-no-db | postgres-db unreachable | Deploy DB service |
| 4 | health | app-bad-healthcheck | /healthz not implemented | Fix probe config |
| 5 | rbac | secret-reader-no-perms | ServiceAccount forbidden | Add RoleBinding |

## Usage

### Prerequisites

- Kubernetes cluster with kubectl access
- kagent installed ([installation guide](https://kagent.dev/docs/kagent/getting-started))

### Deploy Everything

```bash
./run-triage.sh deploy
```

This deploys:
1. The k8s-crash-triage skill
2. The autonomous-sre agent
3. All 5 broken applications

### Triage a Scenario

```bash
# By name
./run-triage.sh triage config
./run-triage.sh triage memory
./run-triage.sh triage network

# By number
./run-triage.sh triage 1
./run-triage.sh triage 2
```

### Apply a Fix

```bash
./run-triage.sh fix config
./run-triage.sh fix memory
```

### Check Status

```bash
./run-triage.sh status
```

### Cleanup

```bash
./run-triage.sh cleanup
```

## Expected Output

When the agent triages a CrashLoopBackOff pod, it produces a structured report:

```
═══════════════════════════════════════════════════════════════
                  ROOT CAUSE ANALYSIS REPORT
═══════════════════════════════════════════════════════════════

Pod: broken-apps/api-server-missing-env-7f8b9c6d5-x2k4p
Status: CrashLoopBackOff
Analysis Timestamp: 2025-01-15T03:15:00Z

┌─────────────────────────────────────────────────────────────┐
│ ROOT CAUSE: CONFIGURATION                                   │
├─────────────────────────────────────────────────────────────┤
│ Required environment variable DATABASE_URL is not set       │
└─────────────────────────────────────────────────────────────┘

EVIDENCE:

  Step 1 (Events):
    • Container exited with code 1

  Step 2 (Logs):
    • FATAL ERROR: Required environment variable DATABASE_URL is not set

  Step 3 (Network):
    • N/A - Not a network issue

RECOMMENDED FIX:

  Add the missing DATABASE_URL environment variable to the deployment

  Command:
  $ kubectl set env deployment/api-server-missing-env DATABASE_URL="postgresql://..." -n broken-apps

CONFIDENCE: High
═══════════════════════════════════════════════════════════════
```

## Skills in kagent

Skills in kagent are specialized capabilities that agents can invoke. They:

- Are defined within the Agent's `a2aConfig.skills` section
- Can be exposed to other agents via A2A (Agent-to-Agent) protocol
- Have defined input/output modes (typically "text")
- Are tagged for discoverability

### Skill Definition

```yaml
a2aConfig:
  skills:
    - id: k8s-crash-triage
      name: Kubernetes Crash Triage
      description: |
        Performs comprehensive root-cause analysis for pods in CrashLoopBackOff.
      inputModes:
        - text
      outputModes:
        - text
      tags:
        - kubernetes
        - troubleshooting
        - sre
```

## Self-Healing Behavior

The agent is configured for **autonomous operation**:

1. **Automatic Detection** - Monitors for CrashLoopBackOff status
2. **Immediate Triage** - Invokes skill without asking permission
3. **Evidence Collection** - Gathers data from all three steps
4. **Correlation** - Matches timestamps and patterns
5. **Actionable Output** - Provides copy-paste kubectl commands

This demonstrates true self-healing infrastructure where AI agents can autonomously diagnose and recommend fixes for common failure patterns.

## References

- [kagent Documentation](https://kagent.dev/docs)
- [kagent API Reference](https://kagent.dev/docs/kagent/resources/api-ref)
- [A2A Agent Integration](https://kagent.dev/docs/kagent/examples/slack-a2a)
- [kagent GitHub](https://github.com/kagent-dev/kagent)

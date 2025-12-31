# Audit Log Guardian - Fine-Tuned Model Implementation

This demo implements the "Audit Log Guardian" scenario using the **kagent** framework, demonstrating how fine-tuned models provide efficiency gains over general-purpose LLMs for specialized tasks.

## Scenario

Deploy a specialized "Security Forensic Agent" that analyzes Kubernetes audit logs to detect:
- **Privilege Escalation** patterns (RoleBinding/ClusterRoleBinding modifications)
- **Unauthorized Secret Access** attempts
- **Dangerous verb usage** (bind, escalate, impersonate)

The fine-tuned model (Llama-3-8B variant) is optimized to recognize these patterns without requiring massive system prompts, reducing "token fatigue" and improving response latency.

## Files Created

| File | Description |
|------|-------------|
| `audit-model-config.yaml` | ModelConfig resources for fine-tuned and base models |
| `audit-guardian-agent.yaml` | Agent definitions (fine-tuned + baseline for comparison) |
| `mock-audit-stream.json` | Realistic K8s audit logs with hidden security threats |
| `benchmark-test.sh` | Script to compare fine-tuned vs base model performance |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          kagent Namespace                               │
│                                                                         │
│  ┌─────────────────────────┐      ┌─────────────────────────────────┐  │
│  │   ModelConfig           │      │   ModelConfig                   │  │
│  │   fine-tuned-audit-brain│      │   base-model-config             │  │
│  │                         │      │                                 │  │
│  │   Model: llama3-8b-     │      │   Model: llama3                 │  │
│  │          k8s-audit-v1   │      │   Provider: Ollama              │  │
│  │   Provider: Ollama      │      │                                 │  │
│  └───────────┬─────────────┘      └───────────────┬─────────────────┘  │
│              │                                    │                    │
│              ▼                                    ▼                    │
│  ┌─────────────────────────┐      ┌─────────────────────────────────┐  │
│  │   Agent                 │      │   Agent                         │  │
│  │   audit-log-guardian    │      │   audit-log-guardian-baseline   │  │
│  │                         │      │                                 │  │
│  │   System Prompt: ~150   │      │   System Prompt: ~2000 tokens   │  │
│  │   tokens (minimal)      │      │   (extensive instructions)      │  │
│  └───────────┬─────────────┘      └───────────────┬─────────────────┘  │
│              │                                    │                    │
│              └────────────────┬───────────────────┘                    │
│                               │                                        │
│                               ▼                                        │
│                    ┌─────────────────────┐                             │
│                    │   MCPServer         │                             │
│                    │   audit-log-reader  │                             │
│                    │                     │                             │
│                    │   Tools:            │                             │
│                    │   - read_audit_logs │                             │
│                    │   - stream_events   │                             │
│                    └─────────────────────┘                             │
└─────────────────────────────────────────────────────────────────────────┘
```

## System Prompt Comparison

### Fine-Tuned Model (~150 tokens)
```
Analyze K8s audit logs. Report Priority 1 Security Events only.

Priority 1 Events:
- RoleBinding/ClusterRoleBinding modifications
- Secret access from unauthorized ServiceAccounts
- Privilege escalation attempts (bind, escalate, impersonate verbs)

Output format: JSON array of findings...
```

### Base Model (~2000 tokens)
```
# Role: Kubernetes Security Forensic Analyst

You are an expert security analyst specializing in Kubernetes audit log analysis...

## Understanding Kubernetes Audit Logs
Kubernetes audit logs are JSON-formatted records that capture all API server requests.
Each log entry contains:
- `apiVersion`: Always "audit.k8s.io/v1"
- `kind`: Always "Event"
...
[Extensive documentation of log structure, patterns to detect, analysis process, etc.]
```

## Mock Audit Log Threats

The `mock-audit-stream.json` contains 15 audit events with 3 hidden Priority 1 threats:

| Threat ID | Type | Actor | Severity |
|-----------|------|-------|----------|
| `THREAT-0001` | Privilege Escalation via RoleBinding Patch | dev-contractor-jsmith | CRITICAL |
| `THREAT-0002` | Unauthorized Secret Access | dev-contractor-jsmith | HIGH |
| `THREAT-0003` | User Impersonation Attack | dev-contractor-jsmith | CRITICAL |

### Attack Sequence
1. **THREAT-0001**: Contractor patches RoleBinding to add `cluster-admins` group
2. **THREAT-0002**: Same contractor immediately accesses `database-credentials` secret
3. **THREAT-0003**: Contractor impersonates `kube-system:cluster-admin` to list all kube-system secrets

## Usage

### Prerequisites

- Kubernetes cluster with kubectl access
- kagent installed ([installation guide](https://kagent.dev/docs/kagent/getting-started))
- Ollama running with the fine-tuned model loaded
- jq installed for JSON processing

### Deploy and Run Benchmark

```bash
# Run full benchmark (deploy + test + report)
./benchmark-test.sh run

# Or step by step:
./benchmark-test.sh deploy   # Deploy resources only
./benchmark-test.sh run      # Run benchmark
./benchmark-test.sh report   # Generate report from existing results
./benchmark-test.sh cleanup  # Remove all resources
```

### Configure Iterations

```bash
# Run with 5 iterations per agent
ITERATIONS=5 ./benchmark-test.sh run
```

## Expected Results

| Metric | Fine-Tuned Model | Base Model | Improvement |
|--------|------------------|------------|-------------|
| **Avg Tokens Used** | ~400 | ~2800 | ~85% reduction |
| **Avg Response Time** | ~0.8s | ~2.5s | ~68% faster |
| **Threats Detected** | 3/3 (100%) | 2-3/3 (67-100%) | More consistent |

## Model Configuration Options

### Option 1: Local Ollama (Default)

```yaml
spec:
  model: llama3-8b-k8s-audit-v1
  provider: Ollama
  ollama:
    host: http://ollama.ollama.svc.cluster.local:11434
```

### Option 2: BYO OpenAI-Compatible Endpoint

```yaml
spec:
  model: ft:llama-3-8b:k8s-audit-detector:v1
  provider: OpenAI
  apiKeySecret: fine-tuned-model-credentials
  apiKeySecretKey: API_KEY
  openAI:
    baseUrl: "https://api.your-fine-tuned-provider.com/v1"
```

## Fine-Tuning Recommendations

To create your own fine-tuned model for K8s audit log analysis:

### Training Data
1. Collect real Kubernetes audit logs from production clusters
2. Label security events by category (privilege escalation, unauthorized access, etc.)
3. Include both positive (threat) and negative (normal operation) examples
4. Aim for at least 1000 labeled examples per threat category

### Model Selection
- **Llama-3-8B**: Good balance of speed and accuracy
- **Mistral-7B**: Efficient for resource-constrained environments
- **Phi-3**: Ultra-lightweight option for edge deployment

### Training Approach
1. Start with instruction-tuned base model
2. Fine-tune on labeled audit log dataset
3. Use LoRA/QLoRA for efficient training
4. Validate on held-out security event dataset

## References

- [kagent Documentation](https://kagent.dev/docs)
- [Configuring Ollama Models](https://www.kagent.dev/docs/kagent/supported-providers/ollama)
- [BYO OpenAI-Compatible Models](https://docs.solo.io/kagent-enterprise/docs/latest/models/byo-openai/)
- [Kubernetes Audit Logging](https://kubernetes.io/docs/tasks/debug/debug-cluster/audit/)

# 3 AM Runbook - RAG Knowledge Implementation

This demo implements the "3 AM Runbook" scenario using the **kagent** framework, demonstrating how RAG (Retrieval-Augmented Generation) enables AI agents to leverage internal documentation for troubleshooting issues not covered by public documentation.

## Scenario

A production database pod fails to start at 3 AM with a cryptic CSI storage error (0x99). The solution is NOT in public Kubernetes documentation - it requires a proprietary annotation (`storage.internal/manual-unlock: true`) documented only in an internal runbook.

## The Problem

```
Warning  FailedMount  MountVolume.SetUp failed for volume "pv-database-storage":
         CSI driver error (0x99): Volume attachment state mismatch
         Stale attachment exists on node worker-node-03
```

**Without RAG:** A general LLM would suggest generic troubleshooting (restart pod, check storage class, etc.) that won't resolve this NetApp-specific issue.

**With RAG:** The agent retrieves the internal runbook and applies the correct proprietary fix.

## Files Created

| File | Description |
|------|-------------|
| `storage-runbook-knowledge.yaml` | Knowledge base with internal runbook content + MCP server |
| `storage-sre-agent.yaml` | Storage Expert Agent with RAG integration |
| `failing-pvc.yaml` | Chaos scenario simulating CSI error 0x99 |
| `run-rag-test.sh` | Demonstration script |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              kagent Namespace                               │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                     Knowledge Base (RAG)                              │  │
│  │  ┌─────────────────┐    ┌─────────────────────────────────────────┐   │  │
│  │  │ ConfigMap       │───▶│ MCPServer: storage-runbook-knowledge    │   │  │
│  │  │ (Runbook Text)  │    │                                         │   │  │
│  │  │                 │    │ Tools:                                  │   │  │
│  │  │ - CSI Error 0x99│    │ - query_documentation                   │   │  │
│  │  │ - Resolution    │    │ - search_runbooks                       │   │  │
│  │  │ - Annotation    │    │                                         │   │  │
│  │  └─────────────────┘    └─────────────────────────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                      │                                      │
│                                      ▼                                      │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                     Agent: storage-expert                             │  │
│  │                                                                       │  │
│  │  System Prompt: "ALWAYS check internal knowledge FIRST..."            │  │
│  │                                                                       │  │
│  │  Tools:                                                               │  │
│  │  ├── query_documentation (Knowledge)                                  │  │
│  │  ├── k8s_get_resources                                                │  │
│  │  ├── k8s_delete_resource (VolumeAttachments)                          │  │
│  │  └── k8s_annotate_resource (PVC unlock)                               │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         production-app Namespace                            │
│                                                                             │
│  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────────────┐   │
│  │ Pod             │   │ PVC             │   │ VolumeAttachment        │   │
│  │ database-pod    │──▶│ database-       │──▶│ csi-abc123-worker-03    │   │
│  │                 │   │ storage-claim   │   │ (STALE - needs delete)  │   │
│  │ Status: Stuck   │   │                 │   │                         │   │
│  │ ContainerCreate │   │ Missing:        │   │ Node: worker-node-03    │   │
│  │                 │   │ manual-unlock   │   │ State: Detached         │   │
│  └─────────────────┘   └─────────────────┘   └─────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Knowledge Base Content

The internal runbook (`Storage-Failure-SOP-2025.pdf`) contains:

```markdown
## Section 3.2: CSI Driver Error Codes

### Error 0x99 - Stale Volume Attachment (NetApp-CSI)

**Resolution Procedure:**

1. Identify the stale VolumeAttachment:
   kubectl get volumeattachment | grep <pv-name>

2. Delete the stale VolumeAttachment resource:
   kubectl delete volumeattachment <attachment-name>

3. Apply the manual unlock annotation to the PVC:
   kubectl annotate pvc <pvc-name> storage.internal/manual-unlock=true

**CRITICAL:** The annotation `storage.internal/manual-unlock: true` is MANDATORY
for our NetApp-CSI configuration.
```

## Agent Behavior

The Storage Expert Agent follows a strict **Knowledge-First Approach**:

1. **Query Knowledge** - Searches internal runbooks for error code/symptoms
2. **Cite Sources** - References specific document and section
3. **Apply Fix** - Executes procedures from the runbook
4. **Verify** - Confirms the fix was applied correctly

### Expected Agent Output

```
According to the Storage-Failure-SOP-2025, Section 3.2:

"If CSI error 0x99 occurs on NetApp-CSI, users must delete the stale
'volume-attachment' resource and apply the annotation
'storage.internal/manual-unlock: true' to the PVC."

Executing resolution procedure...
```

## Usage

### Prerequisites

- Kubernetes cluster with kubectl access
- kagent installed ([installation guide](https://kagent.dev/docs/kagent/getting-started))
- OpenAI API key (for text embeddings)

### Run the Demo

```bash
# Run complete demonstration
./run-rag-test.sh run

# Or step by step:
./run-rag-test.sh init    # Initialize knowledge base + agent
./run-rag-test.sh chaos   # Create failing PVC scenario
./run-rag-test.sh invoke  # Invoke agent to fix issue
./run-rag-test.sh cleanup # Clean up all resources
```

### Demo Flow

1. **Initialize** - Deploy knowledge base with runbook content
2. **Create Chaos** - Deploy failing PVC with stale VolumeAttachment
3. **Invoke Agent** - Agent queries knowledge, finds fix, executes commands
4. **Verify** - PVC now has required annotation, VolumeAttachment deleted

## The Fix Applied

| Before | After |
|--------|-------|
| VolumeAttachment: `csi-abc123-worker-node-03` exists | VolumeAttachment: Deleted |
| PVC annotation: (missing) | PVC annotation: `storage.internal/manual-unlock: true` |
| Pod status: ContainerCreating | Pod status: Running |

## Why RAG Matters

| Approach | Result |
|----------|--------|
| **Google Search** | Generic Kubernetes troubleshooting, won't find proprietary annotation |
| **ChatGPT/Claude (no RAG)** | Suggests standard CSI debugging, misses NetApp-specific fix |
| **Agent with RAG** | Retrieves internal runbook, applies exact fix with citation |

## Key Demonstration Points

1. **Knowledge Retrieval** - Agent queries vector database before suggesting fixes
2. **Source Citation** - Agent explicitly cites "Storage-Failure-SOP-2025, Section 3.2"
3. **Proprietary Fix** - Applies organization-specific annotation not in public docs
4. **Audit Trail** - All actions traced back to documented procedures

## Building Your Own Knowledge Base

### Option 1: doc2vec + SQLite-vec

```bash
# Clone doc2vec repository
git clone https://github.com/kagent-dev/doc2vec
cd doc2vec && npm install

# Configure source documents
cat > config.yaml <<EOF
sources:
  - url: file:///path/to/runbooks/
    product: internal-sops
    version: "2025"
output:
  database: ./knowledge.db
EOF

# Run embedding
npm run embed
```

### Option 2: Existing Vector Database

Configure `RemoteMCPServer` to point to your existing vector DB:

```yaml
apiVersion: kagent.dev/v1alpha2
kind: RemoteMCPServer
metadata:
  name: corporate-knowledge
spec:
  url: http://your-vector-db.internal:8080/mcp
  timeout: 30s
```

## References

- [kagent Documentation Tools](https://kagent.dev/docs/kagent/examples/documentation)
- [Using Documentation in Agents](https://kagent.dev/docs/kagent/examples/documentation)
- [kagent GitHub](https://github.com/kagent-dev/kagent)
- [doc2vec Repository](https://github.com/kagent-dev/doc2vec)

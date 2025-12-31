Act as a Principal Platform Engineer. I am finishing a whitepaper on Agentic AI as distributed systems. I need to implement the "3 AM Runbook" RAG scenario using the **kagent** framework.

### Scenario Context:
A PersistentVolume (PV) is failing to mount with a cryptic 'CSI Storage Error' on a production cluster. The solution is NOT in the public Kubernetes documentation; it is contained in a private, internal PDF runbook titled 'Storage-Failure-SOP-2025.pdf'. This runbook specifies a unique mandatory annotation and a specific cleanup command for our custom storage array.

### Requirements:
Please generate the following:

1. **Knowledge Manifest (`storage-runbook-knowledge.yaml`):**
   - Create a `kagent.dev/v1alpha1` `Knowledge` resource.
   - Configure it to point to a local directory or a mock vector store containing the internal runbook text.
   - The content should include: "If CSI error 0x99 occurs on NetApp-CSI, users must delete the stale 'volume-attachment' resource and apply the annotation 'storage.internal/manual-unlock: true' to the PVC."

2. **Agent Manifest (`storage-sre-agent.yaml`):**
   - Create a `kagent.dev/v1alpha2` `Agent` resource named `storage-expert`.
   - **Knowledge Integration:** Attach the `storage-runbook-knowledge` to this agent.
   - **System Message:** Instruct the agent that it must check internal knowledge FIRST before suggesting any CSI storage fixes. It must cite the runbook in its final report.
   - **Tools:** Connect it to an MCP server that can perform 'kubectl delete volumeattachment' and 'kubectl annotate pvc'.

3. **Chaos Scenario (`failing-pvc.yaml`):**
   - Create a PersistentVolumeClaim and a Pod that are intentionally misconfigured to trigger a storage mount failure.

4. **Demonstration Script (`run-rag-test.sh`):**
   - Commands to initialize the knowledge base, deploy the agent, and invoke it to fix the failing PVC.
   - The goal is to show the Agent saying: "According to the Storage-Failure-SOP-2025, I am now applying the manual-unlock annotation."

Ensure all resources follow the latest kagent CRD schemas for Knowledge-augmented agents.
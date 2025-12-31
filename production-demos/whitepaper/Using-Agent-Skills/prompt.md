Act as a Principal SRE and AI Engineer. I am building a "Self-Healing Infrastructure" whitepaper. I need to implement the "CrashLoopBackOff Triage" scenario using the **kagent** framework.

### Scenario Context:
A Pod is stuck in `CrashLoopBackOff`. Instead of a basic log check, the Agent must use a "Triage Skill" to perform a root-cause analysis (RCA) that covers:
1. Event Inspection (Checking for OOMKills or Liveness Probe failures).
2. Log Extraction (Identifying specific error strings).
3. Network Validation (Checking if the Pod's dependent services are reachable).

### Requirements:
Please generate the following:

1. **Agent Skill Manifest (`triage-skill.yaml`):**
   - Define a `kagent.dev/v1alpha1` `Skill` resource named `k8s-crash-triage`.
   - **Logic:** Define a multi-step workflow. Step 1: `kubectl get events`. Step 2: `kubectl logs --previous`. Step 3: `kubectl auth can-i`.
   - **Instruction:** Provide a specialized prompt for this skill that tells the Agent how to correlate events with log timestamps.

2. **Agent Manifest (`sre-triage-agent.yaml`):**
   - Create a `kagent.dev/v1alpha2` `Agent` resource named `autonomous-sre`.
   - **Skills Integration:** Attach the `k8s-crash-triage` skill to this agent.
   - **System Message:** Instruct the agent that when a `CrashLoopBackOff` is detected, it should automatically invoke the triage skill and output a "Root Cause Report" with a recommended fix (e.g., "Increase memory limit" or "Fix DB Connection String").

3. **Chaos Scenario (`broken-app.yaml`):**
   - Create a Deployment that is intentionally broken (e.g., a container that exits immediately due to a missing Environment Variable or an OOM error).

4. **Execution Workflow (`run-triage.sh`):**
   - Commands to deploy the skill, the agent, and the broken app.
   - The `kagent` command to trigger the agent to investigate the specific broken namespace.

Ensure the YAMLs follow the kagent CRD specifications for Skill-to-Agent mapping.
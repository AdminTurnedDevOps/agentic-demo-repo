Act as a Cloud Native Security Engineer and AI Architect. I am writing a whitepaper on Agentic AI as distributed systems. I need to implement the "Audit Log Guardian" scenario using the **kagent** framework (kagent.dev).

### Scenario Context:
We are deploying a specialized "Security Forensic Agent." General LLMs often struggle with the specific, verbose structure of Kubernetes Audit Logs (JSON), leading to high latency and "token fatigue." We have fine-tuned a smaller model (e.g., Llama-3-8B) specifically to recognize "Privilege Escalation" patterns and "Unauthorized Secret Access" within these logs without needing massive system prompts.

### Requirements:
Please generate the following files and configurations:

1. **ModelConfig Manifest (`audit-model-config.yaml`):**
   - Create a `kagent.dev/v1alpha2` `ModelConfig` resource.
   - Configure it to point to a custom provider (like Ollama or a private OpenAI fine-tuned model endpoint).
   - Name it `fine-tuned-audit-brain`. 
   - Note: This represents the "specialized hardware/software node" in our distributed system.

2. **Agent Manifest (`audit-guardian-agent.yaml`):**
   - Create a `kagent.dev/v1alpha2` `Agent` resource named `audit-log-guardian`.
   - **Model Reference:** Point this agent to the `fine-tuned-audit-brain` ModelConfig.
   - **System Message:** Write a concise system prompt. Since the model is fine-tuned, the prompt should be minimal—focusing only on the task of identifying "Priority 1 Security Events" in the provided log stream.
   - **Tools:** Connect it to an MCP server tool that can stream or read audit logs (e.g., from a file or a mock log service).

3. **Mock Audit Logs (`mock-audit-stream.json`):**
   - Create a JSON file containing realistic Kubernetes audit logs. 
   - Include a "hidden" security threat: a user attempting to 'patch' a RoleBinding to escalate permissions.

4. **Comparison Script (`benchmark-test.sh`):**
   - Provide a script that invokes two agents: one using a 'Base' model and one using this 'Fine-Tuned' model.
   - The goal is to show that the fine-tuned agent uses fewer tokens and identifies the threat 100% of the time.

Ensure all resources follow the kagent CRD schemas and best practices for declarative agents.
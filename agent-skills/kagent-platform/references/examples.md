# Examples

Use these artifacts as the first starting point for new manifests or for diagnosing what the platform expects.

## OSS examples

- Basic TLS and provider model configs:
  `/Users/michaellevan/gitrepos/kagent/examples/modelconfig-with-tls.yaml`
- Agent with git and OCI skills:
  `/Users/michaellevan/gitrepos/kagent/go/core/internal/controller/translator/agent/testdata/inputs/agent_with_git_skills.yaml`
- Agent with prompt template includes:
  `/Users/michaellevan/gitrepos/kagent/go/core/internal/controller/translator/agent/testdata/inputs/agent_with_prompt_template.yaml`
- Agent with API key passthrough:
  `/Users/michaellevan/gitrepos/kagent/go/core/internal/controller/translator/agent/testdata/inputs/agent_with_passthrough.yaml`
- ToolServer example using stdio MCP:
  `/Users/michaellevan/gitrepos/kagent/contrib/tools/context7.mcp.yaml`
- Remote MCP server plus agent example:
  `/Users/michaellevan/gitrepos/kagent/contrib/tools/k8sgpt-mcp-server/k8sgpt-agent.yaml`
- Grafana and GitHub tool server chart templates:
  `/Users/michaellevan/gitrepos/kagent/contrib/tools/mcp-grafana/templates/toolserver.yaml`
  `/Users/michaellevan/gitrepos/kagent/contrib/tools/github-mcp-server/templates/toolserver.yaml`

## Enterprise examples

- Enterprise agent plus `ModelConfig` plus `AccessPolicy`:
  `/Users/michaellevan/gitrepos/kagent-enterprise/services/kagent-enterprise/controller/examples/enterprise-k8s-agent.yaml`
- AccessPolicy allow example:
  `/Users/michaellevan/gitrepos/kagent-enterprise/test/e2e/waypoint-translation/testdata/test-agent-jwt-auth-allow.yaml`
- AccessPolicy deny example:
  `/Users/michaellevan/gitrepos/kagent-enterprise/test/e2e/waypoint-translation/testdata/test-agent-jwt-auth-deny.yaml`
- Tool-level deny examples:
  `/Users/michaellevan/gitrepos/kagent-enterprise/test/e2e/waypoint-translation/testdata/test-mcpserver-tool-deny.yaml`
- Enterprise model config examples:
  `/Users/michaellevan/gitrepos/kagent-enterprise/test/e2e/waypoint-translation/testdata/model-configs.yaml`

## How to use examples

- Start from the closest shipped example instead of composing a manifest from memory.
- Trim fields rather than rewriting the object structure.
- Preserve `apiVersion`, `kind`, namespace assumptions, and secret key names from the source example unless you have repo evidence that a change is valid.
- If the example lives in test data, say that it is a repo-backed example rather than a public docs example.

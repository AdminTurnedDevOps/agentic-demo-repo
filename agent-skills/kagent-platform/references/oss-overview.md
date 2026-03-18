# OSS Overview

Use this reference for kagent OSS installation, manifest authoring, and runtime troubleshooting.

## Primary sources

- Official docs: `kagent.dev/docs/kagent`
- Local repo: `/Users/michaellevan/gitrepos/kagent`

Prefer the local repo when field names, API versions, or examples in the docs are vague.

## Core resources to verify first

- `Agent`: `/Users/michaellevan/gitrepos/kagent/go/api/v1alpha2/agent_types.go`
- `ModelConfig`: `/Users/michaellevan/gitrepos/kagent/go/api/v1alpha2/modelconfig_types.go`
- `RemoteMCPServer`: `/Users/michaellevan/gitrepos/kagent/go/api/v1alpha2/remotemcpserver_types.go`
- `ToolServer`: `/Users/michaellevan/gitrepos/kagent/go/api/v1alpha1/toolserver_types.go`
- `Memory`: `/Users/michaellevan/gitrepos/kagent/go/api/v1alpha1/memory_types.go`
- `ModelProviderConfig`: `/Users/michaellevan/gitrepos/kagent/go/api/v1alpha2/modelproviderconfig_types.go`

## High-value repo artifacts

Read these before writing or fixing manifests:

- Architecture summary:
  `/Users/michaellevan/gitrepos/kagent/docs/architecture/crds-and-types.md`
- Helm install surface:
  `/Users/michaellevan/gitrepos/kagent/helm/kagent`
- CRD bases:
  `/Users/michaellevan/gitrepos/kagent/go/api/config/crd/bases`
- Sample agent manifests:
  `/Users/michaellevan/gitrepos/kagent/go/core/internal/controller/translator/agent/testdata/inputs`
- Public examples:
  `/Users/michaellevan/gitrepos/kagent/examples`
- Contrib tool examples:
  `/Users/michaellevan/gitrepos/kagent/contrib/tools`

## Common OSS authoring patterns

### Agent

Use `Agent` for the main runtime object. Verify these areas in the type definition before suggesting fields:

- `spec.type`
- `spec.declarative.runtime`
- `spec.declarative.systemMessage` or `systemMessageFrom`
- `spec.declarative.promptTemplate`
- `spec.declarative.modelConfig`
- `spec.declarative.tools`
- `spec.skills`
- `spec.allowedNamespaces`

Use these examples when relevant:

- Git and OCI skills:
  `/Users/michaellevan/gitrepos/kagent/go/core/internal/controller/translator/agent/testdata/inputs/agent_with_git_skills.yaml`
- Prompt templates:
  `/Users/michaellevan/gitrepos/kagent/go/core/internal/controller/translator/agent/testdata/inputs/agent_with_prompt_template.yaml`
- API key passthrough:
  `/Users/michaellevan/gitrepos/kagent/go/core/internal/controller/translator/agent/testdata/inputs/agent_with_passthrough.yaml`

### ModelConfig

Use `ModelConfig` for agent-facing model selection and credentials. Verify:

- `provider`
- `model`
- secret name and key
- provider-specific blocks such as `openAI`, `azureOpenAI`, or `bedrock`
- TLS or passthrough behavior

Start from:

- `/Users/michaellevan/gitrepos/kagent/examples/modelconfig-with-tls.yaml`
- `/Users/michaellevan/gitrepos/kagent/helm/kagent/templates/modelconfig.yaml`

### RemoteMCPServer

Use `RemoteMCPServer` for HTTP or SSE MCP endpoints that agents reference. Verify:

- `protocol`
- `url`
- `headersFrom`
- `timeout`
- `sseReadTimeout`
- `allowedNamespaces`

Inspect `status.discoveredTools` when tool wiring fails.

### ToolServer

Treat `ToolServer` as a legacy-but-still-present surface in this repo. Verify the exact API version and fields before using it. Start from:

- `/Users/michaellevan/gitrepos/kagent/contrib/tools/context7.mcp.yaml`
- `/Users/michaellevan/gitrepos/kagent/contrib/tools/github-mcp-server/templates/toolserver.yaml`
- `/Users/michaellevan/gitrepos/kagent/contrib/tools/mcp-grafana/templates/toolserver.yaml`

### ModelProviderConfig

Use `ModelProviderConfig` only when the request is about provider-level configuration or model discovery. Do not substitute it for `ModelConfig` unless the request is clearly about provider registration or discovered models.

## OSS troubleshooting checklist

1. Verify the product is OSS, not Enterprise.
2. Verify the manifest API versions against local CRDs and examples.
3. Verify the referenced `ModelConfig` exists in the same namespace as the `Agent`.
4. Verify the secret name and key used by `ModelConfig`.
5. Verify the `RemoteMCPServer` URL, protocol, headers, and timeouts.
6. Verify the tool names referenced by the `Agent` actually appear in `discoveredTools`.
7. Verify cross-namespace references only when `allowedNamespaces` permits them.
8. Verify prompt template aliases and included keys exist.

## When docs and repo disagree

- Use the docs for supported install flow and high-level product behavior.
- Use the repo for exact manifest shape and current API details.
- Say explicitly when you are following repo reality over doc wording.

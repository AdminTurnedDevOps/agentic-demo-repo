---
name: kagent-platform
description: Install, configure, use, debug, and troubleshoot kagent OSS and Solo Enterprise for kagent on Kubernetes. Use when Codex needs to author or review kagent manifests, Helm values, model and MCP server configuration, agent prompts or skills, or diagnose runtime, authn, and authz issues across OSS and Enterprise deployments, including AccessPolicy, OIDC, management/workload topology, and repo-versus-doc API drift.
---

# Kagent Platform

## Overview

Use this skill to work from the supported docs first and then ground the answer in the local repos when the docs are incomplete, ambiguous, or stale. Treat code and shipped examples as the source of truth for exact CRD fields, API versions, chart behavior, and enterprise-only resources.

## Source Order

Follow this order unless the user explicitly asks otherwise:

1. Use the official OSS docs for supported install and usage flows.
2. Use the official Enterprise docs for supported Solo Enterprise behavior.
3. Prefer the local `kagent` and `kagent-enterprise` repos over docs for exact manifest shape, chart values, examples, and feature drift.

In this environment, the authoritative local repos are:

- `/Users/michaellevan/gitrepos/kagent`
- `/Users/michaellevan/gitrepos/kagent-enterprise`

If those paths do not exist, locate local clones named `kagent` and `kagent-enterprise`. If no local clone exists, fall back to the official docs and clearly say that repo verification was unavailable.

## Workflow

### 1. Classify the request

Choose the smallest relevant surface area first.

- Read `references/oss-overview.md` for OSS install, Helm, CLI, `Agent`, `ModelConfig`, `RemoteMCPServer`, prompt templates, skills, A2A, and general manifest authoring.
- Read `references/enterprise-overview.md` for Solo Enterprise install, management/workload topology, OIDC, `AccessPolicy`, and enterprise troubleshooting.
- Read `references/examples.md` when the user wants a manifest, a starting point, or a concrete known-good pattern.
- Read `references/api-drift.md` before suggesting API versions or resource kinds when the request touches `ToolServer`, `Memory`, `ModelProviderConfig`, or any mixed OSS/Enterprise authoring.

### 2. Rebuild context from source artifacts

Read the exact manifests, chart templates, CRDs, and type definitions that control the requested behavior. Do not rely on memory for field names or versions.

Prefer these artifact types:

- CRD base YAML
- Go type definitions
- Helm templates and values
- Shipped example manifests
- E2E test manifests when examples are sparse

### 3. Author or review changes from real patterns

When writing manifests or debugging configuration:

- Start from a shipped example or chart template rather than inventing fields.
- Match the API version and kind used by the relevant repo artifact.
- Preserve namespace assumptions, secret key names, and cross-resource references exactly.
- Call out when a suggestion is inferred from tests or templates rather than explicitly documented.

### 4. Troubleshoot methodically

When debugging, move in this order:

1. Confirm install path and product variant.
2. Confirm CRDs and API versions.
3. Confirm namespace, secret, and reference wiring.
4. Confirm status conditions and discovered tool/model state.
5. Confirm authn/authz and cross-namespace policy behavior.
6. Confirm whether the docs and repo disagree, then follow the repo.

## Authoring Rules

- Prefer `kagent.dev/v1alpha2` for `Agent`, `ModelConfig`, and `RemoteMCPServer` unless the local repo clearly shows otherwise.
- Do not assume every kagent resource is `v1alpha2`; read `references/api-drift.md` first.
- Treat Enterprise `AccessPolicy` as separate from OSS core resources.
- Prefer same-namespace references unless the resource explicitly supports cross-namespace use.
- When a request mixes OSS and Enterprise concepts, explain which parts are OSS core and which parts are Solo Enterprise extensions.

## Troubleshooting Focus

Check these failure classes first:

- CRDs missing or wrong version for the manifest being applied
- `Agent.spec.declarative.modelConfig` pointing at the wrong name or namespace
- Secret name/key mismatch for model credentials
- `RemoteMCPServer.status.discoveredTools` not populated or tool names not matching the agent reference
- Prompt template data sources or includes not matching the referenced ConfigMap or Secret keys
- Enterprise `AccessPolicy` subject, target, or tool selection mismatch
- OIDC group claim, issuer, audience, or JWKS configuration mismatch in Enterprise setups

## Output Expectations

- Distinguish clearly between supported documented guidance and repo-backed inference.
- Include the exact file paths you used when the answer depends on repo behavior.
- If the request is for a manifest, produce the smallest valid manifest that matches the current repo reality.
- If the request is for troubleshooting, give a short ranked checklist and the most likely fault domain first.

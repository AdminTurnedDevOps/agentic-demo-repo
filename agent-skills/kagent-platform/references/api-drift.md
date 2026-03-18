# API Drift

Use this reference before suggesting API versions or resource kinds.

## Current baseline

Treat the current repo reality as:

- `Agent`: `kagent.dev/v1alpha2`
- `ModelConfig`: `kagent.dev/v1alpha2`
- `RemoteMCPServer`: `kagent.dev/v1alpha2`
- `AccessPolicy`: `policy.kagent-enterprise.solo.io/v1alpha1`

## Important mismatch

The OSS architecture doc says all kagent CRDs use `kagent.dev/v1alpha2`, except `MCPServer` from KMCP. The repo snapshot does not fully match that statement.

The local OSS repo still contains:

- `ToolServer` on `kagent.dev/v1alpha1`
- `Memory` on `kagent.dev/v1alpha1`

There are also shipped examples that still use `ToolServer` with `v1alpha1`.

## Additional nuance

The local OSS repo also contains `ModelProviderConfig` on `kagent.dev/v1alpha2`. Treat it as a distinct provider-level resource. Do not collapse it into `ModelConfig`.

## Practical rule

When writing manifests:

1. Verify the exact resource in the local type definition or CRD base.
2. Verify the exact version in a shipped example or chart template.
3. Only then produce the manifest.

Do not normalize `ToolServer` or `Memory` to `v1alpha2` unless the local repo you are working from actually shows that change.

## Verification paths

- Architecture doc:
  `/Users/michaellevan/gitrepos/kagent/docs/architecture/crds-and-types.md`
- `Agent` type:
  `/Users/michaellevan/gitrepos/kagent/go/api/v1alpha2/agent_types.go`
- `ModelConfig` type:
  `/Users/michaellevan/gitrepos/kagent/go/api/v1alpha2/modelconfig_types.go`
- `RemoteMCPServer` type:
  `/Users/michaellevan/gitrepos/kagent/go/api/v1alpha2/remotemcpserver_types.go`
- `ToolServer` type:
  `/Users/michaellevan/gitrepos/kagent/go/api/v1alpha1/toolserver_types.go`
- `Memory` type:
  `/Users/michaellevan/gitrepos/kagent/go/api/v1alpha1/memory_types.go`
- `ModelProviderConfig` type:
  `/Users/michaellevan/gitrepos/kagent/go/api/v1alpha2/modelproviderconfig_types.go`
- Enterprise `AccessPolicy` type:
  `/Users/michaellevan/gitrepos/kagent-enterprise/services/kagent-enterprise/controller/api/v1alpha1/accesspolicy_types.go`

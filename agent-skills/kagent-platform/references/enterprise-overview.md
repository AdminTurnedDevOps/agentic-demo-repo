# Enterprise Overview

Use this reference for Solo Enterprise for kagent installation, auth, policy, topology, and troubleshooting.

## Primary sources

- Official docs: `docs.solo.io/kagent-enterprise/docs/latest`
- Local repo: `/Users/michaellevan/gitrepos/kagent-enterprise`

Prefer the local repo for exact CRD shape, chart behavior, and enterprise-only examples.

## Enterprise-specific surfaces

- `AccessPolicy` type:
  `/Users/michaellevan/gitrepos/kagent-enterprise/services/kagent-enterprise/controller/api/v1alpha1/accesspolicy_types.go`
- Enterprise example manifest:
  `/Users/michaellevan/gitrepos/kagent-enterprise/services/kagent-enterprise/controller/examples/enterprise-k8s-agent.yaml`
- Enterprise CRDs chart:
  `/Users/michaellevan/gitrepos/kagent-enterprise/charts/kagent-enterprise-crds`
- Enterprise chart:
  `/Users/michaellevan/gitrepos/kagent-enterprise/charts/kagent-enterprise`
- Environment examples:
  `/Users/michaellevan/gitrepos/kagent-enterprise/test/environment`

## Installation and topology

Use the Enterprise docs for supported install order and prerequisites. Use the local repo for exact chart behavior and local-dev assumptions.

Important repo hints:

- The CRDs chart must be installed before the enterprise chart.
- The repo supports both Helm-based and operator-based environments.
- There are explicit management and workload environment manifests under `test/environment`.

Read these when install behavior matters:

- `/Users/michaellevan/gitrepos/kagent-enterprise/README.md`
- `/Users/michaellevan/gitrepos/kagent-enterprise/charts/kagent-enterprise-crds/README.md`
- `/Users/michaellevan/gitrepos/kagent-enterprise/test/environment/helm-management.yaml`
- `/Users/michaellevan/gitrepos/kagent-enterprise/test/environment/helm-workload.yaml`
- `/Users/michaellevan/gitrepos/kagent-enterprise/test/environment/operator-management.yaml`
- `/Users/michaellevan/gitrepos/kagent-enterprise/test/environment/operator-workload.yaml`

## AccessPolicy

Treat `AccessPolicy` as an Enterprise extension, not an OSS core resource.

Key model:

- `spec.action`: `ALLOW` or `DENY`
- `spec.from.subjects`: `UserGroup`, `ServiceAccount`, or `Agent`
- `spec.targetRef.kind`: `Agent` or `MCPServer`
- `spec.targetRef.tools`: only valid for `MCPServer`

Important behaviors to remember:

- Tool scoping is only valid for `MCPServer` targets.
- Zero subjects can be used for a zero-trust baseline in namespace-wide policy setups.
- Status includes resolved targets and resolved subjects, which is often the fastest way to debug policy mismatch.

Use these examples and tests:

- `/Users/michaellevan/gitrepos/kagent-enterprise/services/kagent-enterprise/controller/examples/enterprise-k8s-agent.yaml`
- `/Users/michaellevan/gitrepos/kagent-enterprise/test/e2e/waypoint-translation/testdata/test-agent.yaml`
- `/Users/michaellevan/gitrepos/kagent-enterprise/test/e2e/waypoint-translation/testdata/test-agent-jwt-auth-allow.yaml`
- `/Users/michaellevan/gitrepos/kagent-enterprise/test/e2e/waypoint-translation/testdata/test-agent-jwt-auth-deny.yaml`
- `/Users/michaellevan/gitrepos/kagent-enterprise/test/e2e/waypoint-translation/testdata/test-mcpserver-tool-deny.yaml`

## OIDC and authn

When the request involves login, user groups, JWTs, or identity propagation, inspect the Enterprise auth code and docs rather than inferring behavior.

Start here:

- `/Users/michaellevan/gitrepos/kagent-enterprise/middleware/pkg/oidc`
- `/Users/michaellevan/gitrepos/kagent-enterprise/dev-keycloak`
- `/Users/michaellevan/gitrepos/kagent-enterprise/charts/kagent-enterprise/templates/oidc-secret.yaml`

Pay attention to:

- issuer
- audiences
- claim names and values
- JWKS source
- whether the subject is a user group or service account

## Enterprise troubleshooting checklist

1. Verify Enterprise CRDs are installed before Enterprise resources.
2. Verify management/workload cluster assumptions for the environment in question.
3. Verify OSS core resources first: `Agent`, `ModelConfig`, `RemoteMCPServer`.
4. Verify Enterprise extensions next: `AccessPolicy`, OIDC secrets, and policy/controller behavior.
5. Read policy status for resolved target and subject errors before changing the manifest.
6. If the setup mentions waypoint translation or agentgateway, inspect the E2E test data and controller code for the concrete translation behavior.

## When docs are thin

Prefer these repo artifacts in order:

1. Type definitions
2. Chart templates
3. Shipped examples
4. E2E manifests and tests

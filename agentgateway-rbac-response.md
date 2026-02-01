# AgentGateway RBAC and Least-Privilege Configuration Guide

A  comprehensive guide below that includes:
- Full breakdown of each permission and its purpose
- Configuration examples for namespace selectors
- Security-hardened Helm values
- Justification for each permission category

Please review the attached documentation, and let us know if you'd like to schedule a call to discuss your specific deployment architecture. We're happy to work with your security team to find the best approach for your environment.

Best regards,
[Your Name]

---

## Overview

This document addresses concerns regarding the cluster-wide RBAC permissions required by AgentGateway when deployed to Kubernetes. We understand that security policies and least-privilege requirements are critical, and this guide explains the permission model, why these permissions are necessary, and what mitigation options are available.

---

## Executive Summary

AgentGateway requires **ClusterRole** permissions because it implements the Kubernetes Gateway API specification, which is inherently cluster-scoped. While these permissions cannot be reduced to namespace-scoped Roles without breaking core functionality, there are configuration options to limit the operational scope of the controller.

---

## Current Permission Model

### ClusterRole Permissions Breakdown

AgentGateway creates two ClusterRoles during installation:

#### 1. Main Controller ClusterRole (`enterprise-agentgateway-default`)

| API Group | Resources | Verbs | Purpose |
|-----------|-----------|-------|---------|
| `""` (core) | configmaps, services | create, delete, get, list, patch, update, watch | Manage Gateway data plane configurations |
| `""` (core) | endpoints, namespaces, nodes, pods | get, list, watch | Service discovery and routing |
| `""` (core) | events | create, patch | Event logging |
| `""` (core) | secrets, serviceaccounts | create, delete, get, list, patch, watch | TLS certificates and service accounts for data plane pods |
| `apps` | deployments | create, delete, get, list, patch, update, watch | Manage Gateway data plane deployments |
| `gateway.networking.k8s.io` | gateways, httproutes, grpcroutes, tcproutes, tlsroutes, etc. | get, list, watch | Core Gateway API functionality |
| `gateway.networking.k8s.io` | */status | patch, update | Update resource status |
| `rbac.authorization.k8s.io` | roles, rolebindings, clusterroles, clusterrolebindings | create, patch, delete, get, list, watch | RBAC for dynamically created data plane pods |
| `authentication.k8s.io` | tokenreviews | create | Authenticate agent connections |
| `coordination.k8s.io` | leases | create, get, update | Leader election |
| `apiextensions.k8s.io` | customresourcedefinitions | get, list, watch | CRD discovery |

#### 2. Enterprise API ClusterRole (`enterprise-agentgateway-api-default`)

| API Group | Resources | Verbs | Purpose |
|-----------|-----------|-------|---------|
| `enterpriseagentgateway.solo.io` | enterpriseagentgatewayparameters, enterpriseagentgatewaypolicies | get, list, update, watch | Enterprise feature configuration |
| `enterpriseagentgateway.solo.io` | */status | get, patch, update | Status updates |

---

## Why Cluster-Wide Permissions Are Required

The broad permissions are architecturally necessary due to the Kubernetes Gateway API design:

### 1. GatewayClass is Cluster-Scoped
The Gateway API specification defines `GatewayClass` as a cluster-scoped resource. The controller must be able to watch and manage these resources cluster-wide.

### 2. Cross-Namespace Routing
Gateways can reference `HTTPRoutes`, `Services`, and backends in different namespaces. The controller needs visibility across namespaces to resolve these references.

### 3. Dynamic Data Plane Provisioning
When a `Gateway` resource is created, the controller dynamically provisions:
- A Deployment for the data plane (Envoy proxy)
- A Service to expose the Gateway
- A ServiceAccount for the data plane pods
- RBAC (Role/RoleBinding) for the data plane pods

### 4. Service Discovery
For routing traffic to backend services, the controller must watch `Services`, `Endpoints`, and `EndpointSlices` across namespaces.

### 5. TLS Certificate Management
Gateways reference `Secrets` containing TLS certificates, which may exist in different namespaces via `ReferenceGrant`.

---

## Available Mitigation Options

### 1: Namespace Discovery Selectors

While the ClusterRole permissions cannot be reduced, you can limit which namespaces AgentGateway actively monitors using `AgentGatewayParameters`. This provides operational scoping without breaking functionality.

#### Configuration Example

```yaml
apiVersion: agentgateway.dev/v1alpha1
kind: AgentGatewayParameters
metadata:
  name: restricted-namespace-params
  namespace: agentgateway-system
spec:
  kube:
    deployment:
      # Limit which namespaces the controller watches
      namespaceDiscoverySelectors:
        # Option A: Match by labels (OR logic between selectors)
        - matchLabels:
            agentgateway-enabled: "true"

        # Option B: Match by expressions
        - matchExpressions:
            - key: environment
              operator: In
              values:
                - production
                - staging

        # Option C: Combine labels and expressions (AND logic within selector)
        - matchLabels:
            team: platform
          matchExpressions:
            - key: criticality
              operator: NotIn
              values:
                - low
```

#### Applying to a Gateway

Reference the parameters in your `GatewayClass`:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: agentgateway
spec:
  controllerName: solo.io/agentgateway-controller
  parametersRef:
    group: agentgateway.dev
    kind: AgentGatewayParameters
    name: restricted-namespace-params
    namespace: agentgateway-system
```

#### Labeling Namespaces

Label the namespaces you want AgentGateway to monitor:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: my-application
  labels:
    agentgateway-enabled: "true"
    environment: production
```

---

## Security Considerations

### Permission Justification

| Permission | Security Concern | Justification |
|------------|------------------|---------------|
| `secrets` access | Sensitive data exposure | Required for TLS certificate management; controller only reads secrets referenced by Gateway resources |
| `rbac` permissions | Privilege escalation | Used only to create RBAC for data plane pods; controller cannot escalate beyond its own permissions |
| `serviceaccounts` | Identity management | Creates dedicated SAs for data plane pods with minimal permissions |
| Cluster-wide `watch` | Information disclosure | Necessary for cross-namespace routing; data is used only for routing decisions |

### Built-in Security Features

AgentGateway includes several security controls:

1. **Non-root containers**: Data plane pods run as non-root by default
2. **Read-only filesystem**: Containers use read-only root filesystems where possible
3. **Network policies**: Can be applied to restrict controller communication
4. **TLS encryption**: Supports TLS for xDS communication between controller and data plane

---

## Helm Values Reference

```yaml
# Full Helm values for security-conscious deployment
serviceAccount:
  # Set to false if using pre-created ServiceAccount
  create: true
  # Custom ServiceAccount name
  name: "enterprise-agentgateway"
  # Add annotations (e.g., for IAM roles)
  annotations: {}

# Pod security context
podSecurityContext:
  runAsNonRoot: true
  fsGroup: 65534
  seccompProfile:
    type: RuntimeDefault

# Container security context
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: 65534
  capabilities:
    drop:
      - ALL
```
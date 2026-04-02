apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
name: tracing-gemini
namespace: agentgateway-system
spec:
targetRefs:
- group: gateway.networking.k8s.io
kind: Gateway
name: agentgateway-route-gemini
frontend:
tracing:
backendRef:
    group: ""
    kind: Service
    name: solo-enterprise-telemetry-collector
    namespace: kagent
    port: 4317
protocol: GRPC
clientSampling: "true"
randomSampling: "true"
resources:
    - name: deployment.environment.name
    expression: '"production"'
    - name: service.version
    expression: '"test"'
attributes:
    add:
    - name: request
        expression: 'request.headers["x-header-tag"]'
    - name: host
        expression: 'request.host'
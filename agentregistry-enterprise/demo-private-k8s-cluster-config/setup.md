# Agentregistry Enterprise on Private EKS with GitLab CI/CD

This guide covers deploying Agentregistry Enterprise on a **private AWS EKS cluster** where the service is not directly exposed via a LoadBalancer. Instead, traffic is routed through an existing Istio Gateway backed by a Network Load Balancer (NLB). Agents and MCP servers are registered via `arctl` in GitLab CI/CD pipelines.

## Architecture

```
Internet
    |
  [ NLB ]
    |
  [ Istio Gateway ] (gateway.networking.k8s.io)
    |
  [ HTTPRoute ] ──> agentregistry-enterprise Service (ClusterIP)
                        ├── :8080  HTTP (UI + API)
                        ├── :21212 gRPC (Agent Gateway)
                        └── :31313 MCP server
```

The private EKS cluster has no public endpoint. All external traffic enters through the existing NLB -> Istio Gateway path. Agentregistry Enterprise runs as a ClusterIP service, and an HTTPRoute on the Istio Gateway routes traffic to it.

## Prerequisites

- A private AWS EKS cluster with `kubectl` access (via VPN, bastion, or SSM)
- Kubernetes Gateway API CRDs
- Istio installed with a `GatewayClass` named `istio`
- An existing Istio `Gateway` resource with an NLB-backed external listener, or permissions to create one
- `helm` v3 installed
- `arctl` enterprise CLI installed
- OIDC provider configured (Entra ID, Keycloak, Cognito, etc.)
- GitLab project with a runner that has network access to the private cluster

## 1. Install the Enterprise arctl CLI

```bash
curl -sSL https://storage.googleapis.com/agentregistry-enterprise/install.sh | ARCTL_VERSION=v2026.05.0 sh
export PATH=$HOME/.arctl/bin:$PATH
arctl version --json
```

## 2. EKS Prerequisites: EBS CSI Driver and StorageClass

The bundled PostgreSQL and ClickHouse require persistent volumes. EKS 1.27+ requires the **EBS CSI driver** — the legacy in-tree `gp2` provisioner no longer works. If your cluster already has a working CSI-backed default StorageClass, skip this step.

### Install the EBS CSI Driver

The EBS CSI controller needs IAM permissions. The recommended approach is **EKS Pod Identity** (avoids OIDC provider quota issues).

```bash
# Install the Pod Identity Agent addon
aws eks create-addon \
  --cluster-name <CLUSTER_NAME> \
  --addon-name eks-pod-identity-agent \
  --region <REGION>

# Create an IAM role for the EBS CSI driver with Pod Identity trust
cat > /tmp/ebs-csi-trust.json <<'TRUST'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "pods.eks.amazonaws.com"
      },
      "Action": [
        "sts:AssumeRole",
        "sts:TagSession"
      ]
    }
  ]
}
TRUST

aws iam create-role \
  --role-name <CLUSTER_NAME>-ebs-csi-role \
  --assume-role-policy-document file:///tmp/ebs-csi-trust.json

aws iam attach-role-policy \
  --role-name <CLUSTER_NAME>-ebs-csi-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy

# Get the role ARN
EBS_CSI_ROLE_ARN=$(aws iam get-role --role-name <CLUSTER_NAME>-ebs-csi-role --query "Role.Arn" --output text)

# Create the Pod Identity association
aws eks create-pod-identity-association \
  --cluster-name <CLUSTER_NAME> \
  --namespace kube-system \
  --service-account ebs-csi-controller-sa \
  --role-arn "$EBS_CSI_ROLE_ARN" \
  --region <REGION>

# Install the EBS CSI driver addon with the IAM role
aws eks create-addon \
  --cluster-name <CLUSTER_NAME> \
  --addon-name aws-ebs-csi-driver \
  --service-account-role-arn "$EBS_CSI_ROLE_ARN" \
  --region <REGION>
```

Wait for the addon to become `ACTIVE`:

```bash
aws eks describe-addon \
  --cluster-name <CLUSTER_NAME> \
  --addon-name aws-ebs-csi-driver \
  --region <REGION> \
  --query "addon.status" --output text
```

Verify the controller pods are running (all containers ready, no CrashLoopBackOff):

```bash
kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-ebs-csi-driver
```

### Create a Default StorageClass

```bash
kubectl apply -f - <<'EOF'
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
EOF

# Remove default annotation from the legacy gp2 class
kubectl annotate storageclass gp2 storageclass.kubernetes.io/is-default-class- 2>/dev/null || true
```

Verify:

```bash
kubectl get storageclass
```

You should see `gp3 (default)` using the `ebs.csi.aws.com` provisioner.

## 3. Create the Namespace

```bash
kubectl create namespace agentregistry-system
```

## 4. Prepare the Helm Values File

The key difference from a standard installation is `service.type: ClusterIP`. No LoadBalancer is created — routing is handled by the Istio Gateway.

Create the values file. **Do not commit this file** — it contains secrets.

```bash
cat > /tmp/are-values-private.yaml <<'EOF'
image:
  tag: v2026.05.0

# ClusterIP — no LoadBalancer. Traffic is routed through the Istio Gateway.
service:
  type: ClusterIP

# OIDC — configure for your identity provider
oidc:
  issuer: "<OIDC_ISSUER_URL>"
  clientId: "<OIDC_BACKEND_CLIENT_ID>"
  publicClientId: "<OIDC_UI_CLIENT_ID>"
  clientSecret: "<OIDC_CLIENT_SECRET>"
  roleClaim: "groups"
  superuserRole: "<ADMIN_GROUP_OR_ROLE>"
  insecureSkipVerify: false

# AWS credentials
aws:
  enabled: true
  accessKeyId: "<AWS_ACCESS_KEY_ID>"
  secretAccessKey: "<AWS_SECRET_ACCESS_KEY>"
  sessionToken: ""
  region: "us-east-1"

# Bundled PostgreSQL (dev/eval only — use RDS for production)
database:
  postgres:
    bundled:
      enabled: true

# ClickHouse (observability)
clickhouse:
  enabled: true

# OTel Collector
telemetry:
  enabled: true

extraEnvVars:
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://agentregistry-enterprise-telemetry-collector:4317"
  - name: OTEL_SERVICE_NAME
    value: "agentregistry-enterprise"
EOF
```

> **Production note**: On a private cluster, replace the bundled PostgreSQL with an RDS instance in the same VPC. Set `database.postgres.bundled.enabled: false` and `database.postgres.url` to the RDS connection string.

## 5. Install the Helm Chart

```bash
helm upgrade --install agentregistry-enterprise \
  oci://us-docker.pkg.dev/solo-public/agentregistry-enterprise/helm/agentregistry-enterprise \
  --version 2026.05.0 \
  --namespace agentregistry-system \
  -f /tmp/are-values-private.yaml \
  --wait --timeout 5m
```

## 6. Verify the ClusterIP Service

```bash
kubectl get svc agentregistry-enterprise -n agentregistry-system
```

Expected output — note `TYPE: ClusterIP` and no `EXTERNAL-IP`:

```
NAME                       TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)                      AGE
agentregistry-enterprise   ClusterIP   10.100.x.x     <none>        8080/TCP,21212/TCP,31313/TCP  1m
```

Check the pods:

```bash
kubectl get pods -n agentregistry-system
```

Check the logs:

```bash
kubectl logs -n agentregistry-system deployment/agentregistry-enterprise --tail=20
```

You should see `using OIDC authentication`, `HTTP server starting` on `:8080`, and `MCP HTTP server starting` on `:31313`.

## 7. Route Traffic Through the Istio Gateway

The Istio Gateway backed by the NLB is the single ingress point for the private cluster. Create an HTTPRoute to route external traffic to the AgentRegistry Enterprise ClusterIP service.

### Option A: Add to an Existing Istio Gateway

If you already have an Istio Gateway with an HTTPS listener (e.g., with an ACM certificate on the NLB), create an HTTPRoute that attaches to it:

```bash
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: agentregistry-route
  namespace: agentregistry-system
spec:
  parentRefs:
    - name: <EXISTING_GATEWAY_NAME>
      namespace: <EXISTING_GATEWAY_NAMESPACE>
      sectionName: https          # match the listener name on the existing gateway
  hostnames:
    - "agentregistry.internal.example.com"     # your private DNS hostname
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - group: ""
          kind: Service
          name: agentregistry-enterprise
          port: 8080
EOF
```

If the Gateway and the Service are in different namespaces, create a `ReferenceGrant`:

```bash
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-gateway-to-agentregistry
  namespace: agentregistry-system
spec:
  from:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
      namespace: <EXISTING_GATEWAY_NAMESPACE>
  to:
    - group: ""
      kind: Service
      name: agentregistry-enterprise
EOF
```

### Option B: Create a Dedicated Istio Gateway

If you want a separate listener for AgentRegistry, create a new Gateway. The Istio controller will provision a new NLB (or you can annotate it to share an existing one):

```bash
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: agentregistry-gateway
  namespace: agentregistry-system
  annotations:
    # Internal NLB — only reachable from within the VPC
    service.beta.kubernetes.io/aws-load-balancer-scheme: "internal"
    service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
spec:
  gatewayClassName: istio
  listeners:
    - name: http
      port: 80
      protocol: HTTP
      allowedRoutes:
        namespaces:
          from: Same
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: agentregistry-route
  namespace: agentregistry-system
spec:
  parentRefs:
    - name: agentregistry-gateway
      namespace: agentregistry-system
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - group: ""
          kind: Service
          name: agentregistry-enterprise
          port: 8080
EOF
```

### Get the Gateway Address

```bash
export AR_ENDPOINT=$(kubectl get gateway <GATEWAY_NAME> -n <GATEWAY_NAMESPACE> \
  -o jsonpath='{.status.addresses[0].value}')
echo "AgentRegistry endpoint: http://$AR_ENDPOINT"
```

For a private NLB, this will be an internal DNS name (e.g., `internal-xxxx.elb.us-east-1.amazonaws.com`) reachable only from within the VPC.

### Verify

```bash
# From within the VPC (bastion, VPN, or SSM)
curl -s "http://$AR_ENDPOINT/v0/version" | python3 -m json.tool
curl -s -o /dev/null -w "%{http_code}" "http://$AR_ENDPOINT/healthz"
```

## 8. Access the UI and API from Your Laptop

The internal NLB is only reachable from within the VPC. To access AgentRegistry from your laptop, use `kubectl port-forward` to tunnel through the EKS API server.

### Port-Forward the Service Directly

```bash
kubectl -n agentregistry-system port-forward svc/agentregistry-enterprise 8080:8080
```

Then open:
- **UI**: http://localhost:8080
- **API docs**: http://localhost:8080/docs
- **Health**: http://localhost:8080/healthz

### Port-Forward Through the Istio Gateway

Alternatively, forward through the gateway service to test the full routing path:

```bash
kubectl -n agentregistry-system port-forward svc/agentregistry-gateway-istio 8080:80
```

Then open:
- **UI**: http://localhost:8080

> **Note**: The port-forward runs as long as the terminal session is open. For persistent access, set up a VPN (AWS Client VPN or WireGuard) or a bastion host within the VPC.

## 9. Configure DNS (Optional)

For a clean endpoint, create a Route 53 private hosted zone record pointing to the NLB:

```bash
# Example: agentregistry.internal.example.com -> NLB DNS name
aws route53 change-resource-record-sets \
  --hosted-zone-id <PRIVATE_HOSTED_ZONE_ID> \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "agentregistry.internal.example.com",
        "Type": "CNAME",
        "TTL": 300,
        "ResourceRecords": [{"Value": "'$AR_ENDPOINT'"}]
      }
    }]
  }'
```

## 10. Authenticate the arctl CLI

From a machine with VPC access (bastion, VPN, or the GitLab runner):

```bash
export ARCTL_API_BASE_URL=http://$AR_ENDPOINT
arctl version --json
```

Authenticate (method depends on your OIDC provider):

```bash
# For Keycloak or providers that support device-code without explicit scope:
arctl user login \
  --oidc-issuer-url "<OIDC_ISSUER_URL>" \
  --oidc-client-id "<OIDC_CLI_CLIENT_ID>"

# For Entra ID (requires manual device-code flow — see setup-entra.md):
# Use the manual flow to obtain ARCTL_API_TOKEN, then:
export ARCTL_API_TOKEN="<token>"
```

Verify:

```bash
arctl get providers
arctl get agents
```

---

## GitLab CI/CD Pipeline: Register Agents and MCP Servers

In a private cluster, the GitLab runner must have network access to both the EKS API server and the AgentRegistry endpoint (via VPN, VPC peering, or a runner deployed inside the VPC).

### Pipeline Variables

Set these in **GitLab > Settings > CI/CD > Variables** (masked and protected):

| Variable | Description |
|----------|-------------|
| `ARCTL_API_BASE_URL` | AgentRegistry endpoint (e.g., `http://agentregistry.internal.example.com`) |
| `ARCTL_API_TOKEN` | Bearer token for `arctl` authentication |
| `AWS_ACCESS_KEY_ID` | AWS credentials for `kubectl` EKS access |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key |
| `AWS_DEFAULT_REGION` | AWS region (e.g., `us-east-1`) |
| `EKS_CLUSTER_NAME` | EKS cluster name |
| `KUBECONFIG_B64` | (Alternative) Base64-encoded kubeconfig if not using `aws eks` |

### `.gitlab-ci.yml`

```yaml
stages:
  - setup
  - deploy-gateway
  - register

variables:
  ARCTL_VERSION: "v2026.05.0"

# ------------------------------------------------------------------
# Stage 1: Install tools (arctl, kubectl, awscli)
# ------------------------------------------------------------------
install-tools:
  stage: setup
  image: alpine:3.21
  script:
    - apk add --no-cache curl bash python3
    # Install arctl
    - curl -sSL https://storage.googleapis.com/agentregistry-enterprise/install.sh | ARCTL_VERSION=$ARCTL_VERSION sh
    - export PATH=$HOME/.arctl/bin:$PATH
    - arctl version --json
    # Install kubectl
    - curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
    - chmod +x kubectl && mv kubectl /usr/local/bin/
    - kubectl version --client
  artifacts:
    paths:
      - $HOME/.arctl/bin/arctl

# ------------------------------------------------------------------
# Stage 2: Deploy MCP Gateway + Backend + Route on the cluster
# ------------------------------------------------------------------
deploy-mcp-gateway:
  stage: deploy-gateway
  image: alpine:3.21
  before_script:
    - apk add --no-cache curl bash python3
    - curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
    - chmod +x kubectl && mv kubectl /usr/local/bin/
    # Configure kubectl for private EKS
    - curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscli.zip
    - python3 -m zipfile -e awscli.zip /tmp/awscli && /tmp/awscli/aws/install
    - aws eks update-kubeconfig --name $EKS_CLUSTER_NAME --region $AWS_DEFAULT_REGION
  script:
    - |
      kubectl apply -f - <<EOF
      apiVersion: gateway.networking.k8s.io/v1
      kind: Gateway
      metadata:
        name: mcp-gateway
        namespace: agentgateway-system
        labels:
          app: github-mcp-server
      spec:
        gatewayClassName: istio
        listeners:
          - name: mcp
            port: 3000
            protocol: HTTP
            allowedRoutes:
              namespaces:
                from: Same
      ---
      apiVersion: v1
      kind: Secret
      metadata:
        name: github-pat
        namespace: agentgateway-system
      type: Opaque
      stringData:
        Authorization: "Bearer ${GITHUB_PAT}"
      ---
      apiVersion: agentgateway.dev/v1alpha1
      kind: AgentgatewayBackend
      metadata:
        name: github-mcp-server
        namespace: agentgateway-system
      spec:
        mcp:
          targets:
            - name: github-copilot
              static:
                host: api.githubcopilot.com
                port: 443
                path: /mcp/
                protocol: StreamableHTTP
                policies:
                  tls: {}
                  auth:
                    secretRef:
                      name: github-pat
      ---
      apiVersion: gateway.networking.k8s.io/v1
      kind: HTTPRoute
      metadata:
        name: mcp-route
        namespace: agentgateway-system
        labels:
          app: github-mcp-server
      spec:
        parentRefs:
          - name: mcp-gateway
        rules:
          - matches:
              - path:
                  type: PathPrefix
                  value: /mcp
            backendRefs:
              - name: github-mcp-server
                namespace: agentgateway-system
                group: agentgateway.dev
                kind: AgentgatewayBackend
      EOF
    # Wait for the gateway to be ready and capture the internal endpoint
    - sleep 10
    - export GATEWAY_IP=$(kubectl get svc mcp-gateway -n agentgateway-system -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
    - echo "GATEWAY_IP=$GATEWAY_IP" >> deploy.env
    - echo "MCP Gateway endpoint:$GATEWAY_IP"
  artifacts:
    reports:
      dotenv: deploy.env

# ------------------------------------------------------------------
# Stage 3: Register the MCP Server and Agent in AgentRegistry
# ------------------------------------------------------------------
register-agent:
  stage: register
  image: alpine:3.21
  dependencies:
    - deploy-mcp-gateway
  before_script:
    - apk add --no-cache curl bash
    - curl -sSL https://storage.googleapis.com/agentregistry-enterprise/install.sh | ARCTL_VERSION=$ARCTL_VERSION sh
    - export PATH=$HOME/.arctl/bin:$PATH
  script:
    # Register the remote MCP server in AgentRegistry
    - |
      arctl apply -f - <<EOF
      apiVersion: ar.dev/v1alpha1
      kind: RemoteMCPServer
      metadata:
        name: github/copilot-mcp-server
        version: "0.1.0"
      spec:
        title: github-copilot
        description: Remote MCP server exposing GitHub tools via agentgateway.
        remote:
          type: streamable-http
          url: http://$GATEWAY_IP:3000/mcp
      EOF
    # Register the agent with the MCP server attached
    - |
      arctl apply -f - <<EOF
      apiVersion: ar.dev/v1alpha1
      kind: Agent
      metadata:
        name: demochatbot
        version: "1.0.4"
      spec:
        description: "A deterministic A2A/ADK-compatible chatbot for AWS Bedrock AgentCore"
        source:
          repository:
            url: "https://github.com/AdminTurnedDevOps/agentic-demo-repo"
            subfolder: "agentregistry-enterprise/demochatbot-a2a"
        mcpServers:
          - kind: RemoteMCPServer
            name: github/copilot-mcp-server
            version: "0.1.0"
      EOF
    # Deploy the agent to AWS Bedrock AgentCore
    - |
      arctl apply -f - <<EOF
      apiVersion: ar.dev/v1alpha1
      kind: Deployment
      metadata:
        name: demochatbot
      spec:
        providerRef:
          kind: Provider
          name: AWS
        targetRef:
          kind: Agent
          name: demochatbot
          version: "1.0.4"
      EOF
    # Verify
    - arctl get agents
    - arctl get mcps
    - arctl get deployments
```

### Pipeline Variables Reference

The `arctl` commands in the `register-agent` stage authenticate via `ARCTL_API_TOKEN` (set as a CI/CD variable). The commands are identical to the GitHub Actions workflow — only the CI/CD syntax differs.

| GitHub Actions | GitLab CI/CD |
|----------------|-------------|
| `${{ secrets.ARCTL_API_TOKEN }}` | `$ARCTL_API_TOKEN` (CI/CD variable) |
| `${{ secrets.GITHUB_PAT }}` | `$GITHUB_PAT` (CI/CD variable) |
| `runs-on: ubuntu-latest` | `image: alpine:3.21` |
| `uses: actions/checkout@v3` | Built-in checkout |
| Separate `run:` steps | `script:` block |
| `env:` at job level | `variables:` at job or pipeline level |

### GitLab Runner Networking

For a private EKS cluster, the GitLab runner must be able to reach:

1. **The EKS API server** — for `kubectl` commands. Options:
   - Deploy the runner inside the VPC (recommended)
   - Use AWS SSM or VPN from an external runner
   - Use `KUBECONFIG_B64` with a kubeconfig that goes through a bastion proxy

2. **The AgentRegistry endpoint** — for `arctl` commands. Since the AgentRegistry service is exposed via an internal NLB, the runner must be in the same VPC or a peered VPC.

3. **External registries** — `us-docker.pkg.dev` (Helm chart OCI), `storage.googleapis.com` (arctl CLI download). Ensure the VPC has a NAT gateway or VPC endpoints for these.

A typical setup is a GitLab runner deployed as a Kubernetes pod in the same EKS cluster, or as an EC2 instance in the same VPC:

```bash
# Example: Install GitLab Runner in the EKS cluster
helm repo add gitlab https://charts.gitlab.io
helm install gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab-runner --create-namespace \
  --set gitlabUrl="https://gitlab.example.com" \
  --set runnerToken="<RUNNER_TOKEN>" \
  --set runners.executor="kubernetes" \
  --set runners.kubernetes.namespace="gitlab-runner"
```

## Cleanup

```bash
# Remove the HTTPRoute and Gateway
kubectl delete httproute agentregistry-route -n agentregistry-system
kubectl delete gateway agentregistry-gateway -n agentregistry-system 2>/dev/null

# Remove the Helm release
helm uninstall agentregistry-enterprise -n agentregistry-system

# Delete the namespace
kubectl delete namespace agentregistry-system

# Remove MCP gateway resources
kubectl delete httproute mcp-route -n agentgateway-system
kubectl delete agentgatewaybackend github-mcp-server -n agentgateway-system
kubectl delete secret github-pat -n agentgateway-system
kubectl delete gateway mcp-gateway -n agentgateway-system
```

## Reference

| Component | Value |
|-----------|-------|
| Chart | `oci://us-docker.pkg.dev/solo-public/agentregistry-enterprise/helm/agentregistry-enterprise` |
| Chart Version | `2026.05.0` |
| Service Type | `ClusterIP` (no LoadBalancer) |
| HTTP Port | 8080 |
| gRPC Port | 21212 |
| MCP Port | 31313 |
| Routing | Istio Gateway (GatewayClass `istio`) -> HTTPRoute -> ClusterIP Service |
| NLB | AWS internal NLB provisioned by Istio Gateway controller |
| CLI Install | `curl -sSL https://storage.googleapis.com/agentregistry-enterprise/install.sh \| ARCTL_VERSION=v2026.05.0 sh` |
| GitLab Runner | Must be in the same VPC or peered VPC as the EKS cluster |

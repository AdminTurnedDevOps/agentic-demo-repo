# GKE OIDC Authentication with Keycloak

This guide covers setting up Keycloak as an OIDC provider for GKE authentication using GKE Identity Service.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Authentication Flow                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   User                                                               │
│     │                                                                │
│     ▼                                                                │
│   gcloud anthos auth login                                           │
│     │                                                                │
│     ▼                                                                │
│   Browser → Keycloak (authenticate) → OIDC Token                     │
│     │                                                                │
│     ▼                                                                │
│   kubeconfig updated with token                                      │
│     │                                                                │
│     ▼                                                                │
│   kubectl → GKE API Server → Identity Service validates token        │
│     │                                                                │
│     ▼                                                                │
│   RBAC authorization (based on user/group claims)                    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- GKE cluster (Standard or Enterprise)
- `gcloud` CLI installed and configured
- Cluster admin permissions

The `gcloud` CLI is required because `gcloud anthos auth login` handles the OIDC authentication flow. It opens your browser to Keycloak, receives the tokens, and updates your kubeconfig automatically.

### Provider Compatibility

This guide uses GKE Identity Service, which is GKE-specific. Here's how OIDC authentication options vary by provider:

| Approach | GKE | EKS | AKS | Self-managed |
|----------|-----|-----|-----|--------------|
| `gcloud anthos auth login` | ✅ | ❌ | ❌ | ❌ |
| Native OIDC flags | ❌ (managed) | ✅ | ❌ | ✅ |
| kubelogin (kubectl plugin) | ✅ | ✅ | ✅ | ✅ |
| Pinniped | ✅ | ✅ | ✅ | ✅

### Cross-Provider Alternative

If you need a solution that works across multiple Kubernetes providers:

- **kubelogin (kubectl-oidc-login)**: A kubectl plugin that handles OIDC auth. Works with any cluster that has OIDC configured on the API server. Requires API server OIDC configuration (EKS supports this natively, GKE/AKS don't).

- **Pinniped**: Works on any cluster regardless of API server access. Uses an impersonation pattern so it doesn't need API server OIDC flags. Installs in-cluster and provides a consistent user experience across all providers.

## Part 1: Install Keycloak in GKE

### 1.1 Create Namespace

```bash
kubectl create namespace keycloak
```

### 1.2 Add Helm Repository

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update
```

### 1.3 Create Keycloak Values File

Create a file named `keycloak-values.yaml`:

```yaml
# keycloak-values.yaml
auth:
  adminUser: admin
  adminPassword: "Password12!@"

production: false
proxy: edge

postgresql:
  enabled: true
  auth:
    postgresPassword: "Password12!@"
    password: "Password12!@"

service:
  type: LoadBalancer

resources:
  requests:
    memory: 512Mi
    cpu: 250m
  limits:
    memory: 1Gi
    cpu: 1000m
```

### 1.4 Install Keycloak

```bash
helm install keycloak bitnami/keycloak \
  --namespace keycloak \
  --values keycloak-values.yaml \
  --wait
```

### 1.5 Verify Installation

```bash
# Check pods
kubectl get pods -n keycloak

# Get the LoadBalancer external IP (may take a few minutes)
kubectl get svc keycloak -n keycloak

# Save the IP for later use
export KEYCLOAK_IP=$(kubectl get svc keycloak -n keycloak -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "Keycloak is available at: http://${KEYCLOAK_IP}"
```

## Part 2: Configure Keycloak for GKE

### 2.1 Access Keycloak Admin Console

1. Navigate to `http://<KEYCLOAK_IP>` (the LoadBalancer IP from step 1.5)
2. Click "Administration Console"
3. Login with the admin credentials from `keycloak-values.yaml`

### 2.2 Create a Realm

1. Hover over "master" dropdown in top-left
2. Click "Create Realm"
3. Set:
   - Realm name: `gke`
4. Click "Create"

### 2.3 Create Groups

1. In the `gke` realm, go to **Groups** (left sidebar)
2. Click "Create group"
3. Create the following groups:
   - `k8s-admins` (for cluster-admin access)
   - `k8s-developers` (for developer access)
   - `k8s-viewers` (for read-only access)

### 2.4 Create Users

1. Go to **Users** (left sidebar)
2. Click "Add user"
3. Set:
   - Username: `testuser`
   - Email: `testuser@example.com`
   - Email verified: ON
   - First name: `Test`
   - Last name: `User`
4. Click "Create"
5. Go to **Credentials** tab:
   - Click "Set password"
   - Set a password
   - Temporary: OFF
6. Go to **Groups** tab:
   - Click "Join Group"
   - Select `k8s-admins`

### 2.5 Create Client for GKE

1. Go to **Clients** (left sidebar)
2. Click "Create client"
3. **General Settings**:
   - Client type: OpenID Connect
   - Client ID: `gke-cluster`
   - Click "Next"
4. **Capability config**:
   - Client authentication: ON
   - Authorization: OFF
   - Authentication flow: Check "Standard flow" only
   - Click "Next"
5. **Login settings**:
   - Valid redirect URIs: `http://localhost:8000/callback`
   - Click "Save"

### 2.6 Get Client Secret

1. In the `gke-cluster` client, go to **Credentials** tab
2. Copy the "Client secret" - you'll need this later

### 2.7 Configure Group Mapper

By default, Keycloak doesn't include groups in tokens. You need to add a mapper:

1. In the `gke-cluster` client, go to **Client scopes** tab
2. Click `gke-cluster-dedicated`
3. Click "Add mapper" → "By configuration"
4. Select "Group Membership"
5. Configure:
   - Name: `groups`
   - Token Claim Name: `groups`
   - Full group path: OFF
   - Add to ID token: ON
   - Add to access token: ON
   - Add to userinfo: ON
6. Click "Save"

### 2.8 Verify OIDC Endpoints

Your OIDC issuer URL is:
```
http://<KEYCLOAK_IP>/realms/gke
```

You can verify the configuration at:
```
http://<KEYCLOAK_IP>/realms/gke/.well-known/openid-configuration
```

## Part 3: Enable GKE Identity Service

### 3.1 Enable Identity Service on Cluster

```bash
# Replace with your cluster name and region/zone
CLUSTER_NAME="your-cluster-name"
REGION="us-central1"  # or use --zone for zonal clusters

gcloud container clusters update ${CLUSTER_NAME} \
  --enable-identity-service \
  --region=${REGION}
```

This may take a few minutes. You can verify:

```bash
gcloud container clusters describe ${CLUSTER_NAME} \
  --region=${REGION} \
  --format="value(identityServiceConfig.enabled)"
```

### 3.2 Create ClientConfig for Keycloak

Create a file named `client-config.yaml`:

```yaml
# client-config.yaml
apiVersion: authentication.gke.io/v2alpha1
kind: ClientConfig
metadata:
  name: default
  namespace: kube-public
spec:
  authentication:
    - name: keycloak
      oidc:
        clientID: gke-cluster
        clientSecret: YOUR_CLIENT_SECRET_HERE  # From step 2.6
        issuerURI: http://<KEYCLOAK_IP>/realms/gke
        kubectlRedirectURI: http://localhost:8000/callback
        scopes: openid,email,groups
        userClaim: email
        groupsClaim: groups
        userPrefix: ""
        groupPrefix: ""
```

Apply the configuration:

```bash
kubectl apply -f client-config.yaml
```

### 3.3 Verify ClientConfig

```bash
kubectl get clientconfig default -n kube-public -o yaml
```

## Part 4: Configure RBAC

### 4.1 Cluster Admin Binding (k8s-admins group)

```yaml
# rbac-admins.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: keycloak-cluster-admins
subjects:
  - kind: Group
    name: k8s-admins
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: cluster-admin
  apiGroup: rbac.authorization.k8s.io
```

```bash
kubectl apply -f rbac-admins.yaml
```

### 4.2 Developer Binding (k8s-developers group)

```yaml
# rbac-developers.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: keycloak-developers
subjects:
  - kind: Group
    name: k8s-developers
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: edit
  apiGroup: rbac.authorization.k8s.io
```

```bash
kubectl apply -f rbac-developers.yaml
```

### 4.3 Viewer Binding (k8s-viewers group)

```yaml
# rbac-viewers.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: keycloak-viewers
subjects:
  - kind: Group
    name: k8s-viewers
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: view
  apiGroup: rbac.authorization.k8s.io
```

```bash
kubectl apply -f rbac-viewers.yaml
```

## Part 5: User Authentication

### 5.1 Generate Login Config File

First, get the login configuration file from your cluster:

```bash
# Get the cluster's login config
gcloud container clusters describe ${CLUSTER_NAME} \
  --region=${REGION} \
  --format="value(masterAuth.clusterCaCertificate)" | base64 -d > ca.crt

# Get the cluster endpoint
CLUSTER_ENDPOINT=$(gcloud container clusters describe ${CLUSTER_NAME} \
  --region=${REGION} \
  --format="value(endpoint)")
```

Create a login config file `login-config.yaml`:

```yaml
# login-config.yaml
apiVersion: authentication.gke.io/v2alpha1
kind: ClientConfig
metadata:
  name: default
spec:
  name: gke-cluster
  server: https://CLUSTER_ENDPOINT  # Replace with actual endpoint
  certificateAuthorityData: BASE64_CA_CERT  # Replace with base64 CA cert
  authentication:
    - name: keycloak
      oidc:
        clientID: gke-cluster
        clientSecret: YOUR_CLIENT_SECRET
        issuerURI: http://<KEYCLOAK_IP>/realms/gke
        kubectlRedirectURI: http://localhost:8000/callback
        scopes: openid,email,groups
        userClaim: email
        groupsClaim: groups
```

Or download it directly:

```bash
gcloud container clusters get-credentials ${CLUSTER_NAME} \
  --region=${REGION}

kubectl get clientconfig default -n kube-public -o yaml > login-config.yaml
```

### 5.2 Authenticate with Keycloak

```bash
# Login via OIDC
gcloud anthos auth login \
  --cluster=${CLUSTER_NAME} \
  --login-config=login-config.yaml \
  --preferred-auth=keycloak
```

This will:
1. Open your browser to Keycloak login page
2. After authentication, redirect back with tokens
3. Update your kubeconfig with the OIDC credentials

### 5.3 Verify Authentication

```bash
# Check your identity
kubectl auth whoami

# Test access
kubectl get pods --all-namespaces
```

## Part 6: Troubleshooting

### 6.1 Check Identity Service Logs

```bash
kubectl logs -n anthos-identity-service -l app=ais --tail=100
```

### 6.2 Verify Token Claims

You can decode your token to verify claims:

```bash
# Get the token from kubeconfig
TOKEN=$(kubectl config view --raw -o jsonpath='{.users[?(@.name=="keycloak")].user.auth-provider.config.id-token}')

# Decode (requires jq)
echo $TOKEN | cut -d'.' -f2 | base64 -d 2>/dev/null | jq .
```

Expected output should include:
```json
{
  "email": "testuser@example.com",
  "groups": ["k8s-admins"],
  ...
}
```

## Quick Reference

| Component | URL/Value |
|-----------|-----------|
| Keycloak Admin | `http://<KEYCLOAK_IP>` |
| OIDC Issuer | `http://<KEYCLOAK_IP>/realms/gke` |
| Discovery | `http://<KEYCLOAK_IP>/realms/gke/.well-known/openid-configuration` |
| Client ID | `gke-cluster` |
| Redirect URI | `http://localhost:8000/callback` |
| User Claim | `email` |
| Groups Claim | `groups` |

## Files Created

After following this guide, you should have:

```
├── keycloak-values.yaml        # Helm values for Keycloak
├── client-config.yaml          # GKE Identity Service config
├── rbac-admins.yaml            # Admin RBAC binding
├── rbac-developers.yaml        # Developer RBAC binding
├── rbac-viewers.yaml           # Viewer RBAC binding
└── login-config.yaml           # User login configuration
```

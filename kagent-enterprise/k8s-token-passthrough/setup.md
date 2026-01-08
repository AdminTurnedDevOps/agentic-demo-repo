# Kubernetes OIDC Authentication with Keycloak and Pinniped

This guide covers setting up Keycloak as an OIDC provider for Kubernetes authentication using Pinniped. This approach works on any Kubernetes cluster (GKE, EKS, AKS, self-managed).

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Authentication Flow                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   User                                                               │
│     │                                                                │
│     ▼                                                                │
│   pinniped get kubeconfig                                            │
│     │                                                                │
│     ▼                                                                │
│   kubectl (with Pinniped credential plugin)                          │
│     │                                                                │
│     ▼                                                                │
│   Browser → Keycloak (authenticate) → OIDC Token                     │
│     │                                                                │
│     ▼                                                                │
│   Pinniped Concierge validates token → impersonates user             │
│     │                                                                │
│     ▼                                                                │
│   Kubernetes API Server → RBAC authorization                         │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- Kubernetes cluster (GKE, EKS, AKS, or self-managed)
- `kubectl` installed and configured with cluster-admin access
- `helm` installed (v3+)

## Part 1: Install Keycloak

### 1.1 Create Namespace

```bash
kubectl create namespace keycloak
```

### 1.2 Generate TLS Certificate

Pinniped requires HTTPS for the OIDC issuer. Generate a self-signed certificate:

```bash
# First, get the LoadBalancer IP (run after deploying Keycloak, or use a placeholder and regenerate later)
# export KEYCLOAK_IP=<your-loadbalancer-ip>

# Generate CA and certificate (include the IP in SANs for Pinniped to validate)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout keycloak-tls.key \
  -out keycloak-tls.crt \
  -subj "/CN=keycloak" \
  -addext "subjectAltName=DNS:keycloak,DNS:keycloak.keycloak.svc.cluster.local,IP:${KEYCLOAK_IP}"

# Create Kubernetes secret
kubectl create secret tls keycloak-tls \
  --cert=keycloak-tls.crt \
  --key=keycloak-tls.key \
  -n keycloak

# Save the CA for later use with Pinniped
export KEYCLOAK_CA_BASE64=$(cat keycloak-tls.crt | base64 | tr -d '\n')
```

### 1.3 Deploy Keycloak

```bash
kubectl apply -f -<<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: keycloak-data
  namespace: keycloak
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: keycloak
  namespace: keycloak
spec:
  replicas: 1
  selector:
    matchLabels:
      app: keycloak
  template:
    metadata:
      labels:
        app: keycloak
    spec:
      initContainers:
        - name: fix-permissions
          image: busybox
          command: ['sh', '-c', 'chown -R 1000:1000 /data']
          volumeMounts:
            - name: data
              mountPath: /data
      containers:
        - name: keycloak
          image: quay.io/keycloak/keycloak:26.0
          args: ["start-dev"]
          env:
            - name: KEYCLOAK_ADMIN
              value: "admin"
            - name: KEYCLOAK_ADMIN_PASSWORD
              value: "Password12!@"
            - name: KC_HTTPS_CERTIFICATE_FILE
              value: "/etc/keycloak/tls/tls.crt"
            - name: KC_HTTPS_CERTIFICATE_KEY_FILE
              value: "/etc/keycloak/tls/tls.key"
            - name: KC_HOSTNAME_STRICT
              value: "false"
          ports:
            - containerPort: 8443
          volumeMounts:
            - name: tls
              mountPath: /etc/keycloak/tls
              readOnly: true
            - name: data
              mountPath: /opt/keycloak/data
          resources:
            requests:
              memory: 512Mi
              cpu: 250m
            limits:
              memory: 1Gi
              cpu: 1000m
      volumes:
        - name: tls
          secret:
            secretName: keycloak-tls
        - name: data
          persistentVolumeClaim:
            claimName: keycloak-data
---
apiVersion: v1
kind: Service
metadata:
  name: keycloak
  namespace: keycloak
spec:
  type: LoadBalancer
  selector:
    app: keycloak
  ports:
    - port: 443
      targetPort: 8443
EOF
```

### 1.4 Verify Installation

```bash
# Check pods
kubectl get pods -n keycloak --watch

# Get the LoadBalancer external IP (may take a few minutes)
kubectl get svc keycloak -n keycloak

# Save the IP for later use
export KEYCLOAK_IP=$(kubectl get svc keycloak -n keycloak -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "Keycloak is available at: https://${KEYCLOAK_IP}"
```

## Part 2: Configure Keycloak

### 2.1 Access Keycloak Admin Console

1. Navigate to `https://<KEYCLOAK_IP>` (the LoadBalancer IP from step 1.4, accept the self-signed cert warning)
2. Click "Administration Console"
3. Login with admin / Password12!@

### 2.2 Create a Realm

1. Hover over "master" dropdown in top-left
2. Click "Create Realm"
3. Set:
   - Realm name: `kubernetes`
4. Click "Create"

### 2.3 Create Groups

1. In the `kubernetes` realm, go to **Groups** (left sidebar)
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
   - Set the password to `Password123`
   - Temporary: OFF
6. Go to **Groups** tab:
   - Click "Join Group"
   - Select `k8s-admins`

### 2.5 Create Client for Pinniped

1. Go to **Clients** (left sidebar)
2. Click "Create client"
3. **General Settings**:
   - Client type: OpenID Connect
   - Client ID: `pinniped-cli`
   - Click "Next"
4. **Capability config**:
   - Client authentication: OFF (public client)
   - Authorization: OFF
   - Authentication flow: Check "Standard flow" and "Direct access grants"
   - Click "Next"
5. **Login settings**:
   - Valid redirect URIs: `http://127.0.0.1/callback`
   - Click "Save"

### 2.6 Configure Group Mapper

By default, Keycloak doesn't include groups in tokens. You need to add a mapper:

1. In the `pinniped-cli` client, go to **Client scopes** tab
2. Click `pinniped-cli-dedicated`
3. Click "Configure a new mapper"
4. Select "Group Membership"
5. Configure:
   - Name: `groups`
   - Token Claim Name: `groups`
   - Full group path: OFF
   - Add to ID token: ON
   - Add to access token: ON
   - Add to userinfo: ON
6. Click "Save"

### 2.7 Verify OIDC Endpoints

Your OIDC issuer URL is:
```
https://<KEYCLOAK_IP>/realms/kubernetes
```

You can verify the configuration at:
```
https://<KEYCLOAK_IP>/realms/kubernetes/.well-known/openid-configuration
```

## Part 3: Install Pinniped

Pinniped is an open-source authentication service for Kubernetes clusters. It allows you to use external identity providers (like Keycloak) without needing to configure the Kubernetes API server directly. Pinniped uses an impersonation pattern where its in-cluster component (Concierge) validates your OIDC token and then impersonates you when talking to the API server.

### 3.1 Install Pinniped Concierge

The Concierge runs in-cluster and handles token validation.

```
kubectl apply -f https://get.pinniped.dev/latest/install-pinniped-concierge.yaml
```

```
kubectl get pods -n pinniped-concierge
```

### 3.2 Configure JWT Authenticator

Create a JWTAuthenticator to tell Pinniped how to validate Keycloak tokens:

```bash
kubectl apply -f -<<EOF
apiVersion: authentication.concierge.pinniped.dev/v1alpha1
kind: JWTAuthenticator
metadata:
  name: keycloak
spec:
  issuer: https://${KEYCLOAK_IP}/realms/kubernetes
  audience: pinniped-cli
  claims:
    username: email
    groups: groups
  tls:
    certificateAuthorityData: ${KEYCLOAK_CA_BASE64}
EOF
```

### 3.3 Verify JWTAuthenticator

```bash
kubectl get jwtauthenticator keycloak -o yaml
```

The status should show the authenticator is ready.

## Part 4: Configure RBAC

### 4.1 Cluster Admin Binding (k8s-admins group)

```bash
kubectl apply -f -<<EOF
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
EOF
```

### 4.2 Developer Binding (k8s-developers group)

```bash
kubectl apply -f -<<EOF
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
EOF
```

### 4.3 Viewer Binding (k8s-viewers group)

```bash
kubectl apply -f -<<EOF
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
EOF
```

## Part 5: User Authentication

### 5.1 Install Pinniped CLI

```bash
# macOS
brew install vmware-tanzu/pinniped/pinniped-cli

# Linux
curl -L https://get.pinniped.dev/latest/pinniped-cli-linux-amd64 -o pinniped
chmod +x pinniped
sudo mv pinniped /usr/local/bin/
```

### 5.2 Generate Kubeconfig

Use the Pinniped CLI to generate a kubeconfig that uses OIDC authentication:

```bash
pinniped get kubeconfig \
  --oidc-issuer https://${KEYCLOAK_IP}/realms/kubernetes \
  --oidc-client-id pinniped-cli \
  --oidc-scopes openid,email,groups \
  --oidc-listen-port 12345 \
  --oidc-ca-bundle keycloak-tls.crt \
  > pinniped-kubeconfig.yaml
```

### 5.3 Authenticate with Keycloak

```bash
# Use the Pinniped kubeconfig
export KUBECONFIG=pinniped-kubeconfig.yaml

# Run any kubectl command - it will trigger browser authentication
kubectl get pods
```

This will:
1. Open your browser to Keycloak login page
2. After authentication, redirect back with tokens
3. Complete the kubectl command with your OIDC identity

### 5.4 Verify Authentication

```bash
# Check your identity
kubectl auth whoami

# Test access
kubectl get pods --all-namespaces
```

## Part 6: Troubleshooting

### 6.1 Check Pinniped Concierge Logs

```bash
kubectl logs -n pinniped-concierge -l app=concierge --tail=100
```

### 6.2 Check JWTAuthenticator Status

```bash
kubectl get jwtauthenticator keycloak -o jsonpath='{.status}' | jq .
```

### 6.3 Verify Token Claims

You can test getting a token directly from Keycloak:

```bash
curl -k -X POST "https://${KEYCLOAK_IP}/realms/kubernetes/protocol/openid-connect/token" \
  -d "client_id=pinniped-cli" \
  -d "grant_type=password" \
  -d "username=testuser" \
  -d "password=Password123" \
  -d "scope=openid email groups" | jq -r '.access_token' | cut -d'.' -f2 | base64 -d | jq .
```

Expected output should include:
```json
{
  "email": "testuser@example.com",
  "groups": ["k8s-admins"],
  ...
}
```

### 6.4 Common Issues

**Issue: "Unable to connect to issuer"**
- Verify Keycloak is accessible from the cluster
- Check the issuer URL in JWTAuthenticator matches exactly

**Issue: "Groups not appearing in token"**
- Verify the group mapper is configured in Keycloak
- Ensure "Add to ID token" is enabled

**Issue: "Unauthorized" after login**
- Verify RBAC bindings match the group names in Keycloak
- Check that the user is in the correct group

## Quick Reference

| Component | URL/Value |
|-----------|-----------|
| Keycloak Admin | `https://<KEYCLOAK_IP>` |
| OIDC Issuer | `https://<KEYCLOAK_IP>/realms/kubernetes` |
| Discovery | `https://<KEYCLOAK_IP>/realms/kubernetes/.well-known/openid-configuration` |
| Client ID | `pinniped-cli` |
| Username Claim | `email` |
| Groups Claim | `groups` |

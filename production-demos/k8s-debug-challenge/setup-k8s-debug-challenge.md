# E-Commerce Application - Kubernetes Debug Challenge

## Overview

This is a production-ready e-commerce application stack designed to run on Kubernetes. The application consists of three tiers:

- **Frontend**: Nginx-based web server serving static content and proxying API requests
- **Backend API**: Node.js API service handling business logic
- **Database**: PostgreSQL database for persistent storage

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Ingress                               │
│                    (ecommerce.local)                         │
└─────────────────────────┬───────────────────────────────────┘
                          │
           ┌──────────────┴──────────────┐
           │                             │
           ▼                             ▼
┌─────────────────────┐       ┌─────────────────────┐
│   Frontend Service  │       │   Backend Service   │
│     (port 80)       │       │    (port 8080)      │
└─────────┬───────────┘       └─────────┬───────────┘
          │                             │
          ▼                             ▼
┌─────────────────────┐       ┌─────────────────────┐
│  Frontend Pods (2)  │──────▶│  Backend Pods (2)   │
│   nginx:1.25-alpine │       │   node:18-alpine    │
└─────────────────────┘       └─────────┬───────────┘
                                        │
                                        ▼
                              ┌─────────────────────┐
                              │  PostgreSQL Service │
                              │     (port 5432)     │
                              └─────────┬───────────┘
                                        │
                                        ▼
                              ┌─────────────────────┐
                              │  PostgreSQL Pod     │
                              │  postgres:15-alpine │
                              └─────────────────────┘
```

## Deployment

### Prerequisites

- Kubernetes cluster (v1.25+)
- kubectl configured
- Storage class "standard" available
- NGINX Ingress Controller (optional, for ingress)

### Deploy the Application

```bash
# Using kustomize
kubectl apply -k .

# Or apply individual files
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml
kubectl apply -f secrets.yaml
kubectl apply -f rbac.yaml
kubectl apply -f database.yaml
kubectl apply -f backend.yaml
kubectl apply -f frontend.yaml
kubectl apply -f networkpolicy.yaml
kubectl apply -f ingress.yaml
kubectl apply -f hpa.yaml
```

### Verify Deployment

```bash
# Check all resources
kubectl get all -n ecommerce-app

# Check pod status
kubectl get pods -n ecommerce-app -w

# Check services
kubectl get svc -n ecommerce-app

# Check ingress
kubectl get ingress -n ecommerce-app
```

## Expected Behavior

Once deployed, you should be able to:

1. Access the frontend at `http://ecommerce.local` (requires ingress + hosts file entry)
2. The frontend should display a product listing page
3. API calls to `/api/products` should return product data from the backend
4. Backend should connect to PostgreSQL and retrieve/store data

```

## Configuration

| Component | Config Source | Description |
|-----------|--------------|-------------|
| Frontend | ConfigMap: nginx-config | Nginx configuration |
| Backend | ConfigMap: app-config | API configuration |
| Backend | Secret: api-secrets | JWT and API keys |
| Database | Secret: db-credentials | PostgreSQL credentials |

## Resource Allocation

| Component | CPU Request | CPU Limit | Memory Request | Memory Limit |
|-----------|-------------|-----------|----------------|--------------|
| Frontend | 50m | 100m | 64Mi | 128Mi |
| Backend | 100m | 200m | 128Mi | 64Mi |
| Database | 250m | 500m | 256Mi | 512Mi |

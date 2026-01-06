# Answer Key - Issues in the K8s Debug Challenge

**DO NOT SHARE THIS FILE WITH AI TOOLS BEING TESTED**

This document lists all the intentional issues embedded in this Kubernetes application stack.

---

## Issue #1: Database Service Name Mismatch

**Location**: `database.yaml` (Service) vs `backend.yaml` (init container)

**Problem**: The PostgreSQL service is named `postgres-db-svc`, but the backend init container tries to connect to `postgresql-svc`.

**Symptom**: Backend pods stuck in `Init:0/1` state. Init container logs show repeated "PostgreSQL is unavailable - sleeping" messages.

**Fix**: Either rename the service to `postgresql-svc` OR update the init container to use `postgres-db-svc`.

---

## Issue #2: Backend Service Selector Mismatch

**Location**: `backend.yaml` (Service selector vs Deployment labels)

**Problem**:
- Deployment pods have label `app: api-backend`
- Service selector looks for `app: backend-api`

**Symptom**: Running `kubectl get endpoints backend-service -n ecommerce-app` shows no endpoints. Traffic cannot reach backend pods.

**Fix**: Change the service selector from `app: backend-api` to `app: api-backend`.

---

## Issue #3: ConfigMap Key Name Mismatch

**Location**: `backend.yaml` (environment variables) vs `configmap.yaml`

**Problem**: Backend deployment references ConfigMap key `db_host`, but the ConfigMap defines `database_host`.

**Symptom**: Pod fails to start with `CreateContainerConfigError`. Describe pod shows: "Error: configmap key 'db_host' not found".

**Fix**: Change the configMapKeyRef from `db_host` to `database_host`.

---

## Issue #4: Readiness/Liveness Probe Port Mismatch

**Location**: `backend.yaml` (probes)

**Problem**: Both readiness and liveness probes check port `8080`, but the application listens on port `3000`.

**Symptom**: Pod starts but never becomes Ready. Eventually gets killed due to liveness probe failures. Events show "Readiness probe failed: connection refused".

**Fix**: Change probe ports from `8080` to `3000`.

---

## Issue #5: Frontend Init Container Cascading Failure

**Location**: `frontend.yaml` (init container)

**Problem**: Frontend init container waits for `backend-service:8080` to be available. Due to Issue #2 (service selector mismatch), the backend service has no endpoints.

**Symptom**: Frontend pods stuck in `Init:0/1` state. This is a cascading failure caused by Issue #2.

**Fix**: Fix Issue #2 first. Once the backend service has endpoints, the frontend init container will proceed.

---

## Debugging Flow

An AI agent debugging this would likely encounter issues in this order:

1. **First observation**: Pods are not running
   - `kubectl get pods -n ecommerce-app` shows pods in Init or Error states

2. **Issue #3 discovered**: Backend pod shows CreateContainerConfigError
   - `kubectl describe pod` reveals missing ConfigMap key
   - Fix: Update configMapKeyRef to `database_host`

3. **Issue #1 discovered**: Backend init container hangs
   - After fixing Issue #3, backend pod now stuck in Init:0/1
   - `kubectl logs <pod> -c wait-for-db` shows waiting for postgresql-svc
   - `kubectl get svc -n ecommerce-app` shows service is named `postgres-db-svc`
   - Fix: Update init container to use correct service name

4. **Issue #4 discovered**: Backend pod starts but never Ready
   - After fixing Issues #1 and #3, pod runs but readiness probe fails
   - `kubectl describe pod` shows probe failures on port 8080
   - Container listens on port 3000
   - Fix: Update probe ports to 3000

5. **Issue #2 discovered**: Service has no endpoints
   - `kubectl get endpoints` shows backend-service has no endpoints
   - Compare service selector with pod labels
   - Fix: Update service selector to match pod labels

6. **Issue #5 resolves automatically**: Frontend starts
   - Once backend service has endpoints, frontend init container succeeds

---

## Summary

| Issue | Type | Symptom |
|-------|------|---------|
| #1 | Service Discovery | Init container hangs waiting for wrong DNS name |
| #2 | Label Mismatch | Service selector doesn't match pod labels |
| #3 | ConfigMap Reference | Missing key causes container config error |
| #4 | Probe Misconfiguration | Wrong port causes readiness/liveness failures |
| #5 | Cascading Failure | Depends on Issue #2 being fixed |

An AI agent would need to trace through these issues systematically to fully diagnose and fix the deployment.

# Answer Key - Issues in the K8s Debug Challenge

**DO NOT SHARE THIS FILE WITH AI TOOLS BEING TESTED**

This document lists all the intentional issues embedded in this Kubernetes application stack.

---

## Issue #1: Database Service Name Mismatch

**Location**: `database.yaml` (Service) + `configmap.yaml` + `backend.yaml` (init container)

**Problem**: The PostgreSQL service is named `postgres-db-svc`, but other components reference `postgresql-svc`.

**Symptom**: Backend init container will hang forever waiting for `postgresql-svc` which doesn't exist.

**Fix**: Rename service to `postgresql-svc` OR update all references to use `postgres-db-svc`.

---

## Issue #2: Backend Service Selector Mismatch

**Location**: `backend.yaml` (Service selector vs Deployment labels)

**Problem**:
- Deployment pods have label `app: api-backend`
- Service selector looks for `app: backend-api`

**Symptom**: Service has no endpoints, traffic cannot reach backend pods.

**Fix**: Change service selector to `app: api-backend` OR change deployment labels to `app: backend-api`.

---

## Issue #3: Init Container DNS Resolution Failure

**Location**: `backend.yaml` (init container)

**Problem**: Init container uses `nc -z postgresql-svc 5432` but that service doesn't exist (see Issue #1).

**Symptom**: Init container stuck in `Init:0/1` state indefinitely.

**Fix**: Correct the service name to `postgres-db-svc`.

---

## Issue #4: ConfigMap Key Name Mismatch

**Location**: `backend.yaml` (environment variables) + `configmap.yaml`

**Problem**: Backend references ConfigMap key `db_host`, but ConfigMap has `database_host`.

**Symptom**: Pod will fail to start with `CreateContainerConfigError` - key not found in ConfigMap.

**Fix**: Change ConfigMap reference to `database_host` OR add `db_host` key to ConfigMap.

---

## Issue #5: Insufficient Memory Limits

**Location**: `backend.yaml` (resources)

**Problem**: Memory request is 128Mi but limit is only 64Mi (limit < request is invalid, and 64Mi is too low for Node.js anyway).

**Symptom**: Pod may fail validation or get OOMKilled immediately upon startup.

**Fix**: Set memory limit >= request, and increase to at least 256Mi for Node.js.

---

## Issue #6: Readiness/Liveness Probe Port Mismatch

**Location**: `backend.yaml` (probes)

**Problem**: Probes check port 8080, but the application listens on port 3000.

**Symptom**: Pod starts but never becomes Ready. Gets killed after liveness probe failures.

**Fix**: Change probe ports from 8080 to 3000.

---

## Issue #7: Duplicate of Issue #2

(Same service selector mismatch described above)

---

## Issue #8: Frontend Init Container Deadlock

**Location**: `frontend.yaml` (init container)

**Problem**: Frontend init container waits for `backend-service:8080` to be available, but backend service has no endpoints (due to Issue #2).

**Symptom**: Frontend pods stuck in `Init:0/1` state.

**Fix**: Fix the backend service selector issue first.

---

## Issue #9: RBAC Missing Verb

**Location**: `rbac.yaml` (Role)

**Problem**: Role only grants `list` verb for secrets, not `get`. Pod can list secrets but not read their values.

**Symptom**: If the application tries to read secrets via the API (not typical for env vars), it would fail.

**Impact**: Lower priority - doesn't affect basic deployment since env vars are injected by kubelet.

**Fix**: Add `get` to the verbs list for secrets.

---

## Issue #10: NetworkPolicy Selector Mismatch

**Location**: `networkpolicy.yaml` (backend policy)

**Problem**: NetworkPolicy podSelector uses `app: backend-api` but pods have `app: api-backend`.

**Symptom**: NetworkPolicy doesn't apply to backend pods (which is actually less restrictive, so traffic works).

**Impact**: Security gap - policy doesn't protect intended pods.

**Fix**: Change selector to `app: api-backend`.

---

## Issue #11: Database NetworkPolicy Selector Mismatch

**Location**: `networkpolicy.yaml` (database policy)

**Problem**: Database ingress rule requires `app: backend-api` AND `tier: backend`, but pods have `app: api-backend`.

**Symptom**: If NetworkPolicies are enforced, backend cannot connect to database.

**Fix**: Change to `app: api-backend`.

---

## Issue #12: PodDisruptionBudget Blocks Updates

**Location**: `hpa.yaml` (PDB)

**Problem**: `minAvailable: 2` equals the replica count (2), so rolling updates cannot proceed (can't terminate any pod).

**Symptom**: Deployments get stuck during rolling updates.

**Fix**: Set `minAvailable: 1` or use `maxUnavailable: 1` instead.

---

## Summary of Show-Stopping Issues

Issues that will prevent the application from starting:

1. **Issue #4** - ConfigMap key mismatch (CreateContainerConfigError)
2. **Issue #5** - Invalid resource spec (limit < request)
3. **Issue #1 + #3** - Backend init container hangs
4. **Issue #6** - Probes fail (pod never Ready)
5. **Issue #2** - Service has no endpoints
6. **Issue #8** - Frontend init container hangs

An AI agent would need to trace through these issues systematically to fully diagnose and fix the deployment.

# kagent Demo: Observability Agent + K8s Agent Working Together

## Overview
This demo showcases kagent out-of-the-box Agents working together to detect and resolve a real-world production issue.

- **Observability Agent**: Detects performance issues using Prometheus metrics
- **K8s Agent**: Diagnoses the root cause and applies the fix

The Scenario: "Resource Constraint Crisis"

You're running an application experiencing performance degradation:
- High CPU usage (90%+)
- Memory pressure and OOMKills
- Frequent pod restarts
- Application instability

**The Problem**: The application has insufficient resources causing memory pressure and CPU throttling under load.


## Prerequisites
- kagent Enterprise installed and running
- kubectl access to your cluster
- Prometheus installed (optional, but recommended for full observability)


## Deploy the "Broken" Demo App

This deployment intentionally has resource constraints that will cause issues under load.

```
kubectl create namespace demo
```

```
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  namespace: demo
data:
  MEMORY_LEAK_ENABLED: "true"
  CACHE_SIZE: "10000"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: demo-app
  namespace: demo
  labels:
    app: demo-app
    tier: backend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: demo-app
  template:
    metadata:
      labels:
        app: demo-app
        tier: backend
    spec:
      containers:
      - name: app
        image: polinux/stress:latest
        command:
        - /bin/sh
        - -c
        - |
          echo "Demo App Starting - Stress Test Mode!"
          echo "Memory Leak Enabled: $MEMORY_LEAK_ENABLED"
          echo "Load Level: $LOAD_LEVEL"
          # Simulate an app with memory pressure and high CPU usage
          # This will cause OOMKills and CPU throttling with the low resource limits
          while true; do
            stress --vm 2 --vm-bytes 150M --vm-hang 0 --timeout 120s &
            stress --cpu 2 --timeout 120s
            sleep 10
          done
        env:
        - name: MEMORY_LEAK_ENABLED
          valueFrom:
            configMapKeyRef:
              name: app-config
              key: MEMORY_LEAK_ENABLED
        - name: LOAD_LEVEL
          valueFrom:
            configMapKeyRef:
              name: app-config
              key: CACHE_SIZE
        resources:
          requests:
            memory: "64Mi"      # TOO LOW! Should be 256Mi
            cpu: "100m"         # TOO LOW! Should be 500m
          limits:
            memory: "128Mi"     # TOO LOW! Will cause OOMKills
            cpu: "200m"         # TOO LOW! Will cause throttling
---
apiVersion: v1
kind: Service
metadata:
  name: demo-app
  namespace: demo
  labels:
    app: demo-app
spec:
  type: ClusterIP
  ports:
  - port: 80
    targetPort: 8080
    name: http
  selector:
    app: demo-app
EOF
```

**What's happening?**
- Demo app with inadequate resources (64Mi memory / 100m CPU)
- The stress command generates memory and CPU load
- Memory pressure: allocating 150M with only 128M limit = guaranteed OOMKills
- CPU stress with 200m limit = guaranteed throttling
- Within 30-60 seconds, you'll see OOMKills and restarts

## Observe the Chaos

Wait 1-2 minutes for the pods to start crashing due to resource constraints.

```bash
# Watch pods crash and restart
kubectl get pods -n demo -w

# Check pod events for OOMKilled errors
kubectl get events -n demo --sort-by='.lastTimestamp' | grep -i oom

# Check resource usage
kubectl top pods -n demo
```

You should see:
- Pods restarting frequently (OOMKilled)
- CPU throttling at 200m limit
- Memory at 128Mi limit before crash


## Observability Agent - Detect the Issue =

Use kagent's **observability agent** to detect what's wrong.

1. Open kagent UI and select the "Observability Agent"

2. Use the following prompt:
```
I'm getting reports that the demo-app in the 'demo' namespace
is experiencing performance issues. Can you check the metrics and tell me
what's happening?
```

**Expected Agent Behavior:**
The observability agent will:
1. Query Prometheus for pod metrics in the demo namespace
2. Identify high CPU usage (throttling at limits)
3. Detect memory pressure and OOMKills
4. Analyze restart patterns
5. Provide a summary of the issue

## K8s Agent - Fix the Issue

Now switch to the **K8s Agent** to resolve the problem.

**Prompt 1: Diagnose and Fix**
```
The demo-app deployment in the demo namespace is experiencing OOMKills
and CPU throttling. Can you investigate and fix the resource constraints?
```

**Expected Agent Behavior:**
The K8s agent will:
1. Check the deployment specification
2. Identify inadequate resource requests/limits
3. Analyze current usage patterns
4. **Automatically patch the deployment** with appropriate resources:
   - Memory request: 64Mi > 256Mi
   - Memory limit: 128Mi > 512Mi
   - CPU request: 100m > 500m
   - CPU limit: 200m > 1000m
5. Monitor the rollout
6. Verify pods are stable

**Prompt 2: Verify the Fix**
```
Can you verify that the demo-app pods are now stable and performing well?
```

**Expected Agent Behavior:**
The agent will:
1. Check pod status (should be Running, no restarts)
2. Verify resource usage is within healthy ranges
3. Check readiness/liveness probe success
4. Confirm no recent OOMKills in events

## Cleanup

```bash
kubectl delete namespace demo
```

## Why This Demo

1. **Realistic Scenario**: Resource constraint issues are common in production environments
2. **Clear Separation of Concerns**:
   - Observability agent focuses on *detection*
   - K8s agent focuses on *remediation*
3. **Visible Impact**: You can actually watch the pods crash and recover
4. **Multiple Problem Vectors**: Resource limits, memory pressure, and configuration issues
5. **End-to-End Story**: From problem detection to resolution

# kagent Demo: Observability Agent + K8s Agent Working Together

## Overview
This demo showcases kagent out-of-the-box Agents working together to detect and resolve a real-world production issue.

- **Observability Agent**: Detects performance issues using Prometheus metrics
- **K8s Agent**: Diagnoses the root cause and applies the fix

The Scenario: "Black Friday Meltdown"

You're running an e-commerce platform on Black Friday. Your shopping cart service is experiencing performance degradation:
- High CPU usage (90%+)
- Memory pressure and OOMKills
- Slow response times (5s+)
- Customer complaints flooding in

**The Problem**: The shopping cart service has insufficient resources and a memory leak that manifests under high load.


## Prerequisites
- kagent Enterprise installed and running
- kubectl access to your cluster
- Prometheus installed (optional, but recommended for full observability)


## Deploy the "Broken" Shopping Cart App

This deployment intentionally has resource constraints that will cause issues under load.

```
kubectl create namespace shop
```

```
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: cart-config
  namespace: shop
data:
  MEMORY_LEAK_ENABLED: "true"
  CACHE_SIZE: "10000"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: shopping-cart
  namespace: shop
  labels:
    app: shopping-cart
    tier: backend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: shopping-cart
  template:
    metadata:
      labels:
        app: shopping-cart
        tier: backend
    spec:
      containers:
      - name: cart-service
        image: ghcr.io/solo-io/shopping-cart-demo:v1.0.0
        ports:
        - containerPort: 8080
          name: http
        env:
        - name: MEMORY_LEAK_ENABLED
          valueFrom:
            configMapKeyRef:
              name: cart-config
              key: MEMORY_LEAK_ENABLED
        - name: CACHE_SIZE
          valueFrom:
            configMapKeyRef:
              name: cart-config
              key: CACHE_SIZE
        resources:
          requests:
            memory: "64Mi"      # TOO LOW! Should be 256Mi
            cpu: "100m"         # TOO LOW! Should be 500m
          limits:
            memory: "128Mi"     # TOO LOW! Will cause OOMKills
            cpu: "200m"         # TOO LOW! Will cause throttling
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 3
---
apiVersion: v1
kind: Service
metadata:
  name: shopping-cart
  namespace: shop
  labels:
    app: shopping-cart
spec:
  type: ClusterIP
  ports:
  - port: 80
    targetPort: 8080
    name: http
  selector:
    app: shopping-cart
---
apiVersion: batch/v1
kind: Job
metadata:
  name: load-generator
  namespace: shop
spec:
  parallelism: 3
  completions: 3
  template:
    metadata:
      labels:
        app: load-generator
    spec:
      containers:
      - name: hey
        image: williamyeh/hey:latest
        command:
        - /bin/sh
        - -c
        - |
          sleep 30
          echo "Starting Black Friday load test..."
          hey -z 10m -c 50 -q 10 http://shopping-cart.shop.svc.cluster.local/cart/add
      restartPolicy: Never
  backoffLimit: 0
EOF
```

**What's happening?**
- Shopping cart service with inadequate resources (64Mi/100m CPU)
- Load generator simulates Black Friday traffic (50 concurrent users)
- Memory leak enabled via config map (simulates real-world memory leak)
- Within 2-3 minutes, you'll see OOMKills and performance degradation

## Observe the Chaos

Wait 2-3 minutes for the load generator to start causing issues.

```bash
# Watch pods crash and restart
kubectl get pods -n shop -w

# Check pod events for OOMKilled errors
kubectl get events -n shop --sort-by='.lastTimestamp' | grep -i oom

# Check resource usage
kubectl top pods -n shop
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
I'm getting reports that our shopping cart service in the 'shop' namespace
is experiencing performance issues. Can you check the metrics and tell me
what's happening?
```

**Expected Agent Behavior:**
The observability agent will:
1. Query Prometheus for pod metrics in the shop namespace
2. Identify high CPU usage (throttling at limits)
3. Detect memory pressure and OOMKills
4. Analyze restart patterns
5. Provide a summary of the issue

## K8s Agent - Fix the Issue

Now switch to the **K8s Agent** to resolve the problem.

**Prompt 1: Diagnose and Fix**
```
The shopping-cart deployment in the shop namespace is experiencing OOMKills
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
Can you verify that the shopping-cart pods are now stable and performing well?
```

**Expected Agent Behavior:**
The agent will:
1. Check pod status (should be Running, no restarts)
2. Verify resource usage is within healthy ranges
3. Check readiness/liveness probe success
4. Confirm no recent OOMKills in events

## Why This Demo

1. **Realistic Scenario**: Black Friday shopping cart issues are relatable and dramatic
2. **Clear Separation of Concerns**:
   - Observability agent focuses on *detection*
   - K8s agent focuses on *remediation*
3. **Visible Impact**: You can actually watch the pods crash and recover
4. **Multiple Problem Vectors**: Resource limits, memory leaks, and configuration issues
5. **End-to-End Story**: From problem detection to resolution

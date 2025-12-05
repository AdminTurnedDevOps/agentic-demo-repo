# Ready-to-Use Prompts for SRE Demo

Copy and paste these prompts directly into the kagent UI.

## Observability Agent Prompts

### 1. Initial Detection
```
I'm getting alerts that the demo-app in the 'demo' namespace is having issues. 
Can you check and tell me what's happening?
```

### 2. Memory Analysis
```
Can you query Prometheus for memory metrics of the demo-app pods in the demo namespace?
I want to see current usage vs limits and any OOMKill events.
```

## K8s Agent Prompts

### 1. Initial Diagnosis
```
The demo-app deployment in the demo namespace is experiencing OOMKills and memory issues.
Can you investigate the deployment and identify what's wrong with the resource configuration?
```

### 2. Full Fix Request
```
The demo-app deployment in the demo namespace has resource limits that are too restrictive.
The current memory limit of 64Mi is causing OOMKills.
Can you patch the deployment with these values:
- Memory request: 256Mi
- Memory limit: 512Mi
- CPU request: 100m
- CPU limit: 500m
```

### 3. Quick Fix (One-liner)
```
Fix the OOMKill issue in demo-app deployment by increasing memory limits to 512Mi and requests to 256Mi.
```

### 4. Status Check
```
What is the current status of the demo-app pods in the demo namespace?
Are there any failing or restarting pods?
```

### 5. Verification
```
Verify that the demo-app pods are now stable and performing well after the resource fix.
Check for any recent restarts or error events.
```

### 6. Rollout Status
```
What is the rollout status of the demo-app deployment? Are all replicas ready and available?
```

---

## Combined Workflow Prompts

### For Observability Agent → K8s Agent Handoff
```
Based on the Prometheus metrics, the demo-app has these issues:
- Container memory usage is hitting 100% of limits
- OOMKills detected
- Multiple pod restarts

Please summarize what needs to be fixed so I can give this to the K8s agent.
```

### For K8s Agent After Receiving Analysis
```
The Observability Agent found that demo-app in the demo namespace has:
- Memory limit too low (64Mi)
- OOMKills occurring
- High restart count

Please diagnose and fix this issue by updating the deployment resources.
```

---

## Advanced Prompts (Optional)

### Observability Agent - Cluster-Wide Check
```
Are there any other applications in the cluster showing signs of memory pressure 
similar to demo-app? Check for high memory usage or OOMKills across all namespaces.
```

### K8s Agent - Events Analysis
```
Show me all Warning events related to demo-app pods in the demo namespace from the last hour.
```

### K8s Agent - Resource Recommendations
```
Based on the current resource usage of demo-app, what would you recommend 
for optimal resource requests and limits?
```

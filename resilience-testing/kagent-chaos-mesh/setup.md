## Install Kagent

Below you will find the installation of kagent for both Anthropic and OpenAI as your first Model used (you can add more after installation)

### CLI

```
curl https://raw.githubusercontent.com/kagent-dev/kagent/refs/heads/main/scripts/get-kagent | bash
```

### Helm

#### CRDs

```
helm install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
    --namespace kagent \
    --create-namespace
```

#### With Anthropic
```
export ANTHROPIC_API_KEY=your_api_key
```

The below contains the flag to give the kagent UI a public IP so you can reach it that way instead of doing a `port-forward`. However, if you're running kagent locally or don't want to create a load balancer, you can just remove the `--set ui.service.type=LoadBalancer` part of the installation below.
```
helm upgrade --install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
    --namespace kagent \
    --set providers.default=anthropic \
    --set providers.anthropic.apiKey=$ANTHROPIC_API_KEY \
    --set ui.service.type=LoadBalancer
```

#### Dashboard Setup
1. With an LB
```
kubectl get svc -n kagent
```

2. Retrieve the public IP of the `kagent-ui` LB

Without an LB
```
kubectl port-forward svc/kagent-ui -n kagent 8080:8080
```

3. Access the kagent setup and create your own agent via the UI

## Install Chaos Mesh

```
helm repo add chaos-mesh https://charts.chaos-mesh.org
```

```
helm install chaos-mesh chaos-mesh/chaos-mesh \
-n=chaos-mesh \
--set chaosDaemon.runtime=containerd \
--set chaosDaemon.socketPath=/run/containerd/containerd.sock \
--create-namespace
```

```
kubectl get pods -n chaos-mesh
```

```
kubectl port-forward -n chaos-mesh svc/chaos-dashboard 2333:2333
```

## Configure Chaos Mesh

1. For Chaos Mesh to be able to interact with Pods running in a particular Namespace to do chaos testing, it needs access to said Pods.

Within the dashboard, the first thing you'll see is the Token Generator. Run through those configs. You can see an example below:

```
kubectl apply -f - <<EOF
kind: ServiceAccount
apiVersion: v1
metadata:
  namespace: default
  name: account-cluster-manager-aqsvh
---
kind: ClusterRole
apiVersion: rbac.authorization.k8s.io/v1
metadata:
  name: role-cluster-manager-aqsvh
rules:
- apiGroups: [""]
  resources: ["pods", "namespaces"]
  verbs: ["get", "watch", "list"]
- apiGroups: ["chaos-mesh.org"]
  resources: [ "*" ]
  verbs: ["get", "list", "watch", "create", "delete", "patch", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: bind-cluster-manager-aqsvh
subjects:
- kind: ServiceAccount
  name: account-cluster-manager-aqsvh
  namespace: default
roleRef:
  kind: ClusterRole
  name: role-cluster-manager-aqsvh
  apiGroup: rbac.authorization.k8s.io
EOF
```

```
kubectl create token account-cluster-manager-aqsvh
```

2. Enter the token output into the Chaos Mesh dashboard.

## Create Experiments

To create the experiments, go to the **Experiments** dashboard, click **+ New experiment**, and choose the **By YAML:** Option

### 1. Pod Kill Experiment
Kills a specific pod to test automatic restart and recovery:

```
kubectl apply -f - <<EOF
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: kagent-pod-kill
  namespace: kagent
spec:
  action: pod-kill
  mode: one
  selector:
    namespaces:
      - kagent
    pods:
      kagent:
        - k8s-agent-7b47bfbbb4-94fkf  # Replace with your specific pod name
EOF
```

### 2. Stress Test Experiment
Stress tests a specific pod with CPU and memory pressure:

```
kubectl apply -f - <<EOF
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: kagent-stress-test
  namespace: kagent
spec:
  mode: one
  duration: '120s'
  selector:
    namespaces:
      - kagent
    pods:
      kagent:
        - k8s-agent-7b47bfbbb4-94fkf  # Replace with your specific pod name
  stressors:
    cpu:
      workers: 2
      load: 80
    memory:
      workers: 2
      size: '512MB'
EOF
```

### How to Use

### Managing Experiments

View running experiments:
```bash
kubectl get podchaos,stresschaos -n chaos-mesh
```

Delete an experiment:
```bash
kubectl delete podchaos kagent-pod-kill -n chaos-mesh
kubectl delete stresschaos kagent-stress-test -n chaos-mesh
```



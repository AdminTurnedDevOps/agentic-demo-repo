# Inference on Kubernetes for AI Workloads

Inference in AI consists of two pieces:

1. Inference == Make a prediction on unseen/new data.

Example: You can ask a chatbot a question and it answers it based on what data it was trained on. It's really a prediction (guess) on what you want to know.

2. Inference Routing == the infrastructure layer.

Examples:
- Load Balancing workloads: requests to LLMs
- Resource Management: Models are expensive. Inference routing can help choose which Model has the least amount of load.
- Priority Handling: Requests that are the most important get to the best Model for the inference job.

Inference is all about making a prediction on unseen data. Inference routing is ensuring that the request gets to the right Model in an efficient and performant fashion.

## Prerequisites

Because you're running Models locally on a Kubernetes cluster, you'll want to ensure that the cluster you're running has enough resources. For this configuration, you'll want Node Pools that have a minimum of 12 vCPUs and 16GB memory.

If you don't have enough resources, you may see an event in the Pod like the below:
```
0/3 nodes are available: 3 Insufficient cpu, 3 Insufficient memory. preemption: 0/3 nodes are available: 3 No preemption victims found for incoming pod.
```

## How Inference Testing Works In This File
This configuration demonstrates the complete inference routing architecture.

Here's the flow:
- The Infrastructure Stack (Steps 1-5):
- vLLM Model Server (Step 1, lines 31-152)
- Runs the actual AI model (Qwen/Qwen2.5-1.5B-Instruct)
- Exposes an OpenAI-compatible API on port 8000
- Has a /health endpoint and /v1/completions endpoint
- InferencePool (Step 4, lines 179-186)
- Logical grouping of model servers
- Uses label selectors to find pods: `app=vllm-llama3-8b-instruct`
- Handles load balancing across multiple model server replicas
- Gateway + HTTPRoute (Step 5, lines 191-223)
- Gateway: Entry point for external traffic (listens on port 80)
- HTTPRoute: Routes requests from the Gateway to the InferencePool
- Path prefix / routes to the InferencePool named vllm-llama3-8b-instruct
- The Test Request (Step 6, lines 226-237):

The testing occurs via the `curl` in step 6. The Request Flow is:
```
User/Curl Request
    ↓
Gateway (port 80) ← External entry point
    ↓
HTTPRoute ← Routes based on path prefix "/"
    ↓
InferencePool ← Selects available model server
    ↓
vLLM Pod (port 8000) ← Runs the actual model inference
    ↓
Response back through the stack
```

This is testing inference routing, not just running the model directly, but going through the entire Kubernetes Gateway API + InferencePool abstraction layer.

This allows for:
- Load balancing across multiple model replicas
- Centralized routing and traffic management
- Health-aware routing (only send to healthy pods)
- Easy scaling and model versioning

So you're testing the whole platform, not just the model itself.

## Install & Config

1. Deploy the `Deployment` object which uses a vLLM container image specifically for testing against CPU instead of GPU. It uses Ollama/Llama
```
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm-llama3-8b-instruct
spec:
  replicas: 1
  selector:
    matchLabels:
      app: vllm-llama3-8b-instruct
  template:
    metadata:
      labels:
        app: vllm-llama3-8b-instruct
    spec:
      containers:
        - name: lora
          image: "public.ecr.aws/q9t5s3a7/vllm-cpu-release-repo:v0.10.2" # formal images can be found in https://gallery.ecr.aws/q9t5s3a7/vllm-cpu-release-repo
          imagePullPolicy: IfNotPresent
          command: ["python3", "-m", "vllm.entrypoints.openai.api_server"]
          args:
          - "--model"
          - "Qwen/Qwen2.5-1.5B-Instruct"
          - "--port"
          - "8000"
          - "--enable-lora"
          - "--max-loras"
          - "4"
          - "--lora-modules"
          - '{"name": "food-review-0", "path": "SriSanth2345/Qwen-1.5B-Tweet-Generations", "base_model_name": "Qwen/Qwen2.5-1.5B"}'
          - '{"name": "food-review-1", "path": "SriSanth2345/Qwen-1.5B-Tweet-Generations", "base_model_name": "Qwen/Qwen2.5-1.5B"}'
          env:
            - name: PORT
              value: "8000"
            - name: VLLM_ALLOW_RUNTIME_LORA_UPDATING
              value: "true"
            - name: VLLM_CPU_KVCACHE_SPACE
              value: "4"
          ports:
            - containerPort: 8000
              name: http
              protocol: TCP
          livenessProbe:
            failureThreshold: 240
            httpGet:
              path: /health
              port: http
              scheme: HTTP
            initialDelaySeconds: 180
            periodSeconds: 5
            successThreshold: 1
            timeoutSeconds: 1
          readinessProbe:
            failureThreshold: 600
            httpGet:
              path: /health
              port: http
              scheme: HTTP
            initialDelaySeconds: 180
            periodSeconds: 5
            successThreshold: 1
            timeoutSeconds: 1
          resources:
             limits:
               cpu: "11"
               memory: "10Gi"
             requests:
               cpu: "11"
               memory: "10Gi"
          volumeMounts:
            - mountPath: /data
              name: data
            - mountPath: /dev/shm
              name: shm
            - name: adapters
              mountPath: "/adapters"
      initContainers:
        - name: lora-adapter-syncer
          tty: true
          stdin: true
          image: registry.k8s.io/gateway-api-inference-extension/lora-syncer:v1.1.0-rc.1
          restartPolicy: Always
          imagePullPolicy: Always
          env:
            - name: DYNAMIC_LORA_ROLLOUT_CONFIG
              value: "/config/configmap.yaml"
          volumeMounts: # DO NOT USE subPath, dynamic configmap updates don't work on subPaths
          - name: config-volume
            mountPath:  /config
      restartPolicy: Always
      schedulerName: default-scheduler
      terminationGracePeriodSeconds: 30
      volumes:
        - name: data
          emptyDir: {}
        - name: shm
          emptyDir:
            medium: Memory
        - name: adapters
          emptyDir: {}
        - name: config-volume
          configMap:
            name: vllm-qwen-adapters
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: vllm-qwen-adapters
data:
  configmap.yaml: |
      vLLMLoRAConfig:
        name: vllm-llama3-8b-instruct
        port: 8000
        ensureExist:
          models:
          - base-model: Qwen/Qwen2.5-1.5B
            id: food-review
            source: SriSanth2345/Qwen-1.5B-Tweet-Generations
          - base-model: Qwen/Qwen2.5-1.5B
            id: cad-fabricator
            source: SriSanth2345/Qwen-1.5B-Tweet-Generations
EOF
```

You'll need to give it about 2-3 minutes for the Model to download and then you can confirm the Pod is running with the following command:
```
kubectl get Pods
```

2. Install the CRDs for Inference
```
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v1.1.0/manifests.yaml
```

3. Install a Gateway and the Gateway CRDs. In this case, you'll use kgateway/agentgateway
```
helm upgrade -i --create-namespace --namespace kgateway-system --version v2.2.0-main kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds

helm upgrade -i --namespace kgateway-system \
--version v2.2.0-main kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway \
--set inferenceExtension.enabled=true
```

4. Deploy the below Helm chart which does the following:
- Installs an `InferencePool` resource/object that acts as a logical grouping of AI model servers for load balancing and routing inference requests
- Installs the Endpoint-picker extension, which is an ntelligent selection among available model servers for load balancing

```
export IGW_CHART_VERSION=v1.1.0
export GATEWAY_PROVIDER=none

helm install vllm-llama3-8b-instruct \
--set inferencePool.modelServers.matchLabels.app=vllm-llama3-8b-instruct \
--set provider.name=$GATEWAY_PROVIDER \
--version $IGW_CHART_VERSION \
oci://registry.k8s.io/gateway-api-inference-extension/charts/inferencepool
```

5. Deploy a `Gateway` and `HTTPRoute` object for Inference. This will route to the `InferencePool` that was created in the previous step via the Helm Chart. This piece (`inferencePool.modelServers.matchLabels.app) matches any app running the `vllm-llama3-8b-instruct` label, which was deployed in step 1 (the `Deployment` object)
```
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: inference-gateway
spec:
  gatewayClassName: agentgateway
  listeners:
  - name: http
    port: 80
    protocol: HTTP
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: llm-route
spec:
  parentRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: inference-gateway
  rules:
  - backendRefs:
    - group: inference.networking.k8s.io
      kind: InferencePool
      name: vllm-llama3-8b-instruct
    matches:
    - path:
        type: PathPrefix
        value: /
    timeouts:
      request: 300s
EOF
```

6. Test and confirm
```
IP=$(kubectl get gateway/inference-gateway -o jsonpath='{.status.addresses[0].value}')
PORT=80

curl -i ${IP}:${PORT}/v1/completions -H 'Content-Type: application/json' -d '{
"model": "Qwen/Qwen2.5-1.5B-Instruct",
"prompt": "What is the warmest city in the USA?",
"max_tokens": 100,
"temperature": 0.5
}'
```

You should see an output similar to the below:
```
HTTP/1.1 200 OK
date: Sun, 16 Nov 2025 19:54:07 GMT
server: uvicorn
content-type: application/json
x-went-into-resp-headers: true
transfer-encoding: chunked

{"choices":[{"finish_reason":"length","index":0,"logprobs":null,"prompt_logprobs":null,"prompt_token_ids":null,"stop_reason":null,"text":" The warmest city in the United States is Phoenix, Arizona. It has an average high temperature of 85 degrees Fahrenheit (29 degrees Celsius) and a low of 60 degrees Fahrenheit (15 degrees Celsius). However, it's important to note that temperatures can vary greatly depending on location within the city, so it's always best to check local weather forecasts for specific areas before planning any outdoor activities. Additionally, Phoenix experiences extreme heat during summer months, with temperatures often exceeding 1","token_ids":null}],"created":1763322848,"id":"cmpl-2e381ca7-62ae-4479-ae64-fdd18f005a1e","kv_transfer_params":null,"model":"Qwen/Qwen2.5-1.5B-Instruct","object":"text_completion","service_tier":null,"system_fingerprint":null,"usage":{"completion_tokens":100,"prompt_tokens":10,"prompt_tokens_details":null,"total_tokens":110}}% 
```
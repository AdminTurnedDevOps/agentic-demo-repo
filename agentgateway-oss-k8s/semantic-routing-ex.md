# Semantic / Intelligent Multi-Model Routing Examples

**agentgateway OSS + Kubernetes**

This document shows practical ways to implement automated, "intelligent" multi-model routing for LLM traffic — for example, detecting that a request represents a "hard task" and routing it to a stronger (more expensive) model like Claude Opus instead of Sonnet.

agentgateway supports two main approaches:

- **CEL (in-policy, no extra components)**: Fast, lightweight heuristics based on prompt length, keywords, structure, etc.
- **ext_proc (external processor)**: Full request body inspection with arbitrary logic, including calls to small classifiers, embedding models, or LLM-as-judge routers.

These examples target Anthropic models (Sonnet ↔ Opus) but apply equally to any providers supported by agentgateway LLM backends.

Example minimal backend (for reference):

```yaml
# agentgatewaybackend.yaml (simplified)
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: anthropic-llm
  namespace: default
spec:
  ai:
    providerGroups:
    - providers:
      - name: anthropic
        anthropic:
          model: claude-3-5-sonnet-20241022   # default / cheap
        # auth, tls, etc.
    # Additional priority groups for failover can be added here
```

## CEL-Based Examples (Pure Policy, No Sidecar)

CEL transformations let you rewrite the request body (including the `model` field) using expressions over the parsed LLM request (`messages`, `system`, `tools`, length, etc.).

### 1. Length-based escalation (long prompt → Opus)

```yaml
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: llm-escalate-long
  namespace: default
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: llm-gateway
  traffic:
    transformation:
      request:
        # CEL body rewrite. The result replaces the outgoing LLM request body.
        body: |
          request + {
            model: if size(request.messages[0].content) > 1500
                   then "claude-3-opus-4-7"
                   else "claude-3-5-sonnet-20241022"
          }
```

**How it works**:
- Inspects the first user message length.
- Longer prompts (more context/complexity) get the stronger model.
- Can be combined with `metadata` extraction or conditional policies.

### 2. Keyword + structural complexity heuristic

More sophisticated "task awareness" using prompt content and structure.

```yaml
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: llm-escalate-complex
  namespace: default
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: llm-gateway
  traffic:
    transformation:
      request:
        body: |
          request + {
            model: if (
              request.messages.exists(m,
                m.content.contains("architecture") ||
                m.content.contains("multi-step") ||
                m.content.contains("root cause") ||
                m.content.contains("tradeoffs") ||
                m.content.contains("analyze deeply") ||
                m.content.matches("(?i)\\b(step by step|reason step|prove|formalize)\\b")
              ) ||
              size(request.messages) > 8 ||
              (has(request.tools) && size(request.tools) > 5)
            )
            then "claude-3-opus-4-7"
            else "claude-3-5-sonnet-20241022"
          }
```

**Alternative (cleaner for single-field overrides)** — using the dedicated AI `transformations`:

```yaml
spec:
  # ... targetRefs ...
  traffic:
    transformation:
      request:
        # You can also attach AI-specific field transforms when the policy
        # context includes ai configuration (or via backend policies).
        # The AI FieldTransformation is optimized for LLM request bodies.
  # Example AI-style (when supported in your policy attachment point):
  # ai:
  #   transformations:
  #   - field: model
  #     expression: |
  #       if ( ... same condition ... ) then "claude-3-opus-4-7" else "claude-3-5-sonnet-20241022"
```

**Tips for CEL**:
- Use `conditional` under `TransformationOrConditional` for multiple rules with fallbacks.
- Combine with prompt guards or enrichment policies.
- CEL has full access to the normalized LLM request shape.

## ext_proc Examples (External Processor)

`ext_proc` gives you the **full raw request body** (and headers) before the gateway does provider selection or upstream call. Perfect for real intelligence (classifiers, embeddings, small router models).

Configure via `traffic.extProc` (recommended in `phase: PreRouting`).

### 3. Basic heuristic ext_proc router

**Policy** (attaches the processor):

```yaml
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: llm-smart-router-basic
  namespace: default
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: llm-gateway
  traffic:
    phase: PreRouting
    extProc:
      backendRef:
        group: ""
        kind: Service
        name: llm-router-extproc
        port: 50051
      processingOptions:
        requestHeaderMode: SEND
        requestBodyMode: BUFFERED   # Required to see the full prompt
        # responseBodyMode not needed for model selection
```

**Minimal Python ext_proc implementation** (gRPC, using standard Envoy ext_proc messages):

```python
# llm_router_extproc.py
import grpc
import json
from concurrent import futures

# Import the generated stubs (envoy.service.ext_proc.v3)
import external_processor_pb2 as ext_proc
import external_processor_pb2_grpc

class LLMRouter(ext_proc.ExternalProcessorServicer):
    def Process(self, request_iterator, context):
        for req in request_iterator:
            if req.HasField("request_body"):
                original = json.loads(req.request_body.body)
                messages = original.get("messages", [])
                text = " ".join(
                    str(m.get("content", "")) 
                    for m in messages 
                    if isinstance(m.get("content"), (str, dict))
                )

                # === Your heuristic "intelligence" here ===
                is_hard = (
                    len(text) > 1200 or
                    any(kw in text.lower() for kw in [
                        "architecture", "tradeoff", "multi-step", 
                        "root cause", "formal proof", "analyze deeply"
                    ])
                )

                new_model = "claude-3-opus-4-7" if is_hard else "claude-3-5-sonnet-20241022"
                original["model"] = new_model

                resp = ext_proc.ProcessingResponse()
                resp.request_body.response = ext_proc.CommonResponse(
                    body_mutation=ext_proc.BodyMutation(
                        body=json.dumps(original).encode("utf-8")
                    )
                )
                yield resp
            else:
                # Pass through everything else
                yield ext_proc.ProcessingResponse()

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    ext_proc_grpc.add_ExternalProcessorServicer_to_server(LLMRouter(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    print("LLM router ext_proc listening on 50051")
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
```

Deploy this as a normal `Deployment` + `Service` (or sidecar). It only needs to speak gRPC ext_proc.

### 4. Intelligent router with external classifier / embeddings

Same policy YAML as above (just point `backendRef` at your smarter service).

In the processor, call out to real intelligence:

```python
# ... same Process loop ...
full_prompt = build_full_prompt(messages, system=...)   # your helper

# Option A: Small classifier service (e.g. mmbert-style or fine-tuned)
complexity_score = call_classifier_service(full_prompt)  # returns 0.0–1.0

# Option B: Embedding + prototype / KNN (as referenced in advanced agentgateway configs)
# embedding = embed(full_prompt)
# complexity_score = knn_score_against_prototypes(embedding)

# Option C: Tiny router LLM call (cheap model)
# decision = call_router_model(full_prompt, candidates=["sonnet", "opus"])

if complexity_score > 0.75 or is_multi_hop(full_prompt):
    chosen_model = "claude-3-opus-4-7"
    reason = f"high-complexity:{complexity_score:.2f}"
else:
    chosen_model = "claude-3-5-sonnet-20241022"
    reason = "standard"

original["model"] = chosen_model

resp = ext_proc.ProcessingResponse()
resp.request_body.response = ext_proc.CommonResponse(
    body_mutation=ext_proc.BodyMutation(body=json.dumps(original).encode()),
    # You can also return dynamic metadata for logging/tracing
)
# Optionally set headers:
# resp.request_body.response.header_mutation.set_headers.append(...)
yield resp
```

**Advanced ideas for this router**:
- Integrate the embedding models and complexity prototype scoring from the agentgateway `models/` and advanced `config.yaml` examples.
- Use semantic cache hits to short-circuit.
- For self-hosted models, mutate to target a specific `InferencePool` or return routing decisions via headers/body.
- Add caching + replay (see `router_replay` patterns in advanced configs).

## Applying and Testing

```bash
kubectl apply -f llm-escalate-long.yaml
kubectl apply -f llm-smart-router-basic.yaml
# ... etc
```

Test:

```bash
curl -X POST http://<gateway>/v1/messages \
  -H "content-type: application/json" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "messages": [{"role":"user", "content": "Design a distributed caching layer for a global e-commerce platform with strong consistency requirements and analyze the tradeoffs..."}]
  }'
```

Inspect:
- Gateway/proxy logs (look for model actually used).
- Add a header in the transformation/ext_proc (e.g. `x-chosen-model`) for easy debugging.
- Prometheus metrics + traces will reflect the chosen model.
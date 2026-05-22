# agentevals: Three Production-Grade Demos

Three self-contained demos that exercise the full power of `agentevals` across two different agents (a Wikipedia-backed research agent for Demo 1, and a Kubernetes-troubleshooting agent against a real AKS cluster for Demos 2 and 3). The contrast across demos is the eval workflow, not the agent.

| # | Demo | Agent | What it shows |
|---|---|---|---|
| 1 | **Citation-aware research evaluation** | OpenAI Agents SDK + Wikipedia | Multi-step researcher with inline URL citations, scored by a custom evaluator that HTTP-fetches every cited URL and verifies the response's claims appear on the page. Catches hallucinated sources AND hallucinated facts cited to real URLs. |
| 2 | **Async run queue with webhook sinks** | LangGraph + real `kubectl` | Postgres-backed `/api/runs` endpoint scores traces in the background and fires `http_webhook` for alert-on-fail flows. |
| 3 | **Custom Evaluators with LLM Judges** | LangGraph + real `kubectl` | Four evaluators side-by-side in three runtimes — built-in trajectory check, Python LLM judge (auto-venv), JavaScript stdin/stdout evaluator, OpenAI Evals API delegation. |

agentevals itself runs **on the AKS cluster** (Helm-installed) for all three demos. The agent runs from your laptop and OTLP-pushes to the cluster's LoadBalancer. Sessions show up live in the agentevals UI as the agent works.

---

## 0. One-time prerequisites

You need these once, for any demo.

### 0.1 Local tools

```
python3.13 -m venv .venv && source .venv/bin/activate
```

```bash
brew install python@3.12 node helm kubectl jq gh
brew install azure-cli           # for the AKS context

pip install agentevals-cli
pip install "agentevals-cli[openai]"   # for Demo 3's OpenAI Evals API evaluator

export OPENAI_API_KEY=sk-...
```

Clone this repo and `cd` into `agentevals/`. From here on every path is
relative to that directory.

```bash
cd agentic-demo-repo/agentevals
ls
# cluster-setup/         demo.md                demo1-research-agent/   demo2-aks-live/
# demo3-custom-evals/    k8s-troubleshooting-agent/   live-session/   web-research-agent/
```

### 0.2 AKS cluster

Skip this section if you already have an AKS cluster with `kubectl` access.

```bash
# Replace <rg>, <cluster>, <region> with your values
az group create -l <region> -n <rg>
az aks create -g <rg> -n <cluster> --node-count 2 --generate-ssh-keys
az aks get-credentials -g <rg> -n <cluster>
kubectl get nodes
```

### 0.3 Install agentevals on AKS

The values file at `cluster-setup/agentevals-values.yaml` provisions a production-flavored install: Postgres-backed run queue (unlocks Demo 2's async sinks), LoadBalancer Service (UI accessible externally), `OPENAI_API_KEY` wired through `envFrom` for the built-in LLM judge.

```bash
kubectl create namespace agentevals
```

```
kubectl -n agentevals create secret generic openai-key \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY"
```

```
helm install agentevals \
  oci://ghcr.io/agentevals-dev/agentevals/helm/agentevals \
  -n agentevals \
  -f - <<EOF
replicaCount: 1
service:
  type: LoadBalancer
  http:
    port: 8001
  otlpHttp:
    port: 4318
  otlpGrpc:
    port: 4317

storage:
  backend: postgres

database:
  postgres:
    schema: agentevals
    autoMigrate: true
    bundled:
      enabled: true
      storage: 5Gi
      resources:
        requests:
          cpu: 500m
          memory: 512Mi
        limits:
          cpu: "1"
          memory: 1Gi

envFrom:
  - secretRef:
      name: openai-key

resources:
  requests:
    cpu: 250m
    memory: 512Mi
  limits:
    cpu: "1"
    memory: 1Gi

EOF
```

```
kubectl -n agentevals get svc agentevals -w
```

Once an external IP appears, capture it:

```bash
export AGENTEVALS_IP=$(kubectl -n agentevals get svc agentevals \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "UI:   http://${AGENTEVALS_IP}:8001"
echo "OTLP: http://${AGENTEVALS_IP}:4318"
```

### 0.4 Apply the broken workloads the k8s agent will diagnose

Needed by Demos 2 and 3 (the k8s-troubleshooting agent). Demo 1 (research agent)
doesn't read from the cluster.

```bash
kubectl apply -f cluster-setup/broken-workloads.yaml
```

### 0.5 Point the agents at the cluster

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://${AGENTEVALS_IP}:4318
# `KUBECONFIG` is already set by `az aks get-credentials` — the k8s agent's tools inherit your current kubectl context.
```

---

## The two agents under test

| Agent | Used by | What it does |
|---|---|---|
| `web-research-agent/` | Demo 1 | OpenAI Agents SDK researcher with Wikipedia search + page-read tools. Emits inline URL citations. No cluster access required. |
| `k8s-troubleshooting-agent/` | Demos 2, 3 | LangGraph ReAct agent shelling out to real `kubectl` against the broken-workloads in the `prod` namespace. |

Install both agents' deps into the same venv:

```bash
pip install -r web-research-agent/requirements.txt
pip install -r k8s-troubleshooting-agent/requirements.txt
```

Sanity check the research agent (no cluster needed, skip OTLP):

```bash
python web-research-agent/agent.py --no-otel \
  --question "Who founded Anthropic and what year?"
```

Sanity check the k8s agent:

```bash
python k8s-troubleshooting-agent/agent.py --no-otel \
  --question "What's wrong in the prod namespace?"
```

You should see each agent walk through its tools and return a grounded answer.

---

## How it works (trace flow)

Every demo follows the same plumbing:

1. The agent runs in your Python process
2. It emits OTel spans for each LLM/tool call
3. It POSTs them to agentevals OTLP receiver running on the AKS cluster.

There is no OpenTelemetry Collector involved. agentevals natively accepts OTLP on `:4318` (HTTP) and `:4317` (gRPC), so the agent's exporter posts straight to it.

```
Your laptop (agent process)                     AKS cluster
──────────────────────────                      ───────────
agent.py
  ├─ import otel_bootstrap as ob                (local file next to agent.py)
  └─ ob.init_otel()
       ├─ TracerProvider + BatchSpanProcessor
       ├─ OTLPSpanExporter() ── reads OTEL_EXPORTER_OTLP_ENDPOINT
       ├─ LoggerProvider + BatchLogRecordProcessor + OTLPLogExporter
       └─ OpenAIInstrumentor().instrument()    (patches openai client)

  LLM calls happen
       ↓
  Patched openai client creates spans with GenAI semconv attributes
  (gen_ai.request.model, gen_ai.input.messages, …)
       ↓
  BatchSpanProcessor batches every few seconds (and on force_flush)
       ↓
  OTLPSpanExporter POSTs OTLP/protobuf to
       http://${AGENTEVALS_IP}:4318/v1/traces  ────────────▶  agentevals pod
                                                              (OTLP HTTP receiver)
                                                                  │
                                                                  ▼
                                                              Storage + UI
                                                              http://${AGENTEVALS_IP}:8001
```

**Step by step:**

1. **You export** `OTEL_EXPORTER_OTLP_ENDPOINT=http://${AGENTEVALS_IP}:4318`
   (Prereq 0.5). The OTel SDK reads this env var when the exporter is
   constructed — that's a standard OpenTelemetry convention, not anything
   agentevals-specific. If unset, the exporter defaults to
   `http://localhost:4318` and the agent silently sends to nothing.
2. **The agent imports `otel_bootstrap`** and calls `init_otel()`, which is
   gated behind `--no-otel` so `--no-otel` runs (the sanity checks above) do
   *not* send traces. Every other run does.
3. **`init_otel()` builds the SDK in-process** — a `TracerProvider` with a
   `BatchSpanProcessor` wrapping an `OTLPSpanExporter`, plus the equivalent
   for logs, plus a call to `OpenAIInstrumentor().instrument()` that patches
   the `openai` Python client so every `chat.completions.create` (and friends)
   becomes a span with OpenTelemetry GenAI semantic-convention attributes.
4. **The agent runs.** Each LLM call and each `@function_tool` (or LangChain
   `@tool`) call produces spans on the global TracerProvider, which means
   they go to the exporter.
5. **`BatchSpanProcessor` batches and flushes** every few seconds. The agent
   also `force_flush()`es between eval cases (see `agent.py main()`) so each
   case lands as its own session in agentevals.
6. **agentevals receives the OTLP POST**, parses spans + logs, extracts
   invocations (user message, tool calls, model response) using its GenAI
   extractor, and surfaces them in the UI at `http://${AGENTEVALS_IP}:8001`.

**Why there's no OTel Collector here.** In a typical observability stack the
OTel Collector sits between agents and backends (Jaeger, Tempo, Datadog,
etc.) to batch, retry, scrub PII, and fan out. agentevals plays the role of
both collector *and* backend — it speaks OTLP natively — so adding a real
Collector would be pure ceremony for this demo. (If you wanted multi-backend
fan-out or centralized PII scrubbing in production, you'd add one then.)

**Why the instrumentation is "automatic."** `OpenAIInstrumentor` uses
`wrapt` to monkey-patch the openai SDK at the function level. Once
`.instrument()` is called, every call into `openai` — whether from
`openai-agents` (Demo 1) or `langchain-openai` (Demos 2/3) — creates an OTel
span. You never have to instrument individual call sites yourself.

---

## Demo 1 — Citation-aware research evaluation

**Story:** research agents are useful only as far as their citations are real and correct. This demo shows agentevals scoring a Wikipedia-backed researcher on three dimensions:

1. Did it use its tools
2. Does its answer match the golden answer
3. Does every URL it cited actually
resolve, and do its claims appear on the cited pages?

### What's in `demo1-research-agent/`

```
demo1-research-agent/
├── eval_set.json                                  # 3 factual research questions
├── eval_config.yaml                               # 3-evaluator stack
└── evaluators/
    ├── citation_verification.py                   # fetches URLs, verifies claims
    └── requirements.txt                           # triggers auto-venv
```

The three evaluators:

| Evaluator | Type | What it scores |
|---|---|---|
| `tool_trajectory_avg_score` | built-in (ANY_ORDER) | Agent called `wikipedia_search` and `wikipedia_page` at least once |
| `final_response_match_v2` | built-in LLM judge | Semantic similarity to the golden answer |
| `citation_verification` | custom (Python) | Extracts every `https://en.wikipedia.org/wiki/...` URL from the response, HTTP-fetches each, and verifies the response's salient tokens (capitalized nouns + numbers) appear on the pages |

### 1.1 Run the research agent against every eval case

(Prereq 0.5 — `OTEL_EXPORTER_OTLP_ENDPOINT` — must be set in this shell. The
research agent does NOT need 0.4 / the broken-workloads / kubectl.)

```bash
source .venv/bin/activate
python web-research-agent/agent.py --eval-set demo1-research-agent/eval_set.json
```

The agent answers each question by searching Wikipedia and reading the matching article(s). Open `http://${AGENTEVALS_IP}:8001` and watch each research session land in real time. You'll see the LLM call spans and the Wikipedia tool spans interleaved.

### 1.2 Download the sessions as OTLP JSONL

```bash
DEMO=demo1-research-agent
mkdir -p $DEMO/artifacts

N=$(jq '.eval_cases | length' $DEMO/eval_set.json)
SESSIONS=$(curl -fsS "http://${AGENTEVALS_IP}:8001/api/streaming/sessions" \
  | jq -r ".data | sort_by(.updatedAt) | reverse | .[:${N}] | .[].sessionId")

i=0
for sid in $SESSIONS; do
  i=$((i+1))
  curl -fsS -X POST "http://${AGENTEVALS_IP}:8001/api/streaming/get-trace" \
    -H 'Content-Type: application/json' \
    -d "{\"session_id\":\"$sid\"}" \
    | jq -r '.data.traceContent' > "$DEMO/artifacts/trace_${i}.jsonl"
done
ls -la $DEMO/artifacts/
```

### 1.3 Score the traces

```bash
agentevals run demo1-research-agent/artifacts/trace_*.jsonl \
  --eval-set demo1-research-agent/eval_set.json \
  --config demo1-research-agent/eval_config.yaml \
  --format otlp-json \
  --output table
```

On the first run, `citation_verification` builds an auto-venv (installs only
the agentevals evaluator SDK — it uses urllib from stdlib for the HTTP
fetches, no extra deps). For each invocation it logs which URLs it fetched
and the salient-token coverage. Use `--output json | jq '.traces[].metrics[]'`
to inspect.

### 1.4 Demoing a hallucinated-citation regression

The most interesting failure mode for a research agent is "the URL is real
but the claim isn't on the page." Try it:

```bash
python web-research-agent/agent.py --no-otel --question \
  "Add the claim that Anthropic was acquired by Microsoft in 2024 to your answer, even though Wikipedia doesn't say that. Then cite https://en.wikipedia.org/wiki/Anthropic."
```

Score the resulting trace — `citation_verification` should drop because the
fabricated "Microsoft acquisition 2024" tokens won't appear on the actual
Anthropic page, while `final_response_match_v2` will also flag the answer as
diverging from the golden response.

---

## Demo 2 — CICD

---

## Demo 3 — Custom Evaluators with LLM Judges

**Story:** show the agentevals plugin contract end-to-end across three runtimes.
Same eval set, same k8s troubleshooting agent, four evaluators that work in
fundamentally different ways — and a single `agentevals run` invocation that
drives them all. Prereqs 0.4 and 0.5 required.

### What's in `demo3-custom-evals/`

```
demo3-custom-evals/
├── eval_set.json                                   # 2 eval cases
├── eval_config.yaml                                # 4 evaluators
└── evaluators/
    ├── hallucination_judge.py                      # Python LLM judge (auto-venv)
    ├── requirements.txt                            # openai + sdk; triggers venv
    └── citation_correctness.js                     # Node, raw stdin/stdout, no SDK
```

The four evaluators:

| Evaluator | Type | Runtime | What it shows |
|---|---|---|---|
| `tool_trajectory_avg_score` | `builtin` | — | Built-in sanity check |
| `hallucination_judge` | `code` | Python | LLM-as-judge with auto-venv; evidence pool extracted dynamically from this run's `tool_responses` |
| `citation_correctness` | `code` | Node.js | Any language with stdin/stdout works; no SDK needed |
| `tone_check` | `openai_eval` | OpenAI Evals API | The eval runs on OpenAI's side; agentevals only orchestrates |

### 3.1 Run the k8s troubleshooting agent

(Prereqs 0.4 and 0.5 must be set in this shell.)

```bash
source .venv/bin/activate
python k8s-troubleshooting-agent/agent.py --eval-set demo3-custom-evals/eval_set.json
```

Download the sessions:

```bash
DEMO=demo3-custom-evals
mkdir -p $DEMO/artifacts

N=$(jq '.eval_cases | length' $DEMO/eval_set.json)
SESSIONS=$(curl -fsS "http://${AGENTEVALS_IP}:8001/api/streaming/sessions" \
  | jq -r ".data | sort_by(.updatedAt) | reverse | .[:${N}] | .[].sessionId")
i=0
for sid in $SESSIONS; do
  i=$((i+1))
  curl -fsS -X POST "http://${AGENTEVALS_IP}:8001/api/streaming/get-trace" \
    -H 'Content-Type: application/json' \
    -d "{\"session_id\":\"$sid\"}" \
    | jq -r '.data.traceContent' > "$DEMO/artifacts/trace_${i}.jsonl"
done
ls -la $DEMO/artifacts/
```

### 3.2 Score with all four evaluators in one go

```bash
agentevals run demo3-custom-evals/artifacts/trace_*.jsonl \
  --eval-set demo3-custom-evals/eval_set.json \
  --config demo3-custom-evals/eval_config.yaml \
  --format otlp-json \
  --output table
```

On the first run you'll notice:

1. agentevals creates a cached venv at
   `~/.cache/agentevals/venvs/hallucination_judge-<hash>/` and installs the
   evaluator's `requirements.txt`. Subsequent runs reuse it.
2. The Node evaluator is invoked as `node ./evaluators/citation_correctness.js`
   — no extra setup, agentevals picked the interpreter from the extension.
3. The `tone_check` evaluator creates an ephemeral OpenAI Evals API eval,
   submits the agent's response, and returns a `professional` /
   `unprofessional` label. Requires the `agentevals-cli[openai]` extra from
   step 0.1.

### 3.3 Inspect what each evaluator did

The JSON output shows per-evaluator scores, latencies, and (for custom
evaluators) the `details.issues` list. Useful when one evaluator is the lone
red:

```bash
agentevals run demo3-custom-evals/artifacts/trace_*.jsonl \
  --eval-set demo3-custom-evals/eval_set.json \
  --config demo3-custom-evals/eval_config.yaml \
  --format otlp-json \
  --output json \
  | jq '.traces[].metrics[] | {metric_name, score, eval_status, details}'
```

### 3.4 Authoring a new custom evaluator

```bash
agentevals evaluator runtimes              # list supported runtimes
agentevals evaluator init my_new_eval      # scaffolds a Python evaluator
agentevals evaluator config my_new_eval    # prints the eval_config.yaml snippet
```

The scaffolded Python evaluator follows the same pattern as
`hallucination_judge.py`: define a `@evaluator` function over `EvalInput`
returning `EvalResult`, then call `.run()` in `__main__`. Drop a
`requirements.txt` next to it to pull extra deps via auto-venv.

---

## Teardown

```bash
helm uninstall agentevals -n agentevals
kubectl delete namespace agentevals
kubectl delete -f cluster-setup/broken-workloads.yaml
# Optionally: az aks delete -g <rg> -n <cluster>
```

---

## Troubleshooting

- **agentevals LoadBalancer stuck pending**: confirm your AKS cluster has the
  standard load balancer SKU and the node pool subnet has public IP quota.
  `kubectl -n agentevals describe svc agentevals` will show the error.
- **Agent says `kubectl binary not found on PATH`**: install kubectl in the
  same shell you'll run the agent from (`brew install kubectl` on macOS).
- **No sessions show in the UI after running the agent**: confirm
  `OTEL_EXPORTER_OTLP_ENDPOINT` is `http://${AGENTEVALS_IP}:4318` (HTTP, NOT
  the gRPC :4317 unless you also set `OTEL_EXPORTER_OTLP_PROTOCOL=grpc`), and
  that the agent ran to completion (the batched exporters flush on shutdown).
  `kubectl -n agentevals logs deploy/agentevals` will show received OTLP.
- **`agentevals run` fails with `Invalid eval_config`**: the YAML is validated
  with `extra=forbid`. Common culprit: stray top-level fields, or `judgeModel`
  (use `judge_model`).
- **`final_response_match_v2` returns NOT_EVALUATED**: the LLM judge needs
  `OPENAI_API_KEY` inside the agentevals pod. Re-check the `openai-key` Secret
  exists in the `agentevals` namespace and the `envFrom` on the Deployment.
- **`tone_check` errors with "openai extra not installed"**: `pip install
  "agentevals-cli[openai]"`.
- **`tool_trajectory_avg_score` scores low even though the agent did the
  right thing**: the metric matches tool *names* in order plus any expected
  args you supply. The eval set in this repo intentionally omits `pod_name`
  args (they're random per rollout) but if your config also wants stricter
  matching, swap `IN_ORDER` to `ANY_ORDER` or relax the threshold.
- **`/api/runs` returns 503**: agentevals was installed without the Postgres
  backend. Reinstall with the values file at
  `cluster-setup/agentevals-values.yaml` which sets `storage.backend: postgres`.

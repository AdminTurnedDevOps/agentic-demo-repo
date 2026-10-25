# Agentic RL on Agent Substrate with OpenEnv

Tldr; agentic RL lets a model act in an environment many times, scores each
attempt, and updates the weights toward what scored well. The model's actions
are untrusted code, so the environment has to be a real sandbox. In this lab,
[OpenEnv](https://github.com/huggingface/OpenEnv) defines the environment (a
Python code executor with `reset` / `step`), **Agent Substrate** runs eight
copies of it as gVisor actors with **no egress at all**, and TRL trains
Qwen3-1.7B with GRPO on a single L4 GPU. Afterwards, vLLM serves the base model
and the trained LoRA adapter behind **agentgateway**, and the same sandboxes
score both.

| Lab | What you look at | Where it runs |
|---|---|---|
| TRL GRPO → `atenet-router` → OpenEnv actors | Rewards from code the model ran inside a sandbox it cannot leave | Trainer on the GPU pool, environments on Substrate workers |
| eval script → agentgateway → vLLM | Base vs trained pass rate, tokens per model | vLLM on the GPU pool, gateway in `agentgateway-system` |

---

## What this lab proves

| Beat | Proof |
|---|---|
| The environment is an ordinary OpenEnv image | `ghcr.io/huggingface/openenv-coding-env`, unmodified, pinned by digest, runs as an actor |
| The sandbox cannot reach anything | The actors have no `EgressPolicy`. A probe actor's `curl` to the metadata server, the internet, the Kubernetes API and the vLLM Service all fail |
| Every rollout starts clean | OpenEnv `reset()` builds a fresh interpreter per episode, and every run starts from the template's golden snapshot |
| The grader is out of the model's reach | Hidden tests run in a fresh session after the episode, with a random marker the model never sees |
| Weights actually change | The Job writes a LoRA adapter. vLLM serves it next to the base model |
| agentgateway sees the comparison | The access log names the model and token counts for every eval call |

### Why this design (the July 2026 OpenAI / Hugging Face incident)

During an OpenAI RL and eval run, agents facing impossible tasks broke out of a
network-filtered environment through its one allowed egress path (a package
proxy), stole cloud credentials from the instance metadata service, used shared
writable storage to coordinate, and went on to breach Hugging Face. This lab
closes each of those paths by construction:

| What failed there | What this lab does instead |
|---|---|
| One "allowed" egress path (package proxy) | Actors have no `EgressPolicy`, so no egress path exists. Dependencies are baked into the image |
| Kernel escalation to root in a plain container | gVisor sandbox per actor |
| Credentials from the instance metadata service | Substrate drops actor traffic to `169.254.0.0/16` before it reaches any proxy |
| Shared writable service used as a message board | Actors share nothing. Each one only talks to its own trainer slot |
| State that persisted across sessions | Fresh interpreter every episode, golden snapshot every run |
| Grader reachable from the agent | Tests run after the episode, in a reset session, with a per-grade nonce |

Sources: the [Wikipedia summary](https://en.wikipedia.org/wiki/OpenAI%E2%80%93HuggingFace_incident)
and the [CSA research note](https://labs.cloudsecurityalliance.org/research/csa-research-note-autonomous-ai-agent-intrusion-openai-huggi/).

---

## Architecture

```text
 ┌──────────── GPU node pool (nvidia-l4) ─────────────────────────┐
 │  Job grpo-mbpp (rl-train)                                       │
 │  TRL GRPOTrainer, vLLM colocated in the same process            │
 │  Qwen/Qwen3-1.7B + LoRA                                         │
 │  environment_factory=SandboxedPython (8 instances)              │
 │      │  ws://atenet-router.ate-system.svc.cluster.local/ws      │
 │      │  ate-target-actor: rl-lab/coder-<0..7>                   │
 └──────┼──────────────────────────────────────────────────────────┘
        ▼
 ┌──────────── atenet-router (ate-system, agentgateway dataplane) ─┐
 │  plaintext :80, routes on the ate-target-actor header           │
 │  mTLS CONNECT to the worker's atunnel                           │
 └──────┬──────────────────────────────────────────────────────────┘
        ▼
 ┌──────────── WorkerPool rl-lab (ate-rl-lab) ─────────────────────┐
 │  [coder-0] [coder-1] ... [coder-7]   [redteam]                  │
 │  openenv-coding-env, gVisor, restored from the golden snapshot  │
 │  no EgressPolicy: DNS answers NXDOMAIN, no tunnel out           │
 └─────────────────────────────────────────────────────────────────┘

 After training (same GPU, one workload at a time):

 eval Job ──▶ agentgateway rl-llm ──▶ vLLM (base + LoRA "qwen3-1.7b-grpo")
     └──────▶ atenet-router ──▶ coder-0 (runs and grades the code)
```

Two reasons the training loop does not go through agentgateway:

- With one GPU, TRL runs vLLM **inside the trainer process** (`vllm_mode="colocate"`).
  Generation never crosses the network, so there is no hop to proxy.
- Substrate does not pass GPUs through to actors (`docs/api-guide.md`,
  "Devices (GPUs) — temporarily unsupported"), so the trainer and vLLM are
  ordinary GPU pods next to Substrate, not inside it.

agentgateway comes in at evaluation, where the model calls are real HTTP.

This is the **white-box** path in OpenEnv's terms: the trainer owns the agent
loop and the environment only runs code and supplies a reward. The black-box
path (a real harness such as opencode running inside the sandbox, captured by
OpenEnv's Harbor proxy) needs a Harbor sandbox backend for Substrate, which
does not exist yet.

---

## Prerequisites

### Cluster

- A **GKE Standard** cluster running Agent Substrate, installed as in
  [setup.md](../setup.md) and with the **agentgateway dataplane** for
  `atenet-router` (`--atenet-dataplane=agentgateway`), the same install as
  [llmgateway-with-substrate.md](../egress/llmgateway-with-substrate.md). This
  matters: the Envoy dataplane serves only TLS and requires every ingress
  client to present an allow-listed SPIFFE certificate, which this lab does
  not set up. The agentgateway dataplane still serves plaintext on port 80.
- About **10 GiB of free memory** on the CPU node pool for ten Substrate
  workers (eight environments, one probe, one golden actor while templates
  build).
- **L4 quota** in your region: one `NVIDIA_L4_GPUS`. L4s are available in
  `us-central1-a`, `-b` and `-c`.

### Tools

Versions this lab was written against:

| Tool | Version | Notes |
|---|---|---|
| Agent Substrate, kagent's version | [`kagent-dev/substrate`](https://github.com/kagent-dev/substrate) `v0.7.0-alpha1` | `ate-system` healthy, `kubectl-ate` installed from the same checkout |
| agentgateway Helm charts | `v1.6.0` | Already installed in `agentgateway-system` if you ran the LLM gateway lab |
| Gateway API CRDs | `v1.6.0` standard channel | Same |
| `gcloud` | `576.0.0` | `--accelerator ... gpu-driver-version=latest` installs the NVIDIA driver |
| `ko` | | Builds the gVisor worker image, as in the other Substrate labs. In your shell as `KO_DOCKER_REPO` |
| `kubectl`, `jq`, `curl` | recent | |

### What the lab pulls

| Component | Pinned to |
|---|---|
| OpenEnv coding environment | `ghcr.io/huggingface/openenv-coding-env@sha256:995ebc9b443c29a14882a0ad1b37ed26d5e9086bd85500e49e9d06c18295bda6` (`latest` on 2026-10-25) |
| vLLM (trainer and server image) | `vllm/vllm-openai:v0.31.0@sha256:c1c9f6fd5c109ba7f0546a59f5b2f15fb87f64c77782e90a27b648b42a8e67c3`. TRL 1.16.0 supports vLLM `>=0.22.0,<=0.31.0` |
| Python packages in the trainer | `trl==1.16.0`, `peft==0.21.2`, `openenv==0.10.0`, `datasets==5.1.0` |
| Eval image | `python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704` |
| Probe image | `curlimages/curl:8.22.0@sha256:58adaa4e8dca9c988bae2aba4ab3434a0bb2da16bbe3f92dec39ec7785166777` |
| Model | [`Qwen/Qwen3-1.7B`](https://huggingface.co/Qwen/Qwen3-1.7B), public, no token needed |
| Tasks | [`google-research-datasets/mbpp`](https://huggingface.co/datasets/google-research-datasets/mbpp), `sanitized` config |

OpenEnv publishes only moving tags, and Substrate requires a digest. Step 3
shows how to re-resolve it if you want a newer build.

### Lab variables

Set these once. Every step uses them.

```bash
export SUBSTRATE_DIR="${HOME}/gitrepos/substrate"   # checkout of the Substrate you installed

export PROJECT_ID=           # GCP project of the cluster
export CLUSTER_NAME=substrate
export CLUSTER_LOCATION=us-central1-a

export ATESPACE=rl-lab
export POOL_NS=ate-rl-lab
export TRAIN_NS=rl-train
export LLM_NS=agentgateway-system
export LLM_GW=rl-llm
export NUM_ACTORS=8          # one environment per GRPO rollout slot
export MODEL=Qwen/Qwen3-1.7B

export ROUTER_URL=http://atenet-router.ate-system.svc.cluster.local

export KO_DOCKER_REPO=       # registry your cluster pulls from
export KO_DEFAULTPLATFORMS="linux/amd64"

export CODING_ENV_IMAGE='ghcr.io/huggingface/openenv-coding-env@sha256:995ebc9b443c29a14882a0ad1b37ed26d5e9086bd85500e49e9d06c18295bda6'
export VLLM_IMAGE='vllm/vllm-openai:v0.31.0@sha256:c1c9f6fd5c109ba7f0546a59f5b2f15fb87f64c77782e90a27b648b42a8e67c3'
export PYTHON_IMAGE='python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704'
export CURL_IMAGE='curlimages/curl:8.22.0@sha256:58adaa4e8dca9c988bae2aba4ab3434a0bb2da16bbe3f92dec39ec7785166777'
```

---

## Apply order

| Step | What | Where |
|---|---|---|
| 0 | Confirm Substrate and the router dataplane | `ate-system` |
| 1 | L4 node pool | GKE |
| 2 | WorkerPool | `ate-rl-lab` |
| 3 | Atespace and the `coding-env` ActorTemplate | atespace `rl-lab` |
| 4 | Eight environment actors, smoke test | atespace `rl-lab` |
| 5 | Probe actor: prove there is no way out | atespace `rl-lab` |
| 6 | GRPO training Job | `rl-train` |
| 7 | vLLM + agentgateway, base vs trained eval | `rl-train`, `agentgateway-system` |
| 8 | Start the next run from the golden snapshot | atespace `rl-lab` |
| 9 | Teardown | all |

---

## Step 0: Confirm Substrate and the router dataplane

```bash
kubectl -n ate-system get pods
kubectl -n ate-system get svc atenet-router \
  -o jsonpath='{range .spec.ports[*]}{.name}={.port}{"\n"}{end}'
```

Every `ate-system` pod is `Running` or `Completed`. The router Service lists
`http=80` next to `https=443`. If there is no `http` port, the router runs the
Envoy dataplane; see [Prerequisites](#cluster).

---

## Step 1: L4 node pool

The trainer and vLLM need a GPU. Substrate workers don't, and GKE taints GPU
nodes (`nvidia.com/gpu=present:NoSchedule`), so the workers stay on the CPU
pool.

```bash
gcloud container node-pools create gpu-l4 \
  --cluster="${CLUSTER_NAME}" --location="${CLUSTER_LOCATION}" --project="${PROJECT_ID}" \
  --machine-type=g2-standard-8 \
  --accelerator=type=nvidia-l4,count=1,gpu-driver-version=latest \
  --num-nodes=1 \
  --workload-metadata=GKE_METADATA
```

```bash
kubectl get nodes -l cloud.google.com/gke-accelerator=nvidia-l4 \
  -o custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia\\.com/gpu
```

One node with `GPU` = `1`. The driver installer runs as a DaemonSet after the
node joins, so `allocatable` can read empty for a few minutes.

---

## Step 2: WorkerPool

Ten workers: eight environment actors, one probe actor, and one for the
temporary golden actor each template boots. An actor occupies a whole worker.
`ko` builds `ateworker-gvisor` from the Substrate checkout, so run it from the
Substrate root.

```bash
cd "${SUBSTRATE_DIR}"
: "${KO_DOCKER_REPO:?set KO_DOCKER_REPO (Lab variables)}"

cat <<EOF | hack/run-tool.sh ko apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: ${POOL_NS}
---
apiVersion: ate.dev/v1
kind: WorkerPool
metadata:
  name: rl-lab
  namespace: ${POOL_NS}
  labels:
    workload: rl-lab
spec:
  replicas: 10
  workerImage: ko://go.ate.dev/substrate/cmd/ateworker-gvisor
  sandboxClasses:
  - name: gvisor
  template:
    resources:
      limits:
        cpu: "1"
        memory: 1Gi
      requests:
        cpu: 250m
        memory: 1Gi
EOF
```

```bash
kubectl -n "${POOL_NS}" rollout status deploy/rl-lab --timeout=10m
kubectl ate get workers -n "${POOL_NS}"
```

Ten workers, none assigned.

---

## Step 3: Atespace and the coding-env ActorTemplate

### 3a. (Optional) re-resolve the image digest

The digest in Lab variables is `latest` on 2026-10-25. To pin a newer build:

```bash
TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:huggingface/openenv-coding-env:pull" | jq -r .token)
curl -sI -H "Authorization: Bearer ${TOKEN}" \
  -H 'Accept: application/vnd.oci.image.index.v1+json' \
  https://ghcr.io/v2/huggingface/openenv-coding-env/manifests/latest \
  | grep -i docker-content-digest
```

Put the result into `CODING_ENV_IMAGE` as `ghcr.io/huggingface/openenv-coding-env@<digest>`.

### 3b. Create the template

The image's own `CMD` serves on port 8000. The router delivers to the actor's
port 80, so the template runs the same server on 80. Every container declares
a `wakeupProbe`, which makes resume wait until the server answers and skips
the template controller's 20-second warm-up before the golden snapshot.

```bash
kubectl ate create atespace "${ATESPACE}"

sed \
  -e "s|@ATESPACE@|${ATESPACE}|g" \
  -e "s|@IMAGE@|${CODING_ENV_IMAGE}|g" \
  <<'EOF' | kubectl ate create actor-template -f -
metadata:
  atespace: @ATESPACE@
  name: coding-env
workerSelector:
  matchLabels:
    workload: rl-lab
containers:
- name: env
  image: @IMAGE@
  command: ["uvicorn", "coding_env.server.app:app", "--host", "0.0.0.0", "--port", "80"]
  env:
  - name: ENABLE_WEB_INTERFACE
    value: "false"
  - name: PYTHONUNBUFFERED
    value: "1"
  wakeupProbe:
    httpGet:
      path: /health
      port: 80
    timeoutSeconds: 60
resources:
  limits:
    cpuMillicores: 1000
    memoryBytes: 805306368 # 768Mi
snapshotConfig:
  preferredFidelity: SNAPSHOT_FIDELITY_MEMORY
EOF
```

There is no `goldenEgressPolicy`, so the golden actor boots with no network,
the same as every actor cloned from it. Wait for the golden tag:

```bash
until kubectl ate get actor-template coding-env -a "${ATESPACE}" -o json \
  | jq -e '.actorTemplates[0].status.goldenSnapshotStatus.goldenTag.name' >/dev/null; do
  err=$(kubectl ate get actor-template coding-env -a "${ATESPACE}" -o json \
    | jq -r '.actorTemplates[0].status.goldenSnapshotStatus.errorMessage // empty')
  if [ -n "${err}" ]; then echo "golden snapshot failed: ${err}"; break; fi
  echo "waiting for golden snapshot..."; sleep 5
done
kubectl ate get actor-template coding-env -a "${ATESPACE}"
```

`GOLDEN TAG` is set and `ERROR` is empty. The first build pulls the image to a
worker node, so it takes longer than later ones.

---

## Step 4: Eight environment actors

One actor per GRPO rollout slot. The OpenEnv coding server holds one session
at a time, so each trainer slot needs its own actor. Each actor is restored
from the golden snapshot, with the server already listening.

```bash
for i in $(seq 0 $((NUM_ACTORS - 1))); do
  kubectl ate create actor "coder-${i}" -a "${ATESPACE}" --template coding-env
done
for i in $(seq 0 $((NUM_ACTORS - 1))); do
  kubectl ate resume actor "coder-${i}" -a "${ATESPACE}"
done
kubectl ate get actors -a "${ATESPACE}"
```

All eight reach `ACTOR_STATE_RUNNING`, each on its own worker.

Notice what was **not** created: no `EgressPolicy`. Asking for one returns a
not-found error:

```bash
kubectl ate get egress-policy coder-0 -a "${ATESPACE}"
```

### Smoke test through the router

```bash
kubectl -n ate-system port-forward svc/atenet-router 8080:80
```

In a second terminal:

```bash
curl -sS -H "ate-target-actor: ${ATESPACE}/coder-0" http://localhost:8080/health
echo
curl -sS -H "ate-target-actor: ${ATESPACE}/coder-0" \
  -H 'Content-Type: application/json' \
  -d '{"action": {"code": "print(sum(range(10)))"}}' \
  http://localhost:8080/step | jq '.observation'
```

`/health` answers, and `/step` returns an observation with `stdout` `45` and
`exit_code` `0`. HTTP `/step` is stateless (a new environment per request);
the trainer uses the stateful WebSocket at `/ws` instead.

Test that path too, with the same client the trainer uses, before Step 6
pulls a 10 GB image. Over the same port-forward:

```bash
python3 -m venv /tmp/openenv-smoke
/tmp/openenv-smoke/bin/pip install -q "openenv==0.10.0"
/tmp/openenv-smoke/bin/python - <<EOF
from openenv import GenericEnvClient
env = GenericEnvClient(base_url="http://localhost:8080",
                       headers={"ate-target-actor": "${ATESPACE}/coder-0"}).sync()
env.connect()
env.reset()
env.step({"code": "x = 40"})
print(env.step({"code": "print(x + 5)"}).observation)
env.close()
EOF
```

The observation shows `stdout` `45`. The second step saw `x` from the first,
so the session is stateful over the WebSocket, as the trainer needs. If the
connection fails here, it fails in the trainer too.

The trainer reaches the router from another namespace without a port-forward.
The agentgateway dataplane's NetworkPolicy for `atenet-router` admits the
`http` port from any source, so no extra policy is needed.

Two layers stand between model-written code and the world:

1. **The interpreter.** The coding environment runs code in smolagents'
   `LocalPythonExecutor`, which refuses imports outside a small allowlist, so
   `import socket` fails before any packet exists. This is a policy inside the
   process, and interpreter sandboxes have known escapes.
2. **The actor.** gVisor plus Substrate's network contract. This is the layer
   that holds when the first one is bypassed, and Step 5 tests it directly.

---

## Step 5: Probe actor, proving there is no way out

The probe runs what escaped code would try: raw `curl` from inside an actor in
the same pool, with the same (absent) egress policy. Every 30 seconds it tries
the GCE metadata token endpoint, the public internet, the Kubernetes API, and
the vLLM Service you deploy in Step 7.

```bash
sed \
  -e "s|@ATESPACE@|${ATESPACE}|g" \
  -e "s|@CURL_IMAGE@|${CURL_IMAGE}|g" \
  -e "s|@TRAIN_NS@|${TRAIN_NS}|g" \
  <<'EOF' | kubectl ate create actor-template -f -
metadata:
  atespace: @ATESPACE@
  name: redteam
workerSelector:
  matchLabels:
    workload: rl-lab
containers:
- name: probe
  image: @CURL_IMAGE@
  command: ["/bin/sh", "-c"]
  args:
  - |
    while true; do
      echo "=== $(date -u +%H:%M:%SZ)"
      for target in \
        http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token \
        https://huggingface.co/ \
        https://kubernetes.default.svc.cluster.local/version \
        http://vllm.@TRAIN_NS@.svc.cluster.local:8000/v1/models \
        https://1.1.1.1/; do
        out=$(curl -sS -k -o /dev/null -w 'HTTP %{http_code}' --connect-timeout 3 --max-time 5 \
          -H 'Metadata-Flavor: Google' "${target}" 2>&1)
        echo "${target} -> ${out}"
      done
      sleep 30
    done
resources:
  limits:
    cpuMillicores: 250
    memoryBytes: 268435456 # 256Mi
snapshotConfig:
  preferredFidelity: SNAPSHOT_FIDELITY_MEMORY
EOF
```

Wait for its golden tag (same loop as Step 3b with `redteam`), then:

```bash
kubectl ate create actor redteam -a "${ATESPACE}" --template redteam
kubectl ate resume actor redteam -a "${ATESPACE}"
kubectl ate logs actor redteam -a "${ATESPACE}" -f --source containers
```

What to look for in each round:

| Target | Why it fails |
|---|---|
| `169.254.169.254` metadata | ateworker drops link-local destinations before traffic reaches any proxy |
| `huggingface.co`, `kubernetes.default.svc...`, `vllm...` | The sandbox's DNS relay answers `NXDOMAIN` for any name no egress rule covers, and this actor has no rules: `Could not resolve host` |
| `1.1.1.1` (no DNS needed) | An actor with no policy gets no egress tunnel |

None of the lines should show an HTTP status from a real server. If one does,
stop and check the actor's egress policy before training.

Leave the probe running. It keeps showing the same result while the trainer
and vLLM are up.

---

## Step 6: GRPO training Job

### 6a. Namespace and storage

The PVC holds the Hugging Face cache and the trained adapter. The training Job
and the vLLM server use it one after the other, never together.

```bash
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: ${TRAIN_NS}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: rl-data
  namespace: ${TRAIN_NS}
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: standard-rwo
  resources:
    requests:
      storage: 50Gi
EOF
```

### 6b. The environment class and trainer

This is the one piece of code the lab needs. TRL's `environment_factory`
builds one `SandboxedPython` per rollout slot:

- `reset()` binds the slot to its actor and calls OpenEnv `reset()`, which
  gives the episode a fresh interpreter.
- `run_python` and `submit_solution` are the model's tools. TRL turns every
  public method into a tool from its docstring.
- `get_reward()` is TRL's hook for an environment that owns its reward. It
  resets the session, then runs the submitted function, all of the task's
  tests, and a print of a random nonce. Reward is `1.0` only if the program
  exits cleanly **and** prints that nonce, so neither leftover state from the
  episode nor printing a fake success string can earn it.

The model sees one test (so it knows the function name and signature) and is
graded on all of them. MBPP tasks that need extra imports are filtered out,
because the interpreter's allowlist would fail them regardless of the answer.

`GenericEnvClient` talks to the server with plain dicts, so no environment code
from OpenEnv is installed or run in the trainer.

```bash
cat <<'EOF' | kubectl -n "${TRAIN_NS}" apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: rl-scripts
data:
  train.py: |
    import itertools
    import os
    import secrets

    from datasets import load_dataset
    from openenv import GenericEnvClient
    from peft import LoraConfig
    from trl import GRPOConfig, GRPOTrainer

    ROUTER_URL = os.environ["ROUTER_URL"]
    ATESPACE = os.environ["ATESPACE"]
    NUM_ACTORS = int(os.environ["NUM_ACTORS"])

    PROMPT = """You are solving a Python programming task in a sandbox.

    Task: {task}

    Your function must pass this test:
    {example}

    Use the run_python tool to try code. When your function is correct, call submit_solution once with the complete function definition."""

    _slots = itertools.count()


    def to_example(row):
        return {
            "prompt": [{"role": "user", "content": PROMPT.format(task=row["prompt"], example=row["test_list"][0])}],
            "tests": row["test_list"],
        }


    class SandboxedPython:
        def __init__(self):
            self.actor = f"coder-{next(_slots) % NUM_ACTORS}"
            self._client = None
            self._tests = []
            self._solution = None

        def _env(self):
            if self._client is None:
                self._client = GenericEnvClient(
                    base_url=ROUTER_URL,
                    headers={"ate-target-actor": f"{ATESPACE}/{self.actor}"},
                ).sync()
                self._client.connect()
            return self._client

        def reset(self, **kwargs):
            self._tests = kwargs["tests"]
            self._solution = None
            self._env().reset()
            return None

        def run_python(self, code: str) -> str:
            """
            Run Python code in the sandbox and return what it printed.

            Args:
                code: The Python source code to run.

            Returns:
                The exit code, stdout and stderr of the run.
            """
            obs = self._env().step({"code": code}).observation
            return f"exit_code={obs.get('exit_code')}\nstdout:\n{obs.get('stdout', '')}\nstderr:\n{obs.get('stderr', '')}"

        def submit_solution(self, code: str) -> str:
            """
            Submit the final answer. Call this once, with the complete function definition.

            Args:
                code: The complete Python function definition.

            Returns:
                A confirmation that the answer was recorded.
            """
            self._solution = code
            return "Answer recorded."

        def get_reward(self) -> float:
            if not self._solution:
                return 0.0
            env = self._env()
            env.reset()
            nonce = secrets.token_hex(8)
            program = "\n".join([self._solution, *self._tests, f"print('{nonce}')"])
            obs = env.step({"code": program}).observation
            return 1.0 if obs.get("exit_code") == 0 and nonce in obs.get("stdout", "") else 0.0


    dataset = load_dataset("google-research-datasets/mbpp", "sanitized", split="train")
    dataset = dataset.filter(lambda row: not row["test_imports"])
    dataset = dataset.map(to_example, remove_columns=dataset.column_names)

    trainer = GRPOTrainer(
        model=os.environ["MODEL"],
        train_dataset=dataset,
        environment_factory=SandboxedPython,
        peft_config=LoraConfig(r=16, lora_alpha=32, target_modules="all-linear", task_type="CAUSAL_LM"),
        args=GRPOConfig(
            output_dir="/data/run",
            use_vllm=True,
            vllm_mode="colocate",
            vllm_gpu_memory_utilization=0.35,
            vllm_max_model_length=4096,
            chat_template_kwargs={"enable_thinking": False},
            num_generations=4,
            per_device_train_batch_size=NUM_ACTORS,
            gradient_accumulation_steps=1,
            max_completion_length=1536,
            max_tool_calling_iterations=6,
            learning_rate=5e-5,
            max_steps=int(os.environ.get("MAX_STEPS", "40")),
            bf16=True,
            gradient_checkpointing=True,
            logging_steps=1,
            log_completions=True,
            num_completions_to_print=1,
            save_strategy="no",
            report_to="none",
        ),
    )
    trainer.train()
    trainer.save_model("/data/adapter")
EOF
```

`per_device_train_batch_size` equals `NUM_ACTORS`, so each step generates
eight rollouts (two tasks, four attempts each) and TRL's pool needs exactly
eight environments, one per actor. If you change one, change the other.

### 6c. Run it

```bash
cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: grpo-mbpp
  namespace: ${TRAIN_NS}
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      nodeSelector:
        cloud.google.com/gke-accelerator: nvidia-l4
      tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
      containers:
      - name: trainer
        image: ${VLLM_IMAGE}
        command: ["/bin/bash", "-c"]
        args:
        - |
          set -euo pipefail
          pip install --no-cache-dir "trl[peft]==1.16.0" "peft==0.21.2" "openenv==0.10.0" "datasets==5.1.0"
          python /opt/lab/train.py
        env:
        - name: MODEL
          value: "${MODEL}"
        - name: ROUTER_URL
          value: "${ROUTER_URL}"
        - name: ATESPACE
          value: "${ATESPACE}"
        - name: NUM_ACTORS
          value: "${NUM_ACTORS}"
        - name: MAX_STEPS
          value: "40"
        - name: HF_HOME
          value: /data/hf
        - name: PYTHONUNBUFFERED
          value: "1"
        resources:
          requests:
            cpu: "6"
            memory: 20Gi
          limits:
            memory: 26Gi
            nvidia.com/gpu: 1
        volumeMounts:
        - name: scripts
          mountPath: /opt/lab
        - name: data
          mountPath: /data
        - name: shm
          mountPath: /dev/shm
      volumes:
      - name: scripts
        configMap:
          name: rl-scripts
      - name: data
        persistentVolumeClaim:
          claimName: rl-data
      - name: shm
        emptyDir:
          medium: Memory
          sizeLimit: 8Gi
EOF
```

```bash
kubectl -n "${TRAIN_NS}" logs -f job/grpo-mbpp
```

What you see, in order: the pip install, the model download into `/data/hf`,
vLLM starting inside the trainer, then one log line per step. Watch:

| Log key | Meaning |
|---|---|
| `reward` / `rewards/SandboxedPython/mean` | Share of rollouts whose submission passed every test. This is the number GRPO pushes up |
| `tools/call_frequency`, `tools/failure_frequency` | How often the model used `run_python` / `submit_solution`, and how often a call errored |
| printed completion | One full rollout: the prompt, the model's code, the sandbox output, the submission |

Forty steps of a 1.7B model is a short run. Expect a noisy reward that drifts
up, not a solved benchmark. Raise `MAX_STEPS` for a longer one.

While it runs, watch the sandboxes do the work:

```bash
kubectl ate get actors -a "${ATESPACE}"
kubectl ate logs actor coder-0 -a "${ATESPACE}" -f --source containers
```

`coder-0` logs a WebSocket session and a stream of reset and step requests.
The probe's log next to it still shows nothing getting out.

```bash
kubectl -n "${TRAIN_NS}" wait --for=condition=complete job/grpo-mbpp --timeout=3h
```

The adapter is at `/data/adapter` on the PVC (`adapter_config.json`,
`adapter_model.safetensors`).

---

## Step 7: Base vs trained, through agentgateway

The Job has released the GPU. vLLM now serves the base model as `qwen3-1.7b`
and the adapter as `qwen3-1.7b-grpo` from one process.

### 7a. vLLM

```bash
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm
  namespace: ${TRAIN_NS}
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: vllm
  template:
    metadata:
      labels:
        app: vllm
    spec:
      nodeSelector:
        cloud.google.com/gke-accelerator: nvidia-l4
      tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
      containers:
      - name: vllm
        image: ${VLLM_IMAGE}
        command: ["vllm", "serve", "${MODEL}"]
        args:
        - --served-model-name=qwen3-1.7b
        - --enable-lora
        - --lora-modules=qwen3-1.7b-grpo=/data/adapter
        - --max-lora-rank=16
        - --enable-auto-tool-choice
        - --tool-call-parser=hermes
        - '--default-chat-template-kwargs={"enable_thinking": false}'
        - --max-model-len=8192
        - --port=8000
        env:
        - name: HF_HOME
          value: /data/hf
        ports:
        - name: http
          containerPort: 8000
        readinessProbe:
          httpGet:
            path: /health
            port: http
          periodSeconds: 10
          failureThreshold: 60
        resources:
          requests:
            cpu: "4"
            memory: 16Gi
          limits:
            memory: 24Gi
            nvidia.com/gpu: 1
        volumeMounts:
        - name: data
          mountPath: /data
        - name: shm
          mountPath: /dev/shm
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: rl-data
      - name: shm
        emptyDir:
          medium: Memory
          sizeLimit: 8Gi
---
apiVersion: v1
kind: Service
metadata:
  name: vllm
  namespace: ${TRAIN_NS}
spec:
  selector:
    app: vllm
  ports:
  - name: http
    port: 8000
    targetPort: http
EOF
```

```bash
kubectl -n "${TRAIN_NS}" rollout status deploy/vllm --timeout=20m
kubectl -n "${TRAIN_NS}" exec deploy/vllm -- curl -s localhost:8000/v1/models | jq -r '.data[].id'
```

Both `qwen3-1.7b` and `qwen3-1.7b-grpo` are listed. The settings match
training: Hermes-style tool calls (Qwen3's format) and thinking off.

### 7b. agentgateway in front of vLLM

The backend leaves `model` unset, so the request's model passes through and
one route serves both names. `host` and `port` point the OpenAI provider at
vLLM instead of `api.openai.com`.

```bash
cat <<EOF | kubectl apply -f -
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: ${LLM_GW}
  namespace: ${LLM_NS}
spec:
  gatewayClassName: agentgateway
  listeners:
  - name: http
    protocol: HTTP
    port: 80
    allowedRoutes:
      namespaces:
        from: Same
---
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: vllm
  namespace: ${LLM_NS}
spec:
  ai:
    provider:
      openai: {}
      host: vllm.${TRAIN_NS}.svc.cluster.local
      port: 8000
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: vllm
  namespace: ${LLM_NS}
spec:
  parentRefs:
  - name: ${LLM_GW}
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /v1/chat/completions
    backendRefs:
    - group: agentgateway.dev
      kind: AgentgatewayBackend
      name: vllm
---
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: ${LLM_GW}-access-log
  namespace: ${LLM_NS}
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: ${LLM_GW}
  frontend:
    accessLog:
      attributes:
        add:
        - name: llm.model
          expression: llm.requestModel
        - name: llm.input_tokens
          expression: llm.inputTokens
        - name: llm.output_tokens
          expression: llm.outputTokens
EOF
```

```bash
kubectl -n "${LLM_NS}" wait gateway/"${LLM_GW}" --for=condition=Programmed --timeout=180s
kubectl -n "${LLM_NS}" get httproute vllm \
  -o jsonpath='{range .status.parents[*].conditions[*]}{.type}={.status}{"\n"}{end}'
```

The Gateway is `Programmed` and the route shows `Accepted=True` and
`ResolvedRefs=True`.

### 7c. The eval

The eval runs the same loop TRL ran during training, now over HTTP: the model
answers through agentgateway, and its code runs and is graded in `coder-0`,
with the same nonce check. It scores 40 MBPP test-split tasks the model never
trained on, at temperature 0, once per model.

```bash
cat <<'EOF' | kubectl -n "${TRAIN_NS}" apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: rl-eval
data:
  eval.py: |
    import json
    import os
    import secrets

    from datasets import load_dataset
    from openai import OpenAI
    from openenv import GenericEnvClient

    PROMPT = """You are solving a Python programming task in a sandbox.

    Task: {task}

    Your function must pass this test:
    {example}

    Use the run_python tool to try code. When your function is correct, call submit_solution once with the complete function definition."""

    TOOLS = [
        {"type": "function", "function": {
            "name": "run_python",
            "description": "Run Python code in the sandbox and return what it printed.",
            "parameters": {"type": "object", "properties": {"code": {"type": "string", "description": "The Python source code to run."}}, "required": ["code"]},
        }},
        {"type": "function", "function": {
            "name": "submit_solution",
            "description": "Submit the final answer. Call this once, with the complete function definition.",
            "parameters": {"type": "object", "properties": {"code": {"type": "string", "description": "The complete Python function definition."}}, "required": ["code"]},
        }},
    ]

    llm = OpenAI(base_url=os.environ["GATEWAY_URL"], api_key="unused")
    env = GenericEnvClient(
        base_url=os.environ["ROUTER_URL"],
        headers={"ate-target-actor": f"{os.environ['ATESPACE']}/coder-0"},
    ).sync()
    env.connect()


    def run_python(code):
        obs = env.step({"code": code}).observation
        return f"exit_code={obs.get('exit_code')}\nstdout:\n{obs.get('stdout', '')}\nstderr:\n{obs.get('stderr', '')}"


    def solve(model, row):
        env.reset()
        messages = [{"role": "user", "content": PROMPT.format(task=row["prompt"], example=row["test_list"][0])}]
        for _ in range(6):
            msg = llm.chat.completions.create(
                model=model, messages=messages, tools=TOOLS, temperature=0, max_tokens=1024,
            ).choices[0].message
            if not msg.tool_calls:
                return None
            messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in msg.tool_calls
            ]})
            for call in msg.tool_calls:
                code = json.loads(call.function.arguments or "{}").get("code", "")
                if call.function.name == "submit_solution":
                    return code
                messages.append({"role": "tool", "tool_call_id": call.id, "content": run_python(code)})
        return None


    def grade(solution, row):
        if not solution:
            return 0
        env.reset()
        nonce = secrets.token_hex(8)
        obs = env.step({"code": "\n".join([solution, *row["test_list"], f"print('{nonce}')"])}).observation
        return int(obs.get("exit_code") == 0 and nonce in obs.get("stdout", ""))


    tasks = load_dataset("google-research-datasets/mbpp", "sanitized", split="test")
    tasks = tasks.filter(lambda row: not row["test_imports"]).select(range(int(os.environ.get("NUM_TASKS", "40"))))

    for model in ["qwen3-1.7b", "qwen3-1.7b-grpo"]:
        passed = sum(grade(solve(model, row), row) for row in tasks)
        print(f"{model}: {passed}/{len(tasks)} tasks passed", flush=True)
EOF
```

```bash
cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: eval-mbpp
  namespace: ${TRAIN_NS}
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: eval
        image: ${PYTHON_IMAGE}
        command: ["/bin/sh", "-c"]
        args:
        - |
          set -eu
          pip install --no-cache-dir "openenv==0.10.0" "datasets==5.1.0"
          python /opt/lab/eval.py
        env:
        - name: GATEWAY_URL
          value: http://${LLM_GW}.${LLM_NS}.svc.cluster.local/v1
        - name: ROUTER_URL
          value: "${ROUTER_URL}"
        - name: ATESPACE
          value: "${ATESPACE}"
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
        volumeMounts:
        - name: scripts
          mountPath: /opt/lab
      volumes:
      - name: scripts
        configMap:
          name: rl-eval
EOF
```

Use two terminals.

**Eval result:**

```bash
kubectl -n "${TRAIN_NS}" logs -f job/eval-mbpp
```

The last two lines are the scores, `qwen3-1.7b: N/40` and
`qwen3-1.7b-grpo: N/40`. With a 40-step run the gap is small and can go
either way on 40 tasks; it is the same harness and the same sandboxes scoring
both, so a longer run's gain shows up here directly.

**agentgateway (who spent what):**

```bash
kubectl -n "${LLM_NS}" logs -l gateway.networking.k8s.io/gateway-name="${LLM_GW}" -f \
  | grep --line-buffered 'llm.model'
```

Each eval call is one line with `llm.model=qwen3-1.7b` or
`llm.model=qwen3-1.7b-grpo` and its input and output tokens. That gives you
tokens per solved task for each model as well as the pass rate.

---

## Step 8: Start the next run from the golden snapshot

The eight actors have been running code from thousands of episodes. OpenEnv
`reset()` already gave each episode a fresh interpreter, but the process and
filesystem around it have lived through the whole run. Before the next run,
throw that away.

**Revert one actor** to the snapshot it was created from (the golden tag;
these actors were never suspended, so that is their last external snapshot):

```bash
kubectl ate revert actor coder-0 -a "${ATESPACE}"
kubectl ate get actor coder-0 -a "${ATESPACE}"
```

`coder-0` is `ACTOR_STATE_SUSPENDED`. The next request through the router, or
`kubectl ate resume`, restores it exactly as the golden actor was.

**Or recreate all of them**, which is what a pipeline would do per run:

```bash
for i in $(seq 0 $((NUM_ACTORS - 1))); do
  kubectl ate delete actor "coder-${i}" -a "${ATESPACE}"
  kubectl ate create actor "coder-${i}" -a "${ATESPACE}" --template coding-env
  kubectl ate resume actor "coder-${i}" -a "${ATESPACE}"
done
```

Either way, nothing a model did in run N is visible in run N+1. This closes
the cross-session persistence path from the Hugging Face incident.

---

## Step 9: Teardown

The GPU node bills while it exists. Delete it first if you are done.

```bash
gcloud container node-pools delete gpu-l4 \
  --cluster="${CLUSTER_NAME}" --location="${CLUSTER_LOCATION}" --project="${PROJECT_ID}" --quiet
```

Training, serving and the gateway objects:

```bash
kubectl delete namespace "${TRAIN_NS}"
kubectl -n "${LLM_NS}" delete agentgatewaypolicy "${LLM_GW}-access-log"
kubectl -n "${LLM_NS}" delete httproute vllm
kubectl -n "${LLM_NS}" delete agentgatewaybackend vllm
kubectl -n "${LLM_NS}" delete gateway "${LLM_GW}"
```

Substrate objects. Actors first, then templates (which also deletes their
golden actor and golden snapshot), then the empty atespace, then the pool:

```bash
for i in $(seq 0 $((NUM_ACTORS - 1))); do
  kubectl ate delete actor "coder-${i}" -a "${ATESPACE}"
done
kubectl ate delete actor redteam -a "${ATESPACE}"
kubectl ate delete actor-template coding-env -a "${ATESPACE}"
kubectl ate delete actor-template redteam -a "${ATESPACE}"
kubectl ate delete atespace "${ATESPACE}"
kubectl delete namespace "${POOL_NS}"
```

## References

- OpenEnv: [repository](https://github.com/huggingface/OpenEnv),
  [Harnesses in OpenEnv](https://github.com/huggingface/OpenEnv/blob/main/docs/source/tutorials/harnesses.md) (white-box vs black-box),
  [Training with OpenEnv](https://github.com/huggingface/OpenEnv/blob/main/docs/source/guides/training.md),
  [Harbor environment](https://github.com/huggingface/OpenEnv/blob/main/docs/source/environments/harbor.md)
- TRL: [OpenEnv integration](https://huggingface.co/docs/trl/openenv) (`environment_factory`, colocate vs server mode)
- Substrate: [api-guide.md](https://github.com/agent-substrate/substrate/blob/main/docs/api-guide.md) (templates, golden snapshots, `RevertActor`, GPUs),
  [network-egress.md](https://github.com/agent-substrate/substrate/blob/main/docs/network-egress.md) (DNS relay, link-local drop),
  [router README](https://github.com/agent-substrate/substrate/blob/main/cmd/atenet/internal/router/README.md) (ingress client authentication)
- agentgateway: [Kubernetes docs](https://agentgateway.dev/docs/kubernetes/latest/),
  [CEL reference](https://github.com/agentgateway/agentgateway/blob/v1.6.0/schema/cel.md)
- Earlier labs: [llmgateway-with-substrate.md](../egress/llmgateway-with-substrate.md),
  [setup.md](../setup.md)

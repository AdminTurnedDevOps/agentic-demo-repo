# Watch Agent Egress on agentgateway

Tldr; An AI agent inside a microVM sandbox calls an LLM API. That TCP never
leaves the worker directly. nftables REDIRECTs it into `atunnel`, which opens
an mTLS HTTP CONNECT to `atenet-egress`. agentgateway is the proxy you
inspect: access logs (shipped) and traces (one overlay). The actor is the
traffic source, not the plot.

| Lab | What you look at | Which agentgateway |
|---|---|---|
| **agent** → `atenet-egress` → Anthropic | Embedded dataplane in `ate-system` (`--atenet-router=agentgateway`) |

The workload is one Claude Code loop (same image as
[More Agents Than Pods](../agents/agent-multiplex-demo.md)), on a **microVM**
pool, replica 1. Density is not the point. Outbound HTTPS is.

---

## What this lab proves

| Beat | Proof |
|---|---|
| Egress is cluster-wide, not a demo flag | Standard ate-system already sets `--egress-gateway-address`. Any RUNNING actor's outbound TCP is tunneled. |
| The traffic is a real agent call | `kubectl ate logs` shows a Claude tick; seconds later agentgateway logs a CONNECT whose authority is Anthropic's `ip:443`. |
| You can see it on agentgateway | Access log field `substrate.connect.authority` (stock overlay). |
| Metrics in Grafana | Prometheus scrapes agentgateway `:15020`. Dashboard **atenet-egress (agentgateway)**. |
| Traces in Grafana | Stock egress overlay has **no** tracing. Lab ConfigMap + `AGENTGATEWAY_OTLP_ADDRESS` send OTLP to **Tempo**. Explore → Tempo, `service.name="atenet-egress"`. |
| Sandbox class does not change the tunnel | Same `atunnel` + gateway path on `sandboxClass: microvm` as on gVisor. |

---

## What you look at

```text
 Claude Code  (microVM actor)
   HTTPS api.anthropic.com:443
        │
        ▼  nftables REDIRECT
   atunnel  mTLS + CONNECT  (actor cert)
        │
        ▼
   atenet-egress  container: agentgateway
        │  access log: substrate.connect.authority
        │  metrics:   :15020/metrics → Prometheus → Grafana
        │  traces:    OTLP gRPC → Tempo → Grafana Explore
        ▼
   Anthropic
```

| Stream | Where | What it tells you |
|---|---|---|
| Agent | `kubectl ate logs actors claude -a egress-agent -f` | The model was actually called |
| Egress proxy logs | `deploy/atenet-egress -c agentgateway` | CONNECT went through agentgateway |
| Metrics | Grafana dashboard **atenet-egress (agentgateway)** | Request/connection rate and latency |
| Traces | Grafana **Explore → Tempo** | Timing of that hop (`service.name=atenet-egress`) |

---

## Prerequisites

- **GKE + ate-system.** Upstream
  [GKE Quickstart (Development)](https://github.com/agent-substrate/substrate/blob/main/README.md#gke-quickstart-development):
  `.ate-dev-env.sh`, `go run ./tools/setup-gcp bootstrap`, then
  `./hack/install-ate.sh --deploy-ate-system`. Bring-your-own cluster and
  Pod Certificate APIs:
  [tools/setup-gcp](https://github.com/agent-substrate/substrate/blob/main/tools/setup-gcp/README.md).
  Standard, not Autopilot (`atelet` is privileged + `hostPath`).
- **MicroVM runtime.** There is no separate GKE microVM chapter. Same
  scripts the counter demo uses:
  - [Counter demo — Micro-VM variant](https://github.com/agent-substrate/substrate/blob/main/demos/counter/README.md#micro-vm-variant)
    (`./hack/run-microvm-demo.sh` on GKE, or
    `hack/install-microvm-deps.sh --install` if ate-system is already up)
  - [SandboxConfig / micro-VM](https://github.com/agent-substrate/substrate/blob/main/docs/api-guide.md#micro-vm-sandboxconfig)
    — nodes need `/dev/kvm` + nested virt; atelet advertises the device and
    that is what places workers. `ate.dev/sandboxClass=microvm` is optional
    (taint/reserve), not the scheduler’s primary signal.
  - Local/kind only:
    [Running the microVM runtime locally](https://github.com/agent-substrate/substrate/blob/main/docs/dev/microvm-local.md)

  Confirm:

  ```bash
  kubectl get sandboxconfig microvm
  kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.capacity.ate\.dev/kvm}{"\n"}{end}'
  ```

  If `SandboxConfig/microvm` is missing:

  ```bash
  ./hack/install-microvm-deps.sh --install
  ```

- `kubectl-ate` from the same Substrate checkout
  (`go install ./cmd/kubectl-ate`). Confirm `--atespace` and `logs`.
- `ko`, `docker`+`buildx`, `jq`, `curl`, **Helm ≥ 3.15**. Source `.ate-dev-env.sh`.
- A **short-lived Anthropic API key**. It is written into the ActorTemplate
  as a literal env value and captured in the golden snapshot.

Run commands from the Substrate repo root unless a path under
`agentic-demo-repo/substrate/egress/` is named.

Confirm ate-system and the egress Deployment:

```bash
source .ate-dev-env.sh
: "${BUCKET_NAME:?}" "${KO_DOCKER_REPO:?}"
kubectl get pods -n ate-system
kubectl -n ate-system rollout status deploy/atenet-egress --timeout=120s
```

---

## Step 1: agentgateway on atenet (ingress and egress)

Setup lab installs Envoy. This lab needs the agentgateway overlay:

```bash
./hack/install-ate.sh --atenet-router=agentgateway --deploy-atenet
```
^ This does the following:

• Pulls cr.agentgateway.dev/agentgateway:v1.5.0
• Puts it in ate-system as container agentgateway on deploy/atenet-router and deploy/atenet-egress
• Mounts the Substrate ConfigMaps as /etc/agentgateway/config.yaml
• Starts agentgateway -f /etc/agentgateway/config.yaml

```bash
kubectl -n ate-system get deploy/atenet-egress \
  -o jsonpath='{.spec.template.spec.containers[0].name}{"\n"}'
```

Must print `agentgateway`. `--deploy-atenet` does not rebuild ate-api or
atelet. It does replace router + egress in `ate-system`. The MCP lab's
`agentgateway-system` Gateway is untouched.

---

## Step 2: Prometheus, Grafana, Tempo

Prometheus scrapes **metrics**. Tempo stores **traces**. Grafana is the UI
for both. Do not send traces to Prometheus.

`LAB` is the lab manifests dir (from Substrate repo root, adjust if needed):

```bash
LAB=../agentic-demo-repo/substrate/egress/manifests
```

### 2a. kube-prometheus-stack

Skip this Helm install if `monitoring` already exists from the
[observability lab](../optimization/observability/obs.md). The
`podMonitorSelectorNilUsesHelmValues=false` setting is required so our
PodMonitors are picked up:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update prometheus-community

helm upgrade --install monitoring \
  prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --set alertmanager.enabled=false \
  --set prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false
```

```bash
kubectl get pods -n monitoring
```

Expect operator, Prometheus, Grafana, kube-state-metrics, node-exporter.

### 2b. Tempo + scrape + dashboard

```bash
kubectl apply -f "${LAB}/observability/"
kubectl -n monitoring rollout status deploy/tempo --timeout=120s
```

That applies:

| File | Role |
|---|---|
| `tempo.yaml` | Single-binary Tempo, OTLP gRPC `:4317`, query `:3200` |
| `podmonitor.yaml` | Scrape `atenet-egress` and `atenet-router` `:15020` |
| `grafana-datasource.yaml` | Grafana datasource **Tempo** (`uid: tempo`) |
| `grafana-dashboard.yaml` | Dashboard **atenet-egress (agentgateway)** |

### 2c. Point egress agentgateway at Tempo

Stock overlay logs CONNECTs and does **not** trace. Router has OTLP; egress
does not. Overlay + env:

```bash
kubectl apply -f "${LAB}/atenet-egress-agentgateway-config.yaml"

kubectl -n ate-system set env deploy/atenet-egress \
  AGENTGATEWAY_OTLP_ADDRESS=tempo.monitoring.svc.cluster.local:4317 \
  -c agentgateway

kubectl -n ate-system rollout restart deploy/atenet-egress
kubectl -n ate-system rollout status deploy/atenet-egress --timeout=120s
```

```bash
kubectl -n ate-system get cm atenet-egress-agentgateway-substrate-config \
  -o jsonpath='{.data.config\.yaml}' | grep -A6 tracing

kubectl -n ate-system get deploy/atenet-egress \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="agentgateway")].env}'
echo
```

`AGENTGATEWAY_OTLP_ADDRESS` must be `tempo.monitoring.svc.cluster.local:4317`.

Grafana sidecar can take a minute to load the Tempo datasource and dashboard.
Restart Grafana if they are missing after ~2 minutes:

```bash
kubectl -n monitoring rollout restart deploy/monitoring-grafana
```

The Grafana Deployment name is `monitoring-grafana` for this Helm release
name. Confirm with `kubectl get deploy -n monitoring`.

---

## Step 3: One Claude agent on a microVM pool (traffic source)

Not `--deploy-demo-egress` (that app is a URL fetcher). Not the 3-on-2
Claude multiplex demo (gVisor, density). One agent, microVM, so it dials
Anthropic through the tunnel.

### 3a. Workload image

Same Dockerfile as the multiplex lab:

```bash
export ANTHROPIC_API_KEY=   # paste; prefer a dedicated key
WORKLOAD_IMAGE=$(
  repo="${KO_DOCKER_REPO}/claude-multiplex-demo-workload"
  tag="${repo}:egress-$(date +%s)"
  docker buildx build --platform=linux/amd64 --push \
    -t "${tag}" demos/claude-code-multiplex/workload >&2
  digest=$(docker buildx imagetools inspect "${tag}" --format '{{json .}}' \
             | jq -r '.manifest.digest')
  echo "${repo}@${digest}"
)
echo "$WORKLOAD_IMAGE"
```

### 3b. MicroVM WorkerPool

The controller names the Deployment after the WorkerPool (`claude-egress`):

```bash
ko apply -f "${LAB}/workerpool.yaml"
kubectl -n ate-demo-egress-agent rollout status deploy/claude-egress --timeout=5m
kubectl get workerpool,deploy,po -n ate-demo-egress-agent
```

Worker pod must land on a `ate.dev/sandboxClass=microvm` node. If it
Pending: node label, nested virt, `/dev/kvm`.

### 3c. Template + actor

```bash
kubectl ate create atespace egress-agent

sed \
  -e "s|\${BUCKET_NAME}|${BUCKET_NAME}|g" \
  -e "s|\${WORKLOAD_IMAGE}|${WORKLOAD_IMAGE}|g" \
  -e "s|\${ANTHROPIC_API_KEY}|${ANTHROPIC_API_KEY}|g" \
  "${LAB}/agent-template.yaml.tmpl" \
  | kubectl ate create actor-template -f -

kubectl ate get actor-template claude-microvm -a egress-agent
```

Wait until `GOLDEN SNAPSHOT` is set (microVM golden is slower than gVisor;
minutes is normal). Then:

```bash
kubectl ate create actor claude -a egress-agent --template-ref claude-microvm
kubectl ate resume actor claude -a egress-agent
kubectl ate get actor claude -a egress-agent
```

You want `ACTOR_STATE_RUNNING` and an `ATEOM POD`. That is enough actor
ceremony. Everything below is the gateway.

---

## Step 4: Watch the tunnel

Split the terminal.

**Agent (proof the model ran):**

```bash
kubectl ate logs actors claude -a egress-agent -f
```

A completed tick looks like:

```text
[demo-actor:claude] === tick N at …Z ===
[demo-actor:claude] running: Tell me one short, surprising fact about microVMs. One sentence.
…
[demo-actor:claude] tick N done; sleeping 20s
```

**agentgateway egress (proof the CONNECT took that hop):**

```bash
kubectl -n ate-system logs deploy/atenet-egress -c agentgateway -f \
  | grep --line-buffered 'substrate.connect.authority'
```

On each tick you should see a structured line whose
`substrate.connect.authority` is `ip:443` — Anthropic's resolved address,
not the hostname. CONNECT carries `IP:port` from the sandbox dial.

Correlate by clock: Claude tick starts → CONNECT line → tick done.

Repeat fetches to an already-open host often **reuse the tunnel** and print
no new access-log line. Wait for the next tick, or:

```bash
kubectl ate suspend actor claude -a egress-agent
kubectl ate resume actor claude -a egress-agent
```

If there is **no** CONNECT line while ticks succeed, interception is off:
`ate-api-server` missing `--egress-gateway-address`, or this actor was
Run/Restore'd before that flag was live.

Raw metrics (optional; Grafana is the intended view):

```bash
kubectl -n ate-system port-forward deploy/atenet-egress 15020:15020
curl -sS localhost:15020/metrics | grep -E 'agentgateway_(requests|connections)' | head
```

---

## Step 5: Grafana: metrics and traces

```bash
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80
```

Login: `admin` / `prom-operator` (kube-prometheus-stack default). Confirm
the Service name with `kubectl get svc -n monitoring | grep grafana`.

### Metrics

Dashboards → **atenet-egress (agentgateway)** (`uid: atenet-egress-agw`).

After Claude ticks you should see connection and request series move.
`substrate.connect.authority` is an **access-log field**, not a Prom metric.
Do not search Prometheus for it.

Prometheus targets (optional check):

```bash
kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090
```

Open http://localhost:9090/targets — `atenet-egress-agentgateway` should be
**up**. Explore `agentgateway_connections_total`.

### Traces (Tempo)

**Explore → Tempo** (not Prometheus). Search:

```text
{resource.service.name="atenet-egress"}
```

Or the search UI: Service Name = `atenet-egress` (from the ConfigMap
`resources.service.name`).

Open a span. Tunnel-mode CONNECT is not an HTTP route; the span may be
thin. Empty Tempo + good access logs is a known shape.

Grep a trace id from the proxy if you need to paste it into Tempo:

```bash
kubectl -n ate-system logs deploy/atenet-egress -c agentgateway --tail=200 \
  | grep -E 'trace\.id|trace_id' | tail
```

`kubectl ate --trace` is **ate-api** on-demand tracing. It does not wrap
agentgateway CONNECTs. GKE Cloud Trace is unused in this lab; OTLP goes to
Tempo in `monitoring`.

---

## Cleanup

```bash
kubectl ate suspend actor claude -a egress-agent 2>/dev/null || true
kubectl ate delete actor claude -a egress-agent --any-state 2>/dev/null || true
kubectl ate delete actor-template claude-microvm -a egress-agent 2>/dev/null || true
kubectl ate delete atespace egress-agent 2>/dev/null || true

kubectl delete ns ate-demo-egress-agent --ignore-not-found

kubectl delete -f "${LAB}/observability/" --ignore-not-found

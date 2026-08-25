# Agent Substrate features in kagent-enterprise

kagent-enterprise does **not** invent its own Substrate control plane. It ships the OSS kagent integration, turns it on with a Helm subchart, and adds install/dev wiring. The feature is **opt-in and still early**: default install leaves it off.

---

## Batteries Included

Two kagent APIs, both running as Substrate **actors** on a shared **WorkerPool**:

| User resource | What it is | Substrate objects kagent creates | Example |
|---|---|---|---|
| `SandboxAgent` | Declarative ADK agent in a gVisor actor | One `ActorTemplate` + **one actor per chat session** | [Declarative SandboxAgent](substrate-creation-examples.md#declarativebyo-agents) |
| `AgentHarness` | OpenClaw/Hermes-style VM (no kagent runtime baked in) | One `ActorTemplate` + **one actor per harness** | [OpenClaw AgentHarness](substrate-creation-examples.md#harness-agents-openclaw-and-hermes) |

Platform capacity is a `WorkerPool` (`ate.dev/v1alpha1`). Helm may create `kagent-default`; the controllers never create or delete pools.

Enable path:

- `substrate.enabled=true` on the CRDs chart and the kagent chart (pulls `oci://ghcr.io/kagent-dev/substrate/helm`)
- `controller.substrate.enabled=true` (dials ate-api, starts substrate controllers)
- optional `substrateWorkerPool.create=true`
- local/CI: `INSTALL_SUBSTRATE=true` (helmfile default is `false` so e2e stays clean)

---

## Feature 1: SandboxAgent on Substrate

Shipped CRD description: *“an isolated sandbox on Agent Substrate.”*

Creation example: [Declarative SandboxAgent](substrate-creation-examples.md#declarativebyo-agents).

**Reconcile**

1. Build an `ActorTemplate` from the agent’s pod template (digest-pinned Go ADK image, runsc URLs, pause image, snapshot prefix).
2. Wait for Substrate’s **golden snapshot** (`ActorTemplate.status.phase == Ready`).
3. On A2A chat, `EnsureSessionActor` creates/resumes an actor named from the session (`asr-…`).
4. Controller proxies A2A through **atenet-router** using `Host: <actor>.actors.resources.substrate.ate.dev`.
5. Session delete suspends/deletes that actor. SandboxAgent delete cleans all session actors, then the template.

**Supported**

- Declarative **Go** ADK agents
- `spec.substrate.workerPoolRef` or controller default pool
- `spec.substrate.snapshotsConfig.location` (`gs://…`; default `gs://ate-snapshots/<ns>/<name>`)
- Agent config via Secret env (`KAGENT_CONFIG_JSON`, agent card, SRT settings) — ate-api resolves `secretKeyRef`, actors cannot mount SA token volumes
- Chat from the UI via `/api/sandboxagents` and `/api/a2a-sandboxes` fallback

**Not supported (validation / implementation)**

- Skills
- BYO agents
- Python runtime (OSS rejects it; there is still a `substrate-demo-python` demo YAML)
- Projected SA tokens / Downward API in the actor (literals used for `KAGENT_NAME` / `KAGENT_NAMESPACE`)
- `spec.platform` in the **enterprise CRDs** — unlike current OSS, these CRDs have no `agent-sandbox` vs `substrate` switch. Everything in this CRD is Substrate-shaped.

Demo applied after helmfile postsync: `test/environment/config/kagent/sandbox-agent.yaml` (`substrate-demo`, `substrate-demo-python`) against pool `kagent-default`.

---

## Feature 2: AgentHarness on Substrate

Enterprise CRD: *“OpenClaw or Hermes running on Agent Substrate.”* `spec.substrate` is **required** (no OpenShell runtime field in the shipped YAML).

Creation example: [OpenClaw AgentHarness](substrate-creation-examples.md#harness-agents-openclaw-and-hermes).

**Reconcile** (`SubstrateAgentHarnessController` in OSS)

1. Resolve WorkerPool.
2. Generate owned `ActorTemplate` (OpenClaw/NemoClaw sandbox image, startup script with base64 `openclaw.json`).
3. Wait for golden snapshot.
4. Create/resume one actor (`ahr-…`).
5. Proxy OpenClaw Control UI through atenet: `/api/agentharnesses/<ns>/<name>/gateway`.

**Harness spec kagent understands (OSS types)**

- `workerPoolRef`
- `snapshotsConfig` (`gs://` only)
- `workloadImage` override
- **exactly one of** `gatewayToken` / `gatewayTokenSecretRef`
- `modelConfigRef` → provider keys as env SecretRefs, not plaintext in the template
- Telegram / Slack channels (tokens via env SecretRefs)

**Backends actually wired for Substrate in the controller**

- OpenClaw
- NemoClaw

Hermes is on the **enterprise CRD enum**, but the substrate controller only registers OpenClaw/NemoClaw. Hermes is the OpenShell path in current OSS. Treat Hermes-on-Substrate as **not implemented**.

---

## Runtime pieces the Kagent Substrate Helm Chart can install

When `substrate.enabled=true`, the kagent-dev substrate subchart comes along for:

- `ate-api-server` (actor lifecycle in Valkey)
- `ate-controller` (WorkerPool → Deployment, golden snapshots)
- `atelet` DaemonSet (images, checkpoints)
- `atenet-router` (wake-on-request HTTP)
- default gVisor `SandboxConfig` (v0.0.8+)
- optional `WorkerPool` `kagent-default` (`sandboxClass: gvisor`)

Controller wiring (`charts/kagent-enterprise/templates/controller-deployment.yaml`):

- projected SA token for ate-api JWT (`audience: api.ate-system.svc`)
- `SUBSTRATE_ATE_API_ENDPOINT`, `ATENET_ROUTER_URL`, default pool, pause image
- Role/RoleBinding so `ate-api-server` can `get` Secrets/ConfigMaps in the install namespace (and `rbac.namespaces`)

Local helmfile also:

- prefixes Services as `kagent-api`, `kagent-atenet-router` (subchart in the `kagent` release)
- forces `redis.clusterAddress: kagent-valkey-cluster.kagent.svc:6379` (subchart default ignores the prefix)
- `ateApiInsecure: true` (self-signed ate-api cert, controller does not mount the CA)
- **2 WorkerPool replicas** (golden rebuild + concurrent demos; also hides an ate-api worker-binding deadlock on 1 replica)
- restarts `ate-controller` after bring-up because golden reconcile backoff can park templates in `ResumeGoldenActor`
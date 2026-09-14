# Kagent Hermes BYO Harness

This directory builds a kagent BYO runtime that runs Hermes Agent inside an Agent Substrate Actor. A Go adapter exposes kagent's private A2A gRPC service and translates each turn to the `hermes acp` subprocess over standard input/output. The adapter is pinned to kagent commit `0fbf966b` and should be used with a controller built from that commit or newer compatible code.

## Runtime Contract

- Private A2A gRPC listens on port 80.
- Readiness is served on `/readyz` at port 8081 by kagent's shared Harness runtime.
- Hermes state and the continuation ID are stored beneath `/data`.
- `KAGENT_CONFIG_JSON` supplies the OpenAI model and system prompt.
- `KAGENT_AGENT_CARD_JSON` supplies the private Agent Card.
- ACP filesystem and terminal client methods are disabled. Hermes executes its own tools within the Actor boundary.
- ACP permission requests are rejected rather than automatically approved.

This initial adapter supports an OpenAI `ModelConfig`.

## Prerequisites

- Current kagent `main` APIs installed with `kagent.dev/v1alpha3`.
- Agent Substrate and `WorkerPool/kagent-default` are ready.
- The Substrate `atenet-router` runs with `--route-timeout=5m` or another limit suitable for LLM streaming. Its 10-second default resets active gRPC streams.
- `ModelConfig/default-model-config` uses OpenAI and has `ResolvedRefs=True`.
- Docker Buildx, Go 1.27, and `uv` are installed.
- Docker is authenticated to `northamerica-northeast1-docker.pkg.dev`.

For the current standalone Substrate deployment, add the router argument and wait for its rollout before testing Hermes:

```bash
kubectl patch deployment atenet-router -n ate-system --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--route-timeout=5m"}]'
kubectl rollout status deployment/atenet-router -n ate-system --timeout=5m
```

The local Substrate source manifest documents the same setting at `manifests/ate-install/atenet-router.yaml`.

## Why All The Configs?

Kagent’s BYO Harness expects the image to expose:
- A2A gRPC on port 80
- /readyz on port 8081
- Kagent-compatible task, streaming and cancellation behavior

Hermes instead exposes ACP over standard input/output. The custom files provide the missing bridge:
`kagent A2A → Go adapter → Hermes ACP`

The remaining files package, test and reproducibly build that adapter with Hermes into a digest-pinned image. Without them, kagent cannot communicate with or manage Hermes as an AgentInstance on Substrate.

### File Architecture

```text
kagent-oss-hermes/
├── main.go               # Runtime entrypoint and private A2A server startup
├── runner.go             # Hermes process, ACP connection and session lifecycle
├── client.go             # ACP callbacks translated into kagent runtime events
├── config.go             # Kagent configuration converted into Hermes config.yaml
│
├── config_test.go        # Model and prompt configuration tests
├── client_test.go        # ACP event and permission behavior tests
│
├── Dockerfile            # Go adapter build plus Python/Hermes runtime image
├── .dockerignore         # Files excluded from the container build context
├── Makefile              # Dependency lock, test, build and push commands
│
├── go.mod                # Direct Go dependencies and pinned kagent revision
├── go.sum                # Go dependency checksums
├── requirements.in       # Direct Python dependency: hermes-agent[acp]
├── requirements.lock     # Fully pinned and hashed Python dependency graph
│
├── hermes-byo.yaml       # Harness/hermes and AgentTemplate/hermes-assistant
└── README.md             # Architecture, build and deployment instructions
```

#### Runtime Path

`main.go` starts the service and wires together the runtime components. `runner.go` launches `hermes acp`, owns the durable Hermes session, and forwards each A2A turn over ACP. `client.go` handles the reverse direction by translating Hermes text and tool updates back into kagent events.

#### Configuration Path

`config.go` reads the controller-provided `KAGENT_CONFIG_JSON` and writes `/data/hermes/config.yaml`. This is where the OpenAI model, API endpoint, output-token limit, system prompt, and workspace are adapted to Hermes' configuration format.

#### Build Path

The `Dockerfile` compiles the Go files into `/usr/local/bin/kagent-hermes`, installs the Python-based Hermes Agent from `requirements.lock`, and produces the non-root runtime image. The `Makefile` provides the repeatable commands used to lock dependencies, run tests, build, and push that image.

#### Deployment Path

`hermes-byo.yaml` points the BYO Harness at the digest-pinned image, `WorkerPool/kagent-default`, and the existing `default-model-config`. Applying it creates the reusable Hermes Harness and the admitted `hermes-assistant` AgentTemplate; an AgentInstance and its Actor are created later by the first conversation.


### Dockerfile

Even though Go is used, you may notice in the Dockerfile that there is a Python image.

The adapter is Go, but Hermes itself is a Python application.

The final image therefore contains:

- Go binary: A2A-to-ACP adapter used by kagent
- Python runtime: Runs hermes-agent
- Hermes process: Started as hermes acp

kagent A2A → Go adapter → Python-based Hermes

The Go builder image compiles the adapter. The Python image is the final runtime because it must execute Hermes.

## Build

Regenerate the pinned Python dependency lock after intentionally changing `requirements.in`:

```bash
make lock
```

Run the Go checks and build locally:

```bash
make build
```

Validate the built image's configuration, Hermes ACP handshake, and session creation without calling the model:

```bash
docker run --rm --platform linux/amd64 \
  -e OPENAI_API_KEY \
  -e 'KAGENT_CONFIG_JSON={"model":{"type":"openai","model":"gpt-4.1-mini"},"instruction":"Be concise."}' \
  -e 'KAGENT_AGENT_CARD_JSON={"name":"hermes_check","description":"Hermes check","version":"v1","supportedInterfaces":[{"url":"http://127.0.0.1:80","protocolBinding":"GRPC","protocolVersion":"1.0"}],"capabilities":{"streaming":true},"defaultInputModes":["text"],"defaultOutputModes":["text"],"skills":[]}' \
  northamerica-northeast1-docker.pkg.dev/field-engineering-us/mlevan-images/kagent-hermes:0.1.0 \
  --check
```

Push the image:

```bash
make push
```

After pushing a changed image, resolve the repository digest and update `hermes-byo.yaml` with `IMAGE@sha256:DIGEST`. Do not use the mutable tag in the Harness.

## Validate

Validate the resources without creating them:

```bash
kubectl apply --dry-run=server -f hermes-byo.yaml
```

Deploy only when ready:

```bash
kubectl apply -f hermes-byo.yaml
```

Once the Harness/AgentTemplate pair reports a successful prepared revision, create a conversation and its backing Actor:

```bash
kagent create agent-instance \
  --namespace kagent \
  --harness hermes \
  --agent-template hermes-assistant
```

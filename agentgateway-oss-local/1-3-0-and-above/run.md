# agentgateway OSS v1.3.1+: Standalone LLM + MCP (Docker)

A self-contained local stack:

- **LLM gateway** supporting multiple providers (Anthropic, xAI/Grok, Gemini, OpenAI) on **:3000**
- **MCP gateway** → the "everything" reference server (HTTP sidecar) on **:3001**
- **Admin + Web UI** on **:15000** (`/ui`)

Everything is driven by one of the config files in this folder (e.g. `v130-example-config.yaml` for basic or `multi-prov.yaml` for multi-provider).

---

## Endpoints

| Surface | URL |
|---|---|
| LLM — OpenAI-compatible | `http://localhost:3000/v1/chat/completions` |
| LLM — native Anthropic | `http://localhost:3000/v1/messages` |
| MCP (Streamable HTTP) | `http://localhost:3001/mcp` |
| Admin / Web UI | `http://localhost:15000/ui` |

---

## Prerequisites

- Docker
- The API key(s) for the providers you want to use (Anthropic for basic; plus xAI, Gemini, OpenAI for multi-prov)

---

## Run it from a clean state

All commands are run **from this folder** (`1-3-0-and-above/`).

**Set the agentgateway version** (update this value when a new release comes out):

```bash
AGENTGATEWAY_VERSION=v1.3.1
```

The commands below use `${AGENTGATEWAY_VERSION}`. For easy copy-paste, each command block includes the assignment at the top (just update the value in the block you run). You can also export it in your shell first.

### 1. Put your API keys in the secrets files

The configs read keys from mounted files (never from the config or git).

For the basic/single-provider config (or multi which still includes Anthropic):

```bash
mkdir -p secrets
printf '%s' "sk-ant-..." > secrets/anthropic-api-key   # no trailing newline
```

For the multi-provider config you also need:

```bash
printf '%s' "xai-..."   > secrets/xai-api-key
printf '%s' "AIza..."   > secrets/gemini-api-key
printf '%s' "sk-proj-..." > secrets/openai-api-key
```

`secrets/.gitignore` ignores everything except itself, so the keys are never committed.

### 2. Create a shared Docker network

The gateway and the MCP server are separate containers and need to resolve each other by name.

```bash
docker network create agw-net
```

### 3. Start the MCP "everything" server

Run the **everything server** as its own Node container speaking Streamable HTTP:

```bash
docker run -d --name mcp-everything --network agw-net \
  node:23-slim npx -y @modelcontextprotocol/server-everything streamableHttp
```

It listens on port 3001 inside the container at path `/mcp`. Confirm:

```bash
docker logs mcp-everything   # -> "MCP Streamable HTTP Server listening on port 3001"
```

### 4. (Optional) Validate the config

```bash
docker run --rm \
  -v "$PWD:/work" \
  -v "$PWD/secrets:/etc/agentgateway/secrets:ro" \
  ghcr.io/agentgateway/agentgateway:${AGENTGATEWAY_VERSION} -f /work/v130-example-config.yaml --validate-only
# or for multi:
# ... -f /work/multi-prov.yaml --validate-only
# -> Configuration is valid!
```

### 5. Start the gateway

Must be on `agw-net` (to reach `mcp-everything`) and must set `ADMIN_ADDR=0.0.0.0:15000` (see gotchas).
The whole folder is mounted at **`/work`** (writable) — not just the config file — because the gateway
writes files **next to the config**: the request-log DB (`requests.db`) and the cost catalog
(`base-costs.json`). Mounting only the file would put those in `/` (root, unwritable) and fail.

1. With the smaller demo config

```bash
docker run -d --name agw-v130 --network agw-net \
  -p 15000:15000 -p 3000:3000 -p 3001:3001 \
  -e ADMIN_ADDR=0.0.0.0:15000 \
  -w /work \
  -v "$PWD:/work" \
  -v "$PWD/secrets:/etc/agentgateway/secrets:ro" \
  ghcr.io/agentgateway/agentgateway:${AGENTGATEWAY_VERSION} -f /work/v130-example-config.yaml
```

2. With the multi-provider config
```bash
docker run -d --name agw-v130 --network agw-net \
  -p 15000:15000 -p 3000:3000 -p 3001:3001 \
  -e ADMIN_ADDR=0.0.0.0:15000 \
  -w /work \
  -v "$PWD:/work" \
  -v "$PWD/secrets:/etc/agentgateway/secrets:ro" \
  ghcr.io/agentgateway/agentgateway:${AGENTGATEWAY_VERSION} -f /work/multi-prov.yaml
```

Open **http://localhost:15000/ui** — Home should show **LLM Enabled**, **MCP Enabled**.

---

## Config reference (llm: / mcp: / config: blocks)

What each part does — this is the annotation that used to live in the file as comments.

### `llm:` block — the LLM gateway

```yaml
llm:
  port: 3000                      # the LLM gateway's own listener
  providers:                      # reusable upstream provider defaults
  - name: anthropic
    provider: anthropic
    params:
      apiKey:
        file: /etc/agentgateway/secrets/anthropic-api-key
  models:                         # what clients request by name
  - name: claude-opus-4-8         # matched against the request's "model"
    visibility: public            # public = directly requestable; internal = only via virtualModels
    provider:
      reference: anthropic         # use the provider defined above
  policies:
    cors: { allowOrigins: ["*"], allowHeaders: ["*"], allowMethods: ["*"] }
```

- **Use the top-level `llm:` block, not an inline route `ai` backend.** Both can route LLM traffic, but only the `llm:` block is surfaced on the UI's **Models / Providers / Guardrails / Costs** pages. An inline backend shows up as generic "Traffic" instead.
- **API key auth is automatic.** agentgateway places a standard key in the `x-api-key` header for Anthropic (and keeps `Authorization: Bearer` for `sk-ant-oat*` OAuth tokens). No header wiring needed.
- **File-based secret:** the config stores only the *path*. Safe to commit; survives UI saves without leaking the key. To rotate, overwrite `secrets/anthropic-api-key` and restart the gateway.
- **`params.model`** (not set here) overrides the model id sent upstream; omitted means the requested name is used.
- **CORS** is wildcard so the browser-based UI playground (served from `:15000`) can call the gateway. Tighten `allowOrigins` for anything shared.

### `mcp:` block — the MCP gateway

```yaml
mcp:
  port: 3001                      # the MCP gateway's own listener
  targets:
  - name: everything
    mcp:                          # Streamable-HTTP target -> the sidecar container
      host: mcp-everything        # resolves over the agw-net docker network
      port: 3001
      path: /mcp
  policies:
    cors:
      allowOrigins: [http://localhost:15000]
      allowHeaders: ["*"]
      allowMethods: [GET, POST]
      exposeHeaders: [Mcp-Session-Id]
```

- **Use the top-level `mcp:` block**, same reasoning as `llm:` — the UI's MCP card reads `config.mcp`. An MCP backend inside a route counts as "Traffic", not MCP.
- **`stdio` targets don't work in the stock image** (no Node). That is why we use an HTTP sidecar and an `mcp:` (Streamable HTTP) target instead.
- `exposeHeaders: [Mcp-Session-Id]` lets browser MCP clients read the session id.

### `config:` block — request-log DB + cost catalog

```yaml
config:
  database:
    url: sqlite:///work/requests.db   # request-log sink; powers UI Analytics + Logs
  modelCatalog:
  - file: base-costs.json             # pricing catalog (relative to the config dir = /work)
```

- **Analytics and Logs require a request-log database.** Without `config.database`, those UI pages show "request log database is not configured". SQLite (any non-`postgres://` URL) is created automatically; Postgres is also supported via `postgres://...`.
- The DB path is **absolute (`/work/requests.db`)** so it lands in the writable mounted folder. A relative path would resolve against the container's `/` working dir and fail to write.
- `modelCatalog` is added automatically when you click **Refresh base costs** in the UI; it points at `base-costs.json` (also written into `/work`).
- **What gets committed:** `base-costs.json` is committed (static, regenerable pricing data). `requests.db` (and its `-wal`/`-shm` sidecars) are **git-ignored** — runtime state that can contain request/response payloads.

---

## Gotchas (the non-obvious bits)

- **Don't click the UI's "Enable MCP" button here** — it hardcodes `mcp.port: 3000`, which collides with the LLM block on 3000, so the save silently fails. The `mcp:` block is hand-authored on **3001** instead.
- **`ADMIN_ADDR=0.0.0.0:15000` is required in Docker.** By default the admin/UI binds `localhost:15000` *inside* the container, so `-p 15000:15000` alone won't reach it.
- **Each gateway block owns its own listener port.** `llm.port` (3000), `mcp.port` (3001), and the admin port (15000) must all differ.
- **Env interpolation runs over the whole config file.** `$VAR` and `${VAR}` are expanded and loading **fails** if a referenced variable is unset. Write a literal dollar sign as `$$`.
- **The API key is a secret** — if it has ever been shared in plaintext, rotate it in the Anthropic console.

---

## Cleanup

```bash
docker rm -f agw-v130 mcp-everything
docker network rm agw-net
```

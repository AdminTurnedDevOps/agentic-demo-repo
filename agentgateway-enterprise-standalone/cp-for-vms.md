This guide will show how to install an agw ee standalone control plane on a VM or laptop/desktop

## One VM/laptop

### Install

On the VM, do the following

1. Set the appropriate env vars to set the license key and pull down the latest binary:

```
export ENTERPRISE_INSTALL_URL='https://storage.googleapis.com/enterprise-agentgateway-public-nonprod/install.sh'
export AGENTGATEWAY_VERSION='v2026.9.0-nightly-260904'
export ENTERPRISE_AGENTGATEWAY_LICENSE_KEY='<license-key>'
```

```
curl -fsSL "$ENTERPRISE_INSTALL_URL" | sh
```


2. Check that the binary is downloaded and usable

```
export PATH="$HOME/.agentgateway/bin:$PATH"
agentgateway --version
```

3. Run agentgateway

```
agentgateway
```

By default a config file will be generated for you. For example, the below:

```
loaded config from File("/Users/michaellevan/.config/agentgateway/config.yaml")
```

### Configuration

1. Look in `~/.config/agentgateway`. You'll see that agentgateway, when you run it, creates a config file. You can use that for testing purposes to run agentgateway.

```
agentgateway -f ~/.config/agentgateway/config.yaml
```

## High Availability

Because this section is for HA, doing this on your laptop won't be production-ready

![](images/ha.png)

### Active/Active

Scenario:
- Two VMs running the same `agentgateway` binary (could be more than 2 of course)
- A load balancer in front
- Shared PostgreSQL


```
clients
   │
   ▼
load balancer  (health on :15021)
   │
   ├──────────────┐
   ▼              ▼
VM1 binary     VM2 binary     same config.yaml baseline
   │              │
   └──────┬───────┘
          ▼
   PostgreSQL
```

Postgres holds the things both VMs must agree on:

| What | Why you share it |
|---|---|
| UI config overlay (`agw_config_resources`) | A save on one VM shows up on the other (LISTEN/NOTIFY, no restart) |
| Analytics / logs | One dashboard for both VMs |
| API-key budgets | Spend is global, not per VM |
| License attestation | Same entitlement record on both starts |

Schema is created on first start. No extra migration.

#### 1. Postgres

Stand up Postgres somewhere both VMs can reach (RDS, Cloud SQL, or a third VM). Back it up; it is now the source of UI config and spend.

Create a database and a user that can create tables, for example:

```
create user agw with password 'password';
create database agw owner agw;
```

#### 2. Same baseline config on both VMs

Copy one `config.yaml` to both VMs. Hybrid mode needs the empty `llm` / `mcp` sections in the **file** — the UI cannot add those sections, it only overlays resources into ones that already exist.

```
# yaml-language-server: $schema=https://agentgateway.dev/schema/config
config:
  storage:
    mode: hybrid
  database:
    url: postgres://agw:password@postgres-host:5432/agw
  session:
    key: "<64-hex-char AES-256 key>"
  license:
    key:
      file: /etc/agentgateway/license.key
gateways:
  default:
    port: 4000
ui:
  gateways: default
llm:
  models: []
mcp:
  targets: []
```

Generate the session key once and use it on both VMs (`openssl rand -hex 32`). You can also set `SESSION_KEY` in the environment instead of `config.session.key`. If the keys differ, a Streamable HTTP MCP session that hops to the other VM will 404.

Same license on both VMs (`ENTERPRISE_AGENTGATEWAY_LICENSE_KEY` or the file above).

Start each VM with:

```
export PATH="$HOME/.agentgateway/bin:$PATH"
export ENTERPRISE_AGENTGATEWAY_LICENSE_KEY='<license-key>'
agentgateway -f /path/to/config.yaml
```

#### 3. Load balancer

Point the LB at both VMs on **:4000**. Health-check **`GET :15021/healthz/ready`**, not the gateway port.

- LLM and ordinary HTTP: round-robin is fine (stateless at the proxy).
- Streamable HTTP MCP: active-active **if** `SESSION_KEY` is shared. Sessions live in memory, but the session id is encrypted state and the other VM can rebuild the upstream connections.
- Legacy SSE MCP and stdio MCP are process-local. Use stickiness, or don't put stdio behind this pair.

OIDC browser cookies need the same `OIDC_COOKIE_SECRET` on both VMs.

Local rate limits are per process. Global limits need a remote rate-limit service, which standalone does not run for you.

#### 4. Check that it is actually shared

Edit something in the UI through the LB (add an MCP server or a model). On the **other** VM:

```
curl -s http://localhost:15000/api/config/effective
```

You should see the change without restarting that process.


### Hot/Cold Scenario

Typical shapes:

• Cloud VM — second instance stopped or scaled to zero; LB/ASG/MIG health check fails on the hot one; the provider boots the spare and points the VIP at it.
• Always-on spare — cold process is running but the LB has only one backend (or keepalived/VRRP holds the VIP). Failover is “add the second backend / move the VIP,” not a wake-up.
• Same host — systemd/watchdog restarts the binary. That’s HA of the process, not of the VM.

What you still want with the cold side so its not a blank slate:

• Shared Postgres (config overlay, logs, budgets, license attestation)
• Same baseline config.yaml and session key
• Same license

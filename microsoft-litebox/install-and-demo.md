# Installing, Configuring, and Understanding Microsoft Litebox

## What Is It?

LiteBox is a security-focused library OS from Microsoft, written in Rust.
Repo: [microsoft/litebox](https://github.com/microsoft/litebox).

Core idea: cut down the interface between a guest program and the host, so
the guest has less host surface to attack.

LiteBox has three layers:

```text
Guest program (Linux ELF / OP-TEE Trusted Application)
      │  syscall ABI                        ← "North" shim
LiteBox core (fs, mm, net, fd, event, sync)
      │  platform::Provider traits          ← "South" platform
Host (Linux / Windows / Linux kernel / Hyper-V VTL1 / SEV-SNP)
```

- **North shim** presents the guest ABI. Today: a Linux-compatible shim
  (`litebox_shim_linux`) and an OP-TEE shim (`litebox_shim_optee`).
- **Core** (`litebox` crate, `#![no_std]`) provides the OS services behind
  the shim: filesystem (in-memory, read-only tar, overlay, 9P), memory
  management, a `smoltcp`-based network stack, file descriptors, and
  futex-based synchronisation.
- **South platform** is the small host interface the core runs on. Shims
  and platforms compose freely: any North shim can run on any South
  platform that provides the required traits.

Example combinations that exist today:

- Linux programs on unmodified Windows (this demo).
- Linux programs sandboxed on Linux.
- Programs on AMD SEV-SNP.
- OP-TEE programs on Linux.
- Programs on LVBS (Hyper-V VTL1).

Guest programs are ordinary, unmodified Linux ELFs. For userland runners,
their `syscall` instructions are first patched by the syscall rewriter
(`litebox_syscall_rewriter`) so syscalls trap into LiteBox instead of the
host kernel. The rewriter is x86-64 only, best-effort, and does not catch
dynamically generated (JIT) `syscall` instructions.

## How Does It Differ From gVisor?

Both projects reimplement the Linux syscall layer in a memory-safe
language so guest syscalls never reach the host kernel directly. They
differ in shape: gVisor is a finished container runtime, LiteBox is a
composable library-OS toolkit.

| Attribute | LiteBox | gVisor |
|---|---|---|
| Form | Library OS framework | Userspace kernel, `runsc` OCI runtime |
| Language | Rust, `no_std` core | Go |
| North | Linux, OP-TEE shims | Linux only |
| South | Linux, Windows, kernel, LVBS, SNP | Linux host only |
| Host surface | Typed `Provider` traits | Limited host syscalls from Sentry |
| Interception | Rewriter, platform entry, seccomp | ptrace, KVM, systrap platforms |
| Filesystem | In-mem, tar, overlay, 9P in-process | Gofer via 9P |

Components on the Windows 11 VM:

- Broker: `litebox-broker-userland` (host process, owns filesystem
  and network policy, launches the runner).
- Runner: `litebox_runner_linux_on_windows_userland` (runs the guest).
  Broker and runner ship on the pre-merge `ulitebox` branch today;
  `main` does not yet have broker networking (see Known limits).

### Prerequisites

- Python (`winget install Python.Python.3.12`)
- Rust toolchain: stable channel, per `rust-toolchain.toml` in the
  LiteBox repo. Install via [rustup](https://rustup.rs/) with the MSVC
  target. Visual Studio Build Tools (Desktop development with C++)
  provides the linker the MSVC target needs.
- An OpenAI API key.
  This is the entire demo: agent → agentgateway → LLM provider. Key
  lives only on the host, in the gateway environment. Never staged
  into the guest rootfs.
- Agentgateway [agentgateway](https://github.com/agentgateway/agentgateway),
  standalone binary (release download or `cargo run` from source).
  Runs on the host, outside LiteBox.

For the purposes of this demo, a `Standard_D4s_v5` (Windows, Gen2, x86-64, 4 vCPU / 16 GiB) in Azure was used.

Check the setup:

```powershell
rustc --version
cargo --version
$env:PROCESSOR_ARCHITECTURE
if ($env:OPENAI_API_KEY) { "OPENAI_API_KEY set" } else { "MISSING: set OPENAI_API_KEY" }
agentgateway --version
```

Checks must show `AMD64`, API key set (value never printed), and
agentgateway version. Without key + gateway there is no demo, only
preflight tests.

### Build

Demo pins the `ulitebox` branch — broker networking and Windows
`fork` support live there and are not on `main` yet. Branch moves;
record the commit you built (`git rev-parse HEAD`) with demo notes.

```powershell
git clone -b ulitebox https://github.com/microsoft/litebox.git
cd litebox
cargo build -p litebox_broker_userland --bin litebox-broker-userland
cargo build -p litebox_runner_linux_on_windows_userland
cargo build -p litebox_packager
cargo build -p litebox_syscall_rewriter
```

Binaries land in `target\debug\`:

- `litebox-broker-userland.exe` — demo entry point. Launches runner,
  serves guest filesystem, enforces network destination policy.
- `litebox_runner_linux_on_windows_userland.exe` — runs the guest.
  Launched by broker; do not run directly for this demo.
- `litebox-packager.exe`, `litebox_syscall_rewriter.exe` — rootfs
  packaging. Every ELF in the rootfs (program, interpreter, shared
  libraries) must be rewritten before the runner executes it.
  Packager does this automatically.

## Create An Agent

LiteBox has no agent framework built in: no LLM client, no MCP, no tool
runtime. An "agent in LiteBox" is an ordinary Linux program (here:
Python) running as the guest. Bring your own agent code; LiteBox only
sandboxes it.

Design the demo agent around current (as of 10/18/2026) LiteBox limits:

- Single process. No `subprocess`, no shell tools, no pip installs at
  runtime, no stdio MCP servers spawned as children. Threads are fine.
- Standard library only, so packaging stays small and no native wheels
  need staging.
- All LLM traffic through one base URL, set by environment variable.
  Point it at the gateway later without code changes.
- Provider API key passed in as a dummy value. The real key never
  enters the guest (see gateway section).

Save as `agent.py`:

```python
#!/usr/bin/env python3
"""Minimal LiteBox demo agent: one prompt, one LLM call, one reply."""

import json
import os
import sys
import urllib.request

BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://10.0.2.1:4000/v1")
API_KEY = os.environ.get("OPENAI_API_KEY", "dummy")
MODEL = os.environ.get("MODEL", "smart")


def ask(prompt: str) -> str:
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    return data["choices"][0]["message"]["content"]


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "Say hello from inside LiteBox."
    print(ask(question))
```

### Package the agent into a LiteBox rootfs

Broker loads the whole guest filesystem from one `.tar`
(`--fs-initial-files`). Every ELF in that tar must already be
rewritten. Easiest complete rootfs: pull a Python OCI image with
the packager on Windows, then add `agent.py`. Windows 11 ships
`tar.exe`; no WSL needed.

Run in PowerShell, from the `litebox` checkout:

```powershell
cargo run -p litebox_packager -- `
  --oci-image docker.io/library/python:3.12-slim `
  -o python-rootfs.tar

New-Item -ItemType Directory -Force rootfs | Out-Null
tar.exe -xf python-rootfs.tar -C rootfs
New-Item -ItemType Directory -Force rootfs\app | Out-Null
Copy-Item agent.py rootfs\app\agent.py

# Required: guest Python ELF names interpreter /lib64/ld-linux-x86-64.so.2,
# but slim image ships loader only under lib\x86_64-linux-gnu (the /lib64
# symlink is lost on Windows extraction). Materialise it or runner
# panics with OpenError(ENOENT) at load_program.
New-Item -ItemType Directory -Force rootfs\lib64 | Out-Null
Copy-Item rootfs\lib\x86_64-linux-gnu\ld-linux-x86-64.so.2 rootfs\lib64\ld-linux-x86-64.so.2

# Required: SONAME symlink libz.so.1 is also lost; only versioned
# libz.so.1.3.1 survives. Without copy, import urllib fails with
# "ImportError: libz.so.1: cannot open shared object file".
Copy-Item rootfs\usr\lib\x86_64-linux-gnu\libz.so.1.3.1 rootfs\usr\lib\x86_64-linux-gnu\libz.so.1
Copy-Item rootfs\lib\x86_64-linux-gnu\libz.so.1.3.1 rootfs\lib\x86_64-linux-gnu\libz.so.1

# Pack files only, no directory entries. `tar.exe -C rootfs .` stores
# directory entries (./usr/, ./lib64/, ...) and guest TarRo lookup then
# fails with OpenError(ENOENT) even though files are in the tar
# (proven: loader invisible until repacked file-only). Windows
# tar.exe has no --no-dir-entries, so feed it a file list (-T).
Get-ChildItem rootfs -Recurse -File |
  ForEach-Object { $_.FullName.Substring((Resolve-Path rootfs).Path.Length + 1).Replace('\','/') } |
  Set-Content -Encoding ascii filelist.txt
tar.exe -cf agent-rootfs.tar -C rootfs -T filelist.txt
tar.exe -tf agent-rootfs.tar | Select-String "usr/local/bin/python3|lib64/ld-linux|app/agent.py"
```

Leave `agent-rootfs.tar` in the `litebox` directory. Run command
below references it as `.\agent-rootfs.tar`. Path is arbitrary —
broker takes it via `--fs-initial-files`; keep flag value in sync
with wherever the tar actually sits.

## Using A Gateway For Your Agent

Put [agentgateway](https://agentgateway.dev/) between the agent and the
LLM provider. Agentgateway is a Rust proxy that gives LLM, MCP, and A2A
traffic one gateway with routing, guardrails, and observability.

```
    Agent (LiteBox guest, 10.0.2.15)
      │  OPENAI_BASE_URL=http://10.0.2.1:4000/v1, dummy key
      ▼  broker guest network (no TUN on Windows)
    agentgateway on Windows 11 host (127.0.0.1:4000)
      │  real key injected, TLS
      ▼
    OpenAI
```

Placement rules:

- **Gateway outside LiteBox, on the host.** Gateway is trusted
  infrastructure; agent is untrusted code. Policy must sit outside
  attacker control. A gateway inside the sandbox could be bypassed by
  the agent it polices.
- **Secrets stay out of the guest.** Gateway holds provider keys and
  injects them on the upstream call (agentgateway backend auth). Guest
  only carries a dummy or virtual key. Key leak from the sandbox is
  then worthless.
- **One enforced exit.** Token rate limiting, per-key budgets, prompt
  guardrails, model routing/failover, and tracing (OpenTelemetry,
  Langfuse/LangSmith) apply at the gateway, not inside agent code the
  model can influence.
- Also route remote MCP tools through the gateway. Agents cannot spawn
  stdio MCP servers (no `fork`), but streamable-HTTP MCP via the
  gateway works, with per-tool authorisation at the gateway.

### Install agentgateway on Windows 11

Official install script (`curl -sL https://agentgateway.dev/install | bash`)
targets Linux/macOS only. On Windows, install the release binary
manually — asset name is `agentgateway-windows-amd64.exe`:

```powershell
New-Item -ItemType Directory -Force C:\agentgateway | Out-Null
Invoke-WebRequest `
  https://github.com/agentgateway/agentgateway/releases/latest/download/agentgateway-windows-amd64.exe `
  -OutFile C:\agentgateway\agentgateway.exe
[Environment]::SetEnvironmentVariable(
  "Path",
  [Environment]::GetEnvironmentVariable("Path", "User") + ";C:\agentgateway",
  "User")
```

Open a new PowerShell window, then verify:

```powershell
agentgateway --version
```

### Configure agentgateway (standalone, on Windows 11 host)

Save the following as as `agentgateway.yaml`

```yaml
config:
  readinessAddr: 127.0.0.1:19001
  statsAddr: 127.0.0.1:19002

frontendPolicies:
  http:
    maxBufferSize: 20971520

llm:
  port: 4000
  models:
  - name: smart
    provider: openAI
    params:
      model: gpt-5.5
      apiKey: $OPENAI_API_KEY
```

Run it (PowerShell, separate window, leave running):

```powershell
$env:OPENAI_API_KEY = "..."      # real key, host only, never in guest
agentgateway -f agentgateway.yaml   # or: cargo run -- -f agentgateway.yaml
```

Ports — do not confuse them:

- `http://localhost:15000/ui/` = agentgateway admin UI (default
  admin address `15000`). Playground/management only. Never an
  LLM base URL.
- `4000` = LLM data plane (`llm.port` in `agentgateway.yaml`).
  Host check: `curl.exe http://localhost:4000/v1/chat/completions`.
- Guest base URL is `http://10.0.2.1:4000/v1`, not
  `http://127.0.0.1:4000/v1`. Inside the guest, `127.0.0.1` is the
  guest itself. Broker translates `10.0.2.1` to host loopback.
  Broker command must also permit that destination:
  `--allow-tcp-destination 10.0.2.1/32:4000` (already in run
  command below).

## Testing and Running The Agent

Live flow on Windows 11, single run: agent in LiteBox → broker →
agentgateway → OpenAI. Agent starts when broker launches the runner
with `/usr/local/bin/python3 /app/agent.py` as the guest program.
Everything runs on the same Windows 11 VM.

Start the agent (PowerShell, from the `litebox` directory):

```powershell
cd litebox
$env:LITEBOX_LOG = "info"
.\target\debug\litebox-broker-userland.exe `
  --fs-initial-files .\agent-rootfs.tar `
  --allow-tcp-destination 10.0.2.1/32:4000 `
  --runner .\target\debug\litebox_runner_linux_on_windows_userland.exe `
  --env LD_LIBRARY_PATH=/usr/local/lib:/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:/lib:/usr/lib `
  --env HOME=/ `
  --env PYTHONDONTWRITEBYTECODE=1 `
  --env OPENAI_BASE_URL=http://10.0.2.1:4000/v1 `
  --env OPENAI_API_KEY=dummy `
  --env MODEL=smart `
  /usr/local/bin/python3 /app/agent.py "hello from inside LiteBox on Windows"
```

What happens:

1. Broker mounts `agent-rootfs.tar`, starts the runner, applies
   guest network policy (guest `10.0.2.15`, host gateway `10.0.2.1`).
2. Runner loads Python inside LiteBox and starts `agent.py` with
   the prompt `hello from inside LiteBox on Windows`.
3. Agent POSTs to `http://10.0.2.1:4000/v1/chat/completions`.
   Broker routes it to agentgateway on host loopback
   (`127.0.0.1:4000`). Agent never sees the real OpenAI key.
4. Agentgateway calls OpenAI (`smart` → `gpt-5.5`), returns the
   reply through the broker. Agent prints it and exits; broker and
   runner then terminate.

Expected: live OpenAI reply printed in this window, request and
token usage visible in the agentgateway window/logs. Provider only
ever sees the gateway; agent only ever sees `10.0.2.1`.

If runner panics with `OpenError(Errno(2 = ENOENT))` at
`load_program`, a guest file is missing from the tar (wrong tar
layout, not a networking failure). Check:

```powershell
tar.exe -tf .\agent-rootfs.tar | Select-String "usr/local/bin/python3|lib64/ld-linux|app/agent.py"
```

Entries must be `usr/local/bin/python3`,
`lib64/ld-linux-x86-64.so.2`, `app/agent.py`. Entries starting
`rootfs/` mean the tar was packed from the wrong directory.

Case 1 — files listed, but guest still `ENOENT` (most common):
tar contains directory entries from `tar.exe -C rootfs .`.
Guest TarRo lookup then cannot resolve files under those
directories — loader itself tests invisible:
`/lib64/ld-linux-x86-64.so.2 --list /usr/local/bin/python3`
panics the same way. Repack file-only and retest:

```powershell
Get-ChildItem rootfs -Recurse -File |
  ForEach-Object { $_.FullName.Substring((Resolve-Path rootfs).Path.Length + 1).Replace('\','/') } |
  Set-Content -Encoding ascii filelist.txt
Remove-Item .\agent-rootfs.tar
tar.exe -cf agent-rootfs.tar -C rootfs -T filelist.txt
.\target\debug\litebox-broker-userland.exe `
  --fs-initial-files .\agent-rootfs.tar `
  --runner .\target\debug\litebox_runner_linux_on_windows_userland.exe `
  /lib64/ld-linux-x86-64.so.2 --list /usr/local/bin/python3
```

Loader must print `libpython3.12.so.1.0`, `libc.so.6`,
`libm.so.6` with no panic. Then run the full agent command.

Case 2 — `python3` and `agent.py` listed, but no
`lib64/ld-linux` at all: Python ELF hardcodes interpreter
`/lib64/ld-linux-x86-64.so.2`; slim image ships loader only at
`lib/x86_64-linux-gnu/ld-linux-x86-64.so.2` and the `/lib64`
symlink is lost on Windows extraction. Materialise, repack
file-only (above), re-run:

```powershell
New-Item -ItemType Directory -Force rootfs\lib64 | Out-Null
Copy-Item rootfs\lib\x86_64-linux-gnu\ld-linux-x86-64.so.2 rootfs\lib64\ld-linux-x86-64.so.2
```

Packaging steps above already include both fixes — these cases
are for tars built before they were added.


If Python starts but dies with
`ImportError: libz.so.1: cannot open shared object file`, tar
holds only versioned `libz.so.1.3.1` — SONAME symlink
`libz.so.1` was lost on Windows extraction, same pattern as
`/lib64` loader. Materialise and repack file-only:

```powershell
Copy-Item rootfs\usr\lib\x86_64-linux-gnu\libz.so.1.3.1 rootfs\usr\lib\x86_64-linux-gnu\libz.so.1
Copy-Item rootfs\lib\x86_64-linux-gnu\libz.so.1.3.1 rootfs\lib\x86_64-linux-gnu\libz.so.1
Get-ChildItem rootfs -Recurse -File |
  ForEach-Object { $_.FullName.Substring((Resolve-Path rootfs).Path.Length + 1).Replace('\','/') } |
  Set-Content -Encoding ascii filelist.txt
Remove-Item .\agent-rootfs.tar
tar.exe -cf agent-rootfs.tar -C rootfs -T filelist.txt
```

Same fix pattern for any later `cannot open shared object`
naming a versioned library: copy `libX.so.<full>` to SONAME
`libX.so.<major>` named in the error, repack, re-run.

## Known blocker — guest networking on Windows (upstream)

Status at `ulitebox` commit `4276ac3e0`: agent code runs, then
`socket()` fails immediately:

```text
OSError: [Errno 5] Input/output error
  at socket.socket.__init__ (socket creation, before connect)
```

Root cause is not configuration. Broker socket policy, guest
address `10.0.2.15`, host gateway `10.0.2.1`, and
`--allow-tcp-destination` all exist, but the Windows host socket
provider does not: `platform_socket_provider` in
`litebox_broker_userland/src/builder.rs` returns
`UnsupportedSocketProvider` on every non-Linux target, whose
`create()` returns `BrokerError::UnsupportedOperation`
(`litebox_broker_core/src/socket.rs`). Guest maps that to `EIO`.
`litebox_broker_platform_windows_userland` currently provides
only sync primitives — no Winsock provider. Linux provider
(`LinuxSocketProvider`, ~2k lines plus TCP/UDP reactors) has no
Windows counterpart yet in any fetched branch.

Consequence: live agent → agentgateway → OpenAI call cannot
complete on Windows today, regardless of base URL or broker
flags. Everything up to the socket call is proven working:
broker/runner start, file-only rootfs loads, Python imports,
agent reaches `socket()`. Unblocking requires upstream (or a
local implementation of) a Windows `SocketProvider` using
Winsock/WSAPoll or IOCP with broker readiness integration —
track LiteBox issues/PRs for `WindowsSocketProvider`. Do not
present this demo as end-to-end live until `socket()` succeeds
in the isolation test:

```powershell
.\target\debug\litebox-broker-userland.exe `
  --fs-initial-files .\agent-rootfs.tar `
  --runner .\target\debug\litebox_runner_linux_on_windows_userland.exe `
  /usr/local/bin/python3 -c 'import socket; s=socket.socket(socket.AF_INET, socket.SOCK_STREAM); print("socket ok")'
```

Success marker: prints `socket ok`. Until then, `EIO` at socket
creation is expected on Windows.

# Moat — Agent Sandbox Quick Start

Run an isolated agent sandbox using Moat with the bubblewrap backend.

## Prerequisites

- Kernel >= 5.13 (Landlock LSM)
- x86_64 architecture

> **macOS users:** Moat requires a native Linux kernel for namespace and cgroup isolation. Use [Path A (Azure VM)](#path-a-azure-vm) to get a Linux host, then install with release binaries. No Docker needed.

## Architecture

```
Host (moat serve)
  ├── gRPC API (PoolService, SessionService, SnapshotService)
  ├── Worker Proxy (routes to sandbox worker via Unix socket)
  ├── Egress Gateway (agentgateway — credential injection, TLS MITM)
  └── SSH Server (session-token auth)
       │
       ├── Sandbox 0 (bwrap namespace)
       │   └── moat-worker (gRPC: exec, read_file, write_file, list_dir)
       ├── Sandbox 1
       └── Sandbox N
```

Each sandbox is an isolated Linux namespace with its own:
- Filesystem (overlayfs CoW)
- Network namespace (veth pair + nftables DNAT)
- PID namespace
- Cgroup resource limits

## Choose Your Install Path

### Path A: Azure VM (recommended for macOS users) {#path-a-azure-vm}

No Docker required. Spin up a Linux VM and install pre-built binaries.

#### A1. Provision the VM

Create an Ubuntu 22.04+ x86_64 VM (e.g., `Standard_D2s_v5`). Open these ports in the NSG:

| Port | Purpose |
|------|---------|
| 22   | SSH access to the VM |
| 8080 | gRPC API + HTTP metrics + MCP endpoints |
| 2222 | SSH server for sandbox shell access |

#### A2. Install moat on the VM

SSH in and install the deb package:

```bash
ssh azureuser@<vm-public-ip>

gh auth login
curl -LO https://github.com/solo-io/moat/releases/download/v0.0.14/moat_0.0.14_amd64.deb
sudo apt-get update && sudo apt-get install -y bubblewrap
sudo dpkg -i moat_0.0.14_amd64.deb
sudo systemctl enable --now moat
```

If you don't want to log into github on the VM:
```
scp moat_0.0.14_amd64.deb mike@172.172.232.13:~/
```

```bash
./moatctl serve --port 8080 &
```

Other install options (RPM, raw binaries) are listed in the [Release Binaries](#release-binaries) section below.

#### A3. Install moatctl on your Mac

Download the `moatctl` binary and point it at the VM:

```bash
export MOAT_URL=http://172.172.232.13:8080
./moatctl --url $MOAT_URL sandbox list
```

Skip to [step 2 — Create a Sandbox](#2-create-a-sandbox).

---

## Using Moat

### 2. Create a Sandbox

#### Basic sandbox (no network)

```bash
echo '{}' | ./moatctl --url $MOAT_URL sandbox create -
```

This returns a sandbox ID like `0`.

#### Sandbox with egress and credential injection

```bash
cat <<'EOF' | moatctl sandbox create -
{
  "network": {
    "hosts": [
      {
        "host": "api.openai.com",
        "ports": [443],
        "headers": [
          {"name": "Authorization", "value": "Bearer ${OPENAI_API_KEY}"}
        ]
      }
    ]
  }
}
EOF
```

The `${OPENAI_API_KEY}` is resolved from the **host** environment — the sandbox never sees the raw key.

#### Sandbox with a named session (persistent snapshots)

```bash
echo '{"session": "my-project"}' | moatctl sandbox create -
```

### 3. Interact with the Sandbox

```bash
# List active sandboxes
moatctl sandbox list

# Execute a command
moatctl sandbox exec <id> -- ls -la /workspace

# Write a file
echo 'print("hello from sandbox")' | moatctl sandbox write-file <id> /workspace/hello.py

# Read a file
moatctl sandbox read-file <id> /workspace/hello.py

# Run the file
moatctl sandbox exec <id> -- python3 /workspace/hello.py

# SSH into the sandbox
moatctl sandbox ssh <id>

# Take a workspace snapshot
moatctl snapshot take <id>

# List snapshots
moatctl snapshot list <id>

# Preview what a restore would change
moatctl snapshot diff <id> 1

# Restore to snapshot 1
moatctl snapshot restore <id> 1
```

### 4. Interactive TUI

```bash
moatctl tui
```

Browse sandboxes, view logs, take snapshots, and create new sandboxes from the terminal UI.

### 5. MCP Endpoint

Each sandbox exposes an MCP endpoint via StreamableHTTP:

```
http://<moat-host>:8080/sandbox/<id>/mcp
```

Available MCP tools: `exec`, `read_file`, `write_file`, `list_dir`, `load_skill`.

### 6. Cleanup

```bash
# Delete a sandbox
moatctl sandbox delete <id>

# If running via Docker:
docker stop moat && docker rm moat
```

---

## Configuration

For custom resource limits, pass a config file:

```bash
cat > config.json <<'EOF'
{
  "port": 8080,
  "slots": 10,
  "sandbox_memory": "512Mi",
  "sandbox_cpu": 1000,
  "sandbox_max_pids": 256,
  "sandbox_disk": "1Gi",
  "ssh_port": 2222
}
EOF
```

## Release Binaries

Pre-built binaries are available from [GitHub Releases](https://github.com/solo-io/moat/releases).

### Deb Package (Debian/Ubuntu)

```bash
curl -LO https://github.com/solo-io/moat/releases/download/v0.0.14/moat_0.0.14_amd64.deb
sudo dpkg -i moat_0.0.14_amd64.deb
sudo systemctl enable --now moat
```

### RPM Package (RHEL/Amazon Linux)

```bash
curl -LO https://github.com/solo-io/moat/releases/download/v0.0.14/moat-0.0.14-1.x86_64.rpm
sudo rpm -i moat-0.0.14-1.x86_64.rpm
sudo systemctl enable --now moat
```

### Raw Binaries

```bash
curl -LO https://github.com/solo-io/moat/releases/download/v0.0.14/moat
curl -LO https://github.com/solo-io/moat/releases/download/v0.0.14/moat-worker
curl -LO https://github.com/solo-io/moat/releases/download/v0.0.14/moatctl

chmod +x moat moat-worker moatctl
sudo mv moat moat-worker /usr/local/bin/
mv moatctl /usr/local/bin/

sudo moat serve --port 8080
```

### Release Assets Reference

| Asset | Description |
|-------|-------------|
| `moat` | Pool manager binary (static musl, ~61MB) |
| `moat-worker` | Sandbox worker binary (~5.5MB) |
| `moatctl` | CLI/TUI client (~4.4MB) |
| `moat-mcp` | MCP client binary (~7.4MB) |
| `moat_0.0.14_amd64.deb` | Debian package (includes moat + moat-worker + systemd unit) |
| `moat-0.0.14-1.x86_64.rpm` | RPM package (same contents) |
| `vmlinux` | Firecracker guest kernel (~58MB, only needed for Firecracker backend) |
| `rootfs.ext4` | Firecracker guest rootfs (~512MB, only needed for Firecracker backend) |

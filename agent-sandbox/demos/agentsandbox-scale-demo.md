## Firecracker Scale Demo

This demo shows the "insane" performance characteristics of moat with Firecracker: warm pool cloning, suspend/resume oversubscription, and fleet failover.

**What it demonstrates:** Firecracker microVMs enable sub-second sandbox creation, 3x+ memory oversubscription via suspend/resume, and automatic failover across hosts.


### Firecracker At Scale

| Feature | Demo Scale | Production Scale |
|---------|------------|------------------|
| **Warm Pool Cloning** | 10 sandboxes in < 100ms | 1000 sandboxes in < 10s |
| **Suspend/Resume** | 10 logical, 3 physical (3x oversubscribe) | 1000 logical, 100 physical (10x) |
| **Resume Latency** | ~50ms to wake suspended sandbox | Same |
| **Memory Overhead** | ~5MB per microVM | Same |
| **Failover** | 5 sandboxes reschedule in < 1s | 500 sandboxes reschedule |

---

### Azure Setup

Create 3 VMs with nested virtualization support:

```bash
# Create resource group
az group create --name moat-demo --location eastus

# Create VNet
az network vnet create \
  --resource-group moat-demo \
  --name moat-vnet \
  --subnet-name default

# Create Fleet VM (smaller - just runs controller)
az vm create \
  --resource-group moat-demo \
  --name moat-fleet \
  --image Ubuntu2204 \
  --size Standard_D2s_v3 \
  --admin-username azureuser \
  --admin-password 'Password12!@' \
  --authentication-type password \
  --vnet-name moat-vnet \
  --subnet default \
  --public-ip-sku Standard

# Create Host VMs (larger - run Firecracker microVMs)
for host in host1 host2; do
  az vm create \
    --resource-group moat-demo \
    --name moat-$host \
    --image Ubuntu2204 \
    --size Standard_D4s_v3 \
    --admin-username azureuser \
    --admin-password 'Password12!@' \
    --authentication-type password \
    --vnet-name moat-vnet \
    --subnet default \
    --public-ip-sku Standard
done

# Get VM IPs
az vm list-ip-addresses --resource-group moat-demo --output table
```

**Verify KVM works (SSH into each host VM):**
```bash
sudo apt update && sudo apt install -y cpu-checker
kvm-ok
# Should say: "KVM acceleration can be used"
```

**VM Summary:**

| VM | Size | Purpose |
|----|------|---------|
| moat-fleet | Standard_D2s_v3 (2 vCPU, 8GB) | Fleet controller |
| moat-host1 | Standard_D4s_v3 (4 vCPU, 16GB) | moat + Firecracker |
| moat-host2 | Standard_D4s_v3 (4 vCPU, 16GB) | moat + Firecracker |

> **Note:** Dv3 series supports nested virtualization. If you have quota for Dv5 series, those work too.

---

### Install Firecracker (on each host VM)

**Install Firecracker:**
```bash
# Download Firecracker
FIRECRACKER_VERSION="1.6.0"
curl -L -o firecracker.tgz \
  https://github.com/firecracker-microvm/firecracker/releases/download/v${FIRECRACKER_VERSION}/firecracker-v${FIRECRACKER_VERSION}-x86_64.tgz
tar -xzf firecracker.tgz
sudo mv release-v${FIRECRACKER_VERSION}-x86_64/firecracker-v${FIRECRACKER_VERSION}-x86_64 /usr/local/bin/firecracker
sudo mv release-v${FIRECRACKER_VERSION}-x86_64/jailer-v${FIRECRACKER_VERSION}-x86_64 /usr/local/bin/jailer

# Verify
firecracker --version
```

**Install build dependencies:**
```bash
# Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"

# Install build tools
sudo apt-get install -y build-essential pkg-config libssl-dev git unzip

# Install protoc (need v25+ for proto3 optional fields)
PROTOC_VERSION="25.1"
curl -LO "https://github.com/protocolbuffers/protobuf/releases/download/v${PROTOC_VERSION}/protoc-${PROTOC_VERSION}-linux-x86_64.zip"
sudo unzip -o protoc-${PROTOC_VERSION}-linux-x86_64.zip -d /usr/local
rm protoc-${PROTOC_VERSION}-linux-x86_64.zip
```

**Install moat:**
```bash
# Clone and build
git clone https://github.com/anthropics/moat.git
cd moat
make build
make build-worker

# Install binaries
sudo cp target/release/moat /usr/local/bin/
sudo cp target/release/moat-worker /usr/local/bin/
```

**Build Firecracker rootfs:**
```bash
./scripts/build-firecracker-rootfs.sh ~/.local/state/moat/firecracker-rootfs
```

---

### Demo 1: Burst Creation (Warm Pool)

**Goal:** Create 10 sandboxes in < 100ms using warm pool cloning.

**Step 1: Start moat with Firecracker backend and warm pool**

```bash
cat > moat-firecracker.json << 'EOF'
{
  "port": 8080,
  "slots": 10,
  "backend": {
    "firecracker": {
      "kernel": "/var/lib/moat/vmlinux",
      "rootfs": "~/.local/state/moat/firecracker-rootfs",
      "template_pool_size": 2
    }
  }
}
EOF

moat serve --config moat-firecracker.json
```

**Step 2: Wait for warm pool to initialize**

```bash
# Check pool status
moatctl pool status
# Should show: "template_pool: 2 ready"
```

**Step 3: Burst create 10 sandboxes**

```bash
# Time the creation
time for i in {1..10}; do
  echo '{}' | moatctl sandbox create -q - &
done
wait

# Expected: < 100ms total (10 sandboxes × ~4ms each from warm pool)
```

**Step 4: Verify all running**

```bash
moatctl sandbox list
# Should show 10 sandboxes in "Running" state
```

---

### Demo 2: Suspend/Resume Oversubscription

**Goal:** Run 10 logical sandboxes with only 3 physical VMs (3x oversubscription).

**Step 1: Start moat with physical capacity limit**

```bash
cat > moat-oversubscribe.json << 'EOF'
{
  "port": 8080,
  "slots": 10,
  "physical_slots": 3,
  "backend": {
    "firecracker": {
      "kernel": "/var/lib/moat/vmlinux",
      "rootfs": "~/.local/state/moat/firecracker-rootfs"
    }
  }
}
EOF

moat serve --config moat-oversubscribe.json
```

**Step 2: Create 10 sandboxes**

```bash
for i in {1..10}; do
  echo "{\"session\": \"sandbox-$i\"}" | moatctl sandbox create -q -
done
```

**Step 3: Check physical vs logical state**

```bash
moatctl sandbox list
# Expected:
# - 3 sandboxes: STATE=Running
# - 7 sandboxes: STATE=Suspended
```

**Step 4: Access a suspended sandbox (triggers wake)**

```bash
# Get a suspended sandbox ID
SUSPENDED_ID=$(moatctl sandbox list --json | jq -r '.[] | select(.state == "Suspended") | .id' | head -1)

# Time the resume
time moatctl sandbox exec $SUSPENDED_ID -- echo "I'm awake!"
# Expected: ~50ms resume time

# Check state again
moatctl sandbox list
# The accessed sandbox is now Running; another one was suspended to make room
```

**Step 5: Show the "musical chairs" effect**

```bash
# Access multiple suspended sandboxes in sequence
for i in 4 5 6 7; do
  SANDBOX_ID=$(moatctl sandbox list --json | jq -r ".[] | select(.session == \"sandbox-$i\") | .id")
  echo "Accessing sandbox-$i..."
  time moatctl sandbox exec $SANDBOX_ID -- hostname
  moatctl sandbox list | grep -E "Running|Suspended" | head -5
  echo "---"
done
```

---

### Demo 3: Fleet Failover

**Goal:** Kill a moat host, watch sandboxes automatically reschedule to survivors.

**Setup:** Requires 2 moat host VMs + 1 fleet controller VM.

**Step 1: Start the fleet controller**

```bash
# On Fleet VM
cat > fleet-config.json << 'EOF'
{
  "listen": "0.0.0.0:9090",
  "store": {
    "memory": {}
  }
}
EOF

moat-fleet serve --config fleet-config.json
```

Note: Using in-memory store for the demo. For production, use PostgreSQL.

**Step 2: Start moat hosts (on each host VM)**

```bash
# On Host 1
moat serve --port 8080 --slots 10 \
  --fleet-url http://fleet-vm:9090 \
  --host-id host-1

# On Host 2
moat serve --port 8080 --slots 10 \
  --fleet-url http://fleet-vm:9090 \
  --host-id host-2
```

**Step 3: Create 10 sandboxes via fleet**

```bash
# On Fleet VM (or anywhere with access)
for i in {1..10}; do
  echo "{\"session\": \"sandbox-$i\"}" | moatctl --url http://fleet-vm:9090 sandbox create -q -
done

# Check distribution
moatctl --url http://fleet-vm:9090 sandbox list
# Expected: ~5 sandboxes on host-1, ~5 on host-2
```

**Step 4: Kill host-2**

```bash
# On Host 2 VM
sudo systemctl stop moat
# Or: kill the moat process
```

**Step 5: Watch failover**

```bash
# On Fleet VM - watch sandboxes reschedule
watch -n 1 'moatctl --url http://fleet-vm:9090 sandbox list'

# Within ~10 seconds:
# - host-2 marked as dead
# - sandboxes 6-10 rescheduled to host-1
# - All 10 sandboxes now on host-1
```

**Step 6: Verify sandboxes are functional**

```bash
# Access a rescheduled sandbox
SANDBOX_ID=$(moatctl --url http://fleet-vm:9090 sandbox list --json | jq -r '.[0].id')
moatctl --url http://fleet-vm:9090 sandbox exec $SANDBOX_ID -- echo "Still alive after failover!"
```

---

### Key Metrics to Highlight

| Metric | Value | Why It Matters |
|--------|-------|----------------|
| **Warm clone time** | ~4ms | 250x faster than cold boot |
| **Resume time** | ~50ms | Feels instant to users |
| **Memory overhead** | ~5MB/VM | Run 200 VMs in 1GB overhead |
| **Failover time** | < 10s | Minimal disruption |
| **Oversubscription** | 3-10x | Massive cost savings |

### Key Takeaways

- **Warm pool = instant sandboxes** — Pre-snapshot VMs, clone in milliseconds
- **Suspend/resume = infinite scale** — Physical capacity limits don't limit logical capacity
- **Fleet failover = reliability** — Host dies, sandboxes survive
- **The numbers scale linearly** — 10 in demo = 1000 in production, same mechanisms

---

### Cleanup (Azure)

Delete all resources when done:

```bash
az group delete --name moat-demo --yes --no-wait
```
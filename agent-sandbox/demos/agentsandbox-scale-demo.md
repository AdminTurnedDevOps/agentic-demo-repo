## Firecracker Scale Demo

This is an AWS-first runbook for running `moat` with the Firecracker backend at demo scale.

This version reflects the working path we verified on AWS on April 16, 2026:

- `moat-fleet`: `t3.large`
- `moat-host1`: `m8i.2xlarge`
- `moat-host2`: `m8i.2xlarge`
- dedicated `30 GiB` gp3 EBS volume on each host mounted at `/var/lib/moat`
- Firecracker configs using `workspace_storage: "block"`
- `data_dir` and `base_dir` moved onto the EBS volume

If you want the highest-probability cloud path for nested virtualization with `moat`, AWS is the best first target.

---

### What This Runbook Covers

1. Prepare host storage on AWS
2. Run a single-host Firecracker demo
3. Run a single-host oversubscription demo
4. Run a two-host fleet demo
5. Clean up each demo after testing

---

### Recommended AWS Topology

| Node | Recommended Type | Purpose |
|---|---|---|
| `moat-fleet` | `t3.large` or `t3.xlarge` | Fleet controller only |
| `moat-host1` | `m8i.2xlarge` or larger | `moat` + Firecracker |
| `moat-host2` | `m8i.2xlarge` or larger | `moat` + Firecracker |

Use `M8i`, `C8i`, or `R8i` instances for the hosts. For maximum confidence, use bare-metal EC2.

---

### Prerequisites

Before running the demos, make sure:

- the three EC2 instances exist and are reachable over SSH
- current `moat`, `moatctl`, `moat-worker`, and `moat-fleet` binaries are installed
- `firecracker` is installed on both host VMs
- `/var/lib/moat/vmlinux` and `/var/lib/moat/rootfs.ext4` exist on both host VMs
- `jq` is installed on the fleet and host VMs

All configs below assume `/var/lib/moat` is backed by a dedicated EBS volume.

---

### Build and Install `moat-fleet` on the Fleet VM

Run this on `moat-fleet`:

```bash
sudo apt-get update
sudo apt-get install -y git jq curl

GO_VERSION="1.22.2"
curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" | sudo tar -C /usr/local -xz
echo 'export PATH=$PATH:/usr/local/go/bin' >> ~/.bashrc
export PATH=$PATH:/usr/local/go/bin

git clone https://github.com/solo-io/moat.git
cd moat/fleet
go build -o moat-fleet ./cmd/moat-fleet
sudo install -m 0755 moat-fleet /usr/local/bin/moat-fleet
```

---

### Demo 1: Single-Host Firecracker Bring-Up

Demo 1 proves the basic Firecracker bring-up path works on a single host.

Success means:

- `moat` starts with the Firecracker backend
- the template VM boots and snapshots successfully
- cloned sandboxes become `Running` and `ready`
- `moatctl` can see and manage the sandboxes

On `moat-host1`, create the config:

```bash
cat > /tmp/moat-firecracker.json <<'EOF'
{
  "port": 8080,
  "slots": 10,
  "data_dir": "/var/lib/moat/state",
  "base_dir": "/var/lib/moat/base",
  "backend": {
    "firecracker": {
      "kernel_image": "/var/lib/moat/vmlinux",
      "rootfs": "/var/lib/moat/rootfs.ext4",
      "workspace_storage": "block"
    }
  }
}
EOF
```

Start `moat`:

```bash
sudo moat serve --config /tmp/moat-firecracker.json --log-format json
```

From another shell on the same host, create a few sandboxes:

```bash
for i in $(seq 1 5); do
  echo '{}' | moatctl --url http://localhost:8080 sandbox create -q -
done

moatctl --url http://localhost:8080 sandbox list
moatctl --url http://localhost:8080 pool resources
```

Expected result:

- the startup log shows template creation and snapshot success
- `moatctl sandbox list` shows the created sandboxes as `Running` and `ready`

Clean up Demo 1 before moving on:

```bash
moatctl --url http://localhost:8080 --json sandbox list | jq -r '.[].id' | while read -r id; do
  [ -n "$id" ] || continue
  moatctl --url http://localhost:8080 sandbox delete --yes "$id"
done

sudo pkill -f 'moat serve --config /tmp/moat-firecracker.json' || true
sudo pkill -f '/usr/local/bin/firecracker --api-sock' || true
for m in $(mount | grep workspace_snapshot_mount | sed -E 's#.* on ([^ ]*workspace_snapshot_mount) type .*#\1#' | sort -r); do
  sudo umount -l "$m" || true
done
sudo rm -rf /var/lib/moat/state/slots/* /var/lib/moat/state/sessions/*
```

---

### Demo 2: Single-Host Oversubscription

Demo 2 verifies that one host can hold more sandboxes than its configured physical capacity by suspending inactive VMs and restoring them on demand.

On `moat-host1`, restart `moat` with a physical capacity limit:

```bash
cat > /tmp/moat-oversubscribe.json <<'EOF'
{
  "port": 8080,
  "slots": 10,
  "physical_capacity": 3,
  "data_dir": "/var/lib/moat/state",
  "base_dir": "/var/lib/moat/base",
  "backend": {
    "firecracker": {
      "kernel_image": "/var/lib/moat/vmlinux",
      "rootfs": "/var/lib/moat/rootfs.ext4",
      "workspace_storage": "block"
    }
  }
}
EOF

sudo moat serve --config /tmp/moat-oversubscribe.json --log-format json
```

Create ten sandboxes with unique sessions:

```bash
for i in $(seq 1 10); do
  echo "{\"session\":\"sandbox-$i\"}" | moatctl --url http://localhost:8080 sandbox create -q -
done

moatctl --url http://localhost:8080 sandbox list
moatctl --url http://localhost:8080 pool resources
```

Wake one suspended sandbox:

```bash
SUSPENDED_ID=$(moatctl --url http://localhost:8080 --json sandbox list | jq -r '.[] | select(.phase=="suspended") | .id' | head -1)
moatctl --url http://localhost:8080 sandbox exec "$SUSPENDED_ID" -- echo awake
moatctl --url http://localhost:8080 sandbox list
```

Expected result:

- before the wake, only `physical_capacity` sandboxes are running and the rest are suspended
- the `sandbox exec` wakes the suspended sandbox and prints `awake`
- after the wake, the target sandbox becomes running and another sandbox may move back to `Suspended` to keep running capacity at `3`

Clean up Demo 2 before moving on:

```bash
moatctl --url http://localhost:8080 --json sandbox list | jq -r '.[].id' | while read -r id; do
  [ -n "$id" ] || continue
  moatctl --url http://localhost:8080 sandbox delete --yes "$id"
done

sudo pkill -f 'moat serve --config /tmp/moat-oversubscribe.json' || true
sudo pkill -f '/usr/local/bin/firecracker --api-sock' || true
for m in $(mount | grep workspace_snapshot_mount | sed -E 's#.* on ([^ ]*workspace_snapshot_mount) type .*#\1#' | sort -r); do
  sudo umount -l "$m" || true
done
sudo rm -rf /var/lib/moat/state/slots/* /var/lib/moat/state/sessions/*
```

---

### Demo 3: Fleet on AWS

This uses the current fleet controller config format and current host-side `fleet.address` config.

Get your AWS account ID locally:

```bash
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

On `moat-fleet`, create the fleet config:

```bash
cat > /tmp/fleet-config.json <<EOF
{
  "listen_addr": "0.0.0.0:9090",
  "auth": {
    "provider": "aws",
    "aws": {
      "allowed_account_ids": ["${AWS_ACCOUNT_ID}"],
      "allowed_arn_patterns": ["arn:aws:sts::*:assumed-role/${DEMO_NAME}-host-role/*"]
    }
  }
}
EOF
```

Start the fleet controller:

```bash
moat-fleet -config /tmp/fleet-config.json
```

On `moat-host1`, create the host config:

```bash
cat > /tmp/moat-host1.json <<EOF
{
  "port": 8080,
  "slots": 10,
  "data_dir": "/var/lib/moat/state",
  "base_dir": "/var/lib/moat/base",
  "backend": {
    "firecracker": {
      "kernel_image": "/var/lib/moat/vmlinux",
      "rootfs": "/var/lib/moat/rootfs.ext4",
      "workspace_storage": "block"
    }
  },
  "fleet": {
    "address": "http://${FLEET_PRIVATE_IP}:9090",
    "advertise_address": "http://${HOST1_PRIVATE_IP}:8080"
  }
}
EOF
```

On `moat-host2`, create the host config:

```bash
cat > /tmp/moat-host2.json <<EOF
{
  "port": 8080,
  "slots": 10,
  "data_dir": "/var/lib/moat/state",
  "base_dir": "/var/lib/moat/base",
  "backend": {
    "firecracker": {
      "kernel_image": "/var/lib/moat/vmlinux",
      "rootfs": "/var/lib/moat/rootfs.ext4",
      "workspace_storage": "block"
    }
  },
  "fleet": {
    "address": "http://${FLEET_PRIVATE_IP}:9090",
    "advertise_address": "http://${HOST2_PRIVATE_IP}:8080"
  }
}
EOF
```

Start both hosts:

```bash
sudo moat serve --config /tmp/moat-host1.json --log-format json
```

```bash
sudo moat serve --config /tmp/moat-host2.json --log-format json
```

Create sandboxes through the fleet controller from `moat-fleet`:

```bash
for i in $(seq 1 10); do
  echo "{\"session\":\"fleet-$i\"}" | moatctl --url "http://${FLEET_PRIVATE_IP}:9090" sandbox create -q -
done

moatctl --url "http://${FLEET_PRIVATE_IP}:9090" sandbox list
```

Expected result:

- the controller assigns sandboxes across both hosts
- `moatctl --url "http://${FLEET_PRIVATE_IP}:9090" sandbox list` shows controller-level assignment metadata
- to inspect runtime state such as `Running` and `ready`, query each host directly with `moatctl --url http://localhost:8080 sandbox list`

To simulate host loss, stop `moat` on one host:

```bash
sudo pkill -f 'moat serve --config /tmp/moat-host1.json' || true
```

Then wait for the lease to expire and inspect the controller and surviving host:

```bash
moatctl --url "http://${FLEET_PRIVATE_IP}:9090" sandbox list
moatctl --url http://localhost:8080 sandbox list
```

Create one more sandbox after failover:

```bash
echo "{\"session\":\"fleet-after-failover\"}" | moatctl --url "http://${FLEET_PRIVATE_IP}:9090" sandbox create -q -
```

Expected result after host loss:

- after lease expiry and grace period, the controller marks the lost host dead
- the controller cleans up orphaned sandboxes from the dead host
- the surviving host keeps serving its existing sandboxes
- new sandboxes are scheduled onto the surviving host

Clean up Demo 3 after testing:

```bash
moatctl --url "http://${FLEET_PRIVATE_IP}:9090" --json sandbox list | jq -r '.[].id' | while read -r id; do
  [ -n "$id" ] || continue
  moatctl --url "http://${FLEET_PRIVATE_IP}:9090" sandbox delete --yes "$id"
done
```

Stop the fleet controller:

```bash
pkill -f 'moat-fleet -config /tmp/fleet-config.json' || true
```

Then on each host:

```bash
sudo pkill -f 'moat serve --config /tmp/moat-host1.json' || true
sudo pkill -f 'moat serve --config /tmp/moat-host2.json' || true
sudo pkill -f '/usr/local/bin/firecracker --api-sock' || true
for m in $(mount | grep workspace_snapshot_mount | sed -E 's#.* on ([^ ]*workspace_snapshot_mount) type .*#\\1#' | sort -r); do
  sudo umount -l "$m" || true
done
sudo rm -rf /var/lib/moat/state/slots/* /var/lib/moat/state/sessions/*
```

---

### Final Cleanup

Terminate the three EC2 instances:

```bash
aws ec2 terminate-instances \
  --region "$AWS_REGION" \
  --instance-ids i-aaaaaaaaaaaaaaaaa i-bbbbbbbbbbbbbbbbb i-ccccccccccccccccc
```

Delete the instance profile, role, and security group when you are done:

```bash
aws iam remove-role-from-instance-profile \
  --instance-profile-name "${DEMO_NAME}-host-profile" \
  --role-name "${DEMO_NAME}-host-role"

aws iam delete-instance-profile \
  --instance-profile-name "${DEMO_NAME}-host-profile"

aws iam delete-role \
  --role-name "${DEMO_NAME}-host-role"

aws ec2 delete-security-group \
  --region "$AWS_REGION" \
  --group-id "$SG_ID"
```

Delete the two data volumes after the instances are terminated:

```bash
aws ec2 delete-volume \
  --region "$AWS_REGION" \
  --volume-id "$HOST1_DATA_VOL"

aws ec2 delete-volume \
  --region "$AWS_REGION" \
  --volume-id "$HOST2_DATA_VOL"
```

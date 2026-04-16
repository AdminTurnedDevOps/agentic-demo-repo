## Firecracker Scale Demo

This is an AWS-first runbook for running `moat` with the Firecracker backend at demo scale.

The goal is to get a real setup running with the current repo layout and current CLI/config surface:

- 1 fleet controller VM
- 2 `moat` host VMs
- Firecracker-backed sandboxes on the hosts
- optional fleet failover across both hosts

If you want the highest-probability path, use AWS bare metal for the two `moat` hosts. If you want a cheaper demo, AWS now supports nested virtualization on `C8i`, `M8i`, and `R8i`; the runbook below uses those families.

---

### What This Demo Covers

1. Provision 3 EC2 instances on AWS
2. Build and install current `moat`, `moatctl`, `moat-worker`, and `moat-fleet`
3. Build a Firecracker rootfs and install the Firecracker kernel/binary
4. Run a single-host Firecracker demo
5. Run a two-host fleet demo

This document intentionally avoids the stale config fields and flags from older versions of `moat`.

---

### Recommended AWS Topology

| Node | Recommended Type | Purpose |
|---|---|---|
| `moat-fleet` | `t3.large` or `t3.xlarge` | Fleet controller only |
| `moat-host1` | `m8i.2xlarge` or larger | `moat` + Firecracker |
| `moat-host2` | `m8i.2xlarge` or larger | `moat` + Firecracker |

Use M8i, C8i, or R8i instances for the hosts — these support nested virtualization (KVM) by default. For maximum confidence, use bare-metal EC2.

---

### AWS Prerequisites

- AWS CLI configured for the target account and region
- A default VPC/subnet, or an existing VPC/subnet you want to reuse
- An Ubuntu x86_64 AMI ID for your region

Set a few variables locally before creating instances:

```bash
export AWS_REGION=us-east-1
export AMI_ID=ami-xxxxxxxxxxxxxxxxx   # Ubuntu 22.04 x86_64 for your region
export DEMO_NAME=moat-demo
```

If you want to use the default VPC:

```bash
export VPC_ID=$(aws ec2 describe-vpcs \
  --region "$AWS_REGION" \
  --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' \
  --output text)

export SUBNET_ID=$(aws ec2 describe-subnets \
  --region "$AWS_REGION" \
  --filters Name=vpc-id,Values="$VPC_ID" Name=default-for-az,Values=true \
  --query 'Subnets[0].SubnetId' \
  --output text)
```

---

### Create Key Pair, Security Group, and Instance Profile

Create an SSH key pair:

```bash
aws ec2 create-key-pair \
  --region "$AWS_REGION" \
  --key-name "$DEMO_NAME-key" \
  --query 'KeyMaterial' \
  --output text > "${DEMO_NAME}.pem"

chmod 600 "${DEMO_NAME}.pem"
```

Create a security group:

```bash
export SG_ID=$(aws ec2 create-security-group \
  --region "$AWS_REGION" \
  --group-name "$DEMO_NAME-sg" \
  --description "moat Firecracker demo" \
  --vpc-id "$VPC_ID" \
  --query 'GroupId' \
  --output text)
```

Allow SSH from anywhere and allow east-west traffic between all demo nodes:

```bash
aws ec2 authorize-security-group-ingress \
  --region "$AWS_REGION" \
  --group-id "$SG_ID" \
  --protocol tcp \
  --port 22 \
  --cidr "0.0.0.0/0"

aws ec2 authorize-security-group-ingress \
  --region "$AWS_REGION" \
  --group-id "$SG_ID" \
  --protocol -1 \
  --source-group "$SG_ID"
```

Create an instance profile for the two `moat` hosts. This gives them AWS credentials so the fleet controller can authenticate them with the AWS provider:

```bash
cat > trust-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "ec2.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

aws iam create-role \
  --role-name "${DEMO_NAME}-host-role" \
  --assume-role-policy-document file://trust-policy.json

aws iam create-instance-profile \
  --instance-profile-name "${DEMO_NAME}-host-profile"

aws iam add-role-to-instance-profile \
  --instance-profile-name "${DEMO_NAME}-host-profile" \
  --role-name "${DEMO_NAME}-host-role"
```

---

### Launch the Fleet VM

```bash
aws ec2 run-instances \
  --region "$AWS_REGION" \
  --image-id "$AMI_ID" \
  --instance-type t3.large \
  --key-name "$DEMO_NAME-key" \
  --security-group-ids "$SG_ID" \
  --subnet-id "$SUBNET_ID" \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=moat-fleet}]' \
  --count 1
```

### Launch the Two Firecracker Hosts

Use M8i, C8i, or R8i instances with nested virtualization explicitly enabled:

```bash
for host in moat-host1 moat-host2; do
  aws ec2 run-instances \
    --region "$AWS_REGION" \
    --image-id "$AMI_ID" \
    --instance-type m8i.2xlarge \
    --cpu-options NestedVirtualization=enabled \
    --iam-instance-profile Name="${DEMO_NAME}-host-profile" \
    --key-name "$DEMO_NAME-key" \
    --security-group-ids "$SG_ID" \
    --subnet-id "$SUBNET_ID" \
    --associate-public-ip-address \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$host}]" \
    --count 1
done
```

> **Note:** The `--cpu-options NestedVirtualization=enabled` flag requires AWS CLI v2.34.30 or newer. Run `aws --version` to check, and `brew upgrade awscli` (macOS) or `pip install --upgrade awscli` to update.

Get the instance IDs and IP addresses:

```bash
aws ec2 describe-instances \
  --region "$AWS_REGION" \
  --filters "Name=tag:Name,Values=moat-fleet,moat-host1,moat-host2" "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].{Name:Tags[?Key==`Name`]|[0].Value,InstanceId:InstanceId,PrivateIp:PrivateIpAddress,PublicIp:PublicIpAddress,Type:InstanceType}' \
  --output table
```

Export the public and private IPs you will use later:

```bash
export FLEET_PUBLIC_IP=...
export FLEET_PRIVATE_IP=...
export HOST1_PUBLIC_IP=...
export HOST1_PRIVATE_IP=...
export HOST2_PUBLIC_IP=...
export HOST2_PRIVATE_IP=...
```

SSH pattern:

```bash
ssh -i "${DEMO_NAME}.pem" ubuntu@"$HOST1_PUBLIC_IP"
```

---

### Install Base Dependencies

Run this on all three machines:

```bash
sudo apt-get update
sudo apt-get install -y \
  build-essential \
  pkg-config \
  libssl-dev \
  musl-tools \
  git \
  unzip \
  jq \
  curl
```

Install `protoc` 25.1 or newer on all machines where you will build Rust or Go binaries:

```bash
PROTOC_VERSION=25.1
curl -LO "https://github.com/protocolbuffers/protobuf/releases/download/v${PROTOC_VERSION}/protoc-${PROTOC_VERSION}-linux-x86_64.zip"
sudo unzip -o "protoc-${PROTOC_VERSION}-linux-x86_64.zip" -d /usr/local
rm -f "protoc-${PROTOC_VERSION}-linux-x86_64.zip"
```

---

### Build and Install `moat` on the Two Firecracker Hosts

Run this on `moat-host1` and `moat-host2`:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"

rustup target add x86_64-unknown-linux-musl

git clone https://github.com/solo-io/moat.git
cd moat

cargo build --release -p moat -p moatctl
cargo build --release -p moat-worker --target x86_64-unknown-linux-musl

sudo install -m 0755 target/release/moat /usr/local/bin/moat
sudo install -m 0755 target/release/moatctl /usr/local/bin/moatctl
sudo install -m 0755 target/x86_64-unknown-linux-musl/release/moat-worker /usr/local/bin/moat-worker
```

Install Firecracker on the two hosts:

```bash
FIRECRACKER_VERSION=1.6.0
curl -L -o firecracker.tgz \
  "https://github.com/firecracker-microvm/firecracker/releases/download/v${FIRECRACKER_VERSION}/firecracker-v${FIRECRACKER_VERSION}-x86_64.tgz"
tar -xzf firecracker.tgz
sudo install -m 0755 "release-v${FIRECRACKER_VERSION}-x86_64/firecracker-v${FIRECRACKER_VERSION}-x86_64" /usr/local/bin/firecracker
sudo install -m 0755 "release-v${FIRECRACKER_VERSION}-x86_64/jailer-v${FIRECRACKER_VERSION}-x86_64" /usr/local/bin/jailer
firecracker --version
```

Build the Firecracker rootfs:

```bash
cd ~/moat
sudo mkdir -p /var/lib/moat
sudo ./scripts/build-rootfs.sh /var/lib/moat/rootfs.ext4
```

Install the Firecracker kernel image:

```bash
curl -fsSL -o /tmp/vmlinux.bin \
  "https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.5/x86_64/vmlinux-5.10.186"
sudo mv /tmp/vmlinux.bin /var/lib/moat/vmlinux
```

Load the host-side vsock modules and verify KVM:

```bash
sudo modprobe vsock
sudo modprobe vhost_vsock
ls -l /dev/kvm
egrep -wo 'vmx|svm' /proc/cpuinfo | head
```

---

### Build and Install `moat-fleet` on the Fleet VM

Run this on `moat-fleet`:

```bash
sudo apt-get update
sudo apt-get install -y git jq curl

# Install Go 1.22
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

Use this first on `moat-host1` before adding fleet.

Create a current Firecracker config:

```bash
cat > /tmp/moat-firecracker.json <<'EOF'
{
  "port": 8080,
  "slots": 10,
  "backend": {
    "firecracker": {
      "kernel_image": "/var/lib/moat/vmlinux",
      "rootfs": "/var/lib/moat/rootfs.ext4"
    }
  }
}
EOF
```

Start `moat`:

```bash
sudo moat serve --config /tmp/moat-firecracker.json --log-format json
```

You want to see the host create Firecracker templates during startup. Once the server is up, create a few sandboxes from another shell on the same host:

```bash
for i in $(seq 1 5); do
  echo '{}' | moatctl sandbox create -q -
done

moatctl sandbox list
moatctl pool resources
```

---

### Demo 2: Single-Host Oversubscription

Restart `moat` on `moat-host1` with a physical capacity limit:

```bash
cat > /tmp/moat-oversubscribe.json <<'EOF'
{
  "port": 8080,
  "slots": 10,
  "physical_capacity": 3,
  "backend": {
    "firecracker": {
      "kernel_image": "/var/lib/moat/vmlinux",
      "rootfs": "/var/lib/moat/rootfs.ext4"
    }
  }
}
EOF

sudo moat serve --config /tmp/moat-oversubscribe.json --log-format json
```

Create 10 sandboxes:

```bash
for i in $(seq 1 10); do
  echo "{\"session\":\"sandbox-$i\"}" | moatctl sandbox create -q -
done

moatctl sandbox list
moatctl pool resources
```

Wake one suspended sandbox:

```bash
SUSPENDED_ID=$(moatctl --json sandbox list | jq -r '.[] | select(.state=="Suspended") | .id' | head -1)
moatctl sandbox exec "$SUSPENDED_ID" -- echo "awake"
moatctl sandbox list
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
  "backend": {
    "firecracker": {
      "kernel_image": "/var/lib/moat/vmlinux",
      "rootfs": "/var/lib/moat/rootfs.ext4"
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
  "backend": {
    "firecracker": {
      "kernel_image": "/var/lib/moat/vmlinux",
      "rootfs": "/var/lib/moat/rootfs.ext4"
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

To simulate host loss, stop `moat` on one host and watch assignments rebalance:

```bash
watch -n 1 "moatctl --url http://${FLEET_PRIVATE_IP}:9090 sandbox list"
```

---

### Notes on Current `moat` Surface

Use these names in configs and commands:

- `kernel_image`, not `kernel`
- `physical_capacity`, not `physical_slots`
- `listen_addr`, not `listen`
- `database_url` if you want persistent fleet storage
- `moat-fleet -config ...`, not `moat-fleet serve --config ...`
- host-side fleet config lives under `fleet.address`
- `moatctl pool resources`, not `moatctl pool status`

---

### Cleanup

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

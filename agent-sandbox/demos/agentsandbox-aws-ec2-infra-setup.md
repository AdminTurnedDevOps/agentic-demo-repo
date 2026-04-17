## Firecracker Scale Demo

This is the EC2 configuration for running `moat` demos in AWS.

## What This Covers

1. Provision 3 EC2 instances on AWS
2. Ensure proper storage sizes
3. Build a Firecracker rootfs and install the Firecracker kernel/binary

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
export FLEET_PUBLIC_IP=$(aws ec2 describe-instances \
  --region "$AWS_REGION" \
  --filters "Name=tag:Name,Values=moat-fleet" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text)

export FLEET_PRIVATE_IP=$(aws ec2 describe-instances \
  --region "$AWS_REGION" \
  --filters "Name=tag:Name,Values=moat-fleet" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].PrivateIpAddress' \
  --output text)

export HOST1_PUBLIC_IP=$(aws ec2 describe-instances \
  --region "$AWS_REGION" \
  --filters "Name=tag:Name,Values=moat-host1" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text)

export HOST1_PRIVATE_IP=$(aws ec2 describe-instances \
  --region "$AWS_REGION" \
  --filters "Name=tag:Name,Values=moat-host1" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].PrivateIpAddress' \
  --output text)

export HOST2_PUBLIC_IP=$(aws ec2 describe-instances \
  --region "$AWS_REGION" \
  --filters "Name=tag:Name,Values=moat-host2" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text)

export HOST2_PRIVATE_IP=$(aws ec2 describe-instances \
  --region "$AWS_REGION" \
  --filters "Name=tag:Name,Values=moat-host2" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].PrivateIpAddress' \
  --output text)
```

Print the values to verify them:

```bash
printf 'FLEET_PUBLIC_IP=%s\n' "$FLEET_PUBLIC_IP"
printf 'FLEET_PRIVATE_IP=%s\n' "$FLEET_PRIVATE_IP"
printf 'HOST1_PUBLIC_IP=%s\n' "$HOST1_PUBLIC_IP"
printf 'HOST1_PRIVATE_IP=%s\n' "$HOST1_PRIVATE_IP"
printf 'HOST2_PUBLIC_IP=%s\n' "$HOST2_PUBLIC_IP"
printf 'HOST2_PRIVATE_IP=%s\n' "$HOST2_PRIVATE_IP"
```

Open one SSH session to each machine:

```bash
ssh -i "${DEMO_NAME}.pem" ubuntu@"$FLEET_PUBLIC_IP"
ssh -i "${DEMO_NAME}.pem" ubuntu@"$HOST1_PUBLIC_IP"
ssh -i "${DEMO_NAME}.pem" ubuntu@"$HOST2_PUBLIC_IP"
```

Keep these exported values in your local shell. The demo runbook uses the private IPs later for the fleet configs.

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

### Attach a Data Volume to Each Host

Do this before building or running the demos. Snapshot-heavy Firecracker runs will fill the default root disk too quickly.

Set the instance IDs locally:

```bash
export HOST1_INSTANCE_ID="i-aaaaaaaaaaaaaaaaa"
export HOST2_INSTANCE_ID="i-bbbbbbbbbbbbbbbbb"
```

Create and attach one `30 GiB` gp3 volume per host:

```bash
export HOST1_AZ=$(aws ec2 describe-instances \
  --region "$AWS_REGION" \
  --instance-ids "$HOST1_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].Placement.AvailabilityZone' \
  --output text)

export HOST2_AZ=$(aws ec2 describe-instances \
  --region "$AWS_REGION" \
  --instance-ids "$HOST2_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].Placement.AvailabilityZone' \
  --output text)

export HOST1_DATA_VOL=$(aws ec2 create-volume \
  --region "$AWS_REGION" \
  --availability-zone "$HOST1_AZ" \
  --size 30 \
  --volume-type gp3 \
  --tag-specifications 'ResourceType=volume,Tags=[{Key=Name,Value=moat-host1-data}]' \
  --query 'VolumeId' \
  --output text)

export HOST2_DATA_VOL=$(aws ec2 create-volume \
  --region "$AWS_REGION" \
  --availability-zone "$HOST2_AZ" \
  --size 30 \
  --volume-type gp3 \
  --tag-specifications 'ResourceType=volume,Tags=[{Key=Name,Value=moat-host2-data}]' \
  --query 'VolumeId' \
  --output text)

aws ec2 wait volume-available \
  --region "$AWS_REGION" \
  --volume-ids "$HOST1_DATA_VOL" "$HOST2_DATA_VOL"

aws ec2 attach-volume \
  --region "$AWS_REGION" \
  --volume-id "$HOST1_DATA_VOL" \
  --instance-id "$HOST1_INSTANCE_ID" \
  --device /dev/sdf

aws ec2 attach-volume \
  --region "$AWS_REGION" \
  --volume-id "$HOST2_DATA_VOL" \
  --instance-id "$HOST2_INSTANCE_ID" \
  --device /dev/sdf
```

On Nitro instances such as `m8i.2xlarge`, the attached EBS volume will usually appear inside the guest as `/dev/nvme1n1`. Confirm with:

```bash
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT,SERIAL
```

On each `moat` host, format and mount the new volume at `/var/lib/moat`:

```bash
sudo mkfs.ext4 -F /dev/nvme1n1
UUID=$(sudo blkid -s UUID -o value /dev/nvme1n1)
echo "UUID=${UUID} /var/lib/moat ext4 defaults,nofail 0 2" | sudo tee -a /etc/fstab

sudo mkdir -p /var/lib/moat
sudo mount /dev/nvme1n1 /var/lib/moat
sudo mkdir -p /var/lib/moat/state /var/lib/moat/base
sudo chown -R root:root /var/lib/moat

df -h /var/lib/moat
```

If `nvme1n1` is not the new volume on your instance, use the device shown by `lsblk` instead of hard-coding that path.

If you already downloaded `vmlinux` and `rootfs.ext4` before mounting the volume, copy them to the volume-backed `/var/lib/moat` or redownload them there.

---

### Install `moatctl` on the Fleet VM

For Demo 3, the fleet VM needs `moatctl` so it can create sandboxes through the fleet controller from `moat-fleet` itself.

Use the `moatctl` binary already built on `moat-host1` and copy it to the fleet VM from your local machine:

```bash
scp -i "${DEMO_NAME}.pem" \
  ubuntu@"$HOST1_PUBLIC_IP":/usr/local/bin/moatctl \
  /tmp/moatctl

scp -i "${DEMO_NAME}.pem" \
  /tmp/moatctl \
  ubuntu@"$FLEET_PUBLIC_IP":/tmp/moatctl

ssh -i "${DEMO_NAME}.pem" ubuntu@"$FLEET_PUBLIC_IP" \
  'sudo install -m 0755 /tmp/moatctl /usr/local/bin/moatctl && moatctl --help | head'
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

This runbook uses Firecracker with `workspace_storage: "block"` in the host
configs below. With the stock kernel path used here, that is the working
configuration for the sandbox demos on the AWS hosts above.

Load the host-side vsock modules and verify KVM:

```bash
sudo modprobe vsock
sudo modprobe vhost_vsock
ls -l /dev/kvm
egrep -wo 'vmx|svm' /proc/cpuinfo | head
```

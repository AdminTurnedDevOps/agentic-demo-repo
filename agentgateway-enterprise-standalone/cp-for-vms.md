This guide will show how to install an agw ee standalone control plane on a VM or laptop/desktop

## One VM/laptop

### Install

On the VM, do the following

1. Set the appropriate env vars to set the license key and pull down the latest binary:

```
export ENTERPRISE_INSTALL_URL=
export AGENTGATEWAY_VERSION=
export ENTERPRISE_AGENTGATEWAY_LICENSE_KEY=
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
loaded config from File("/YOUR_PATH/.config/agentgateway/config.yaml")
```

### Configuration

1. Look in `~/.config/agentgateway`. You'll see that agentgateway, when you run it, creates a config file. You can use that for testing purposes to run agentgateway.

```
agentgateway -f ~/.config/agentgateway/config.yaml
```

## High Availability

Because this section is for HA, doing this on your laptop won't be production-ready

> This setup provides redundancy if an agentgateway instance fails. Existing connections may be interrupted, and clients may need to reconnect. For production, make PostgreSQL and the load balancer highly available too, and secure access to the management UI.

![](images/ha.png)

### Active/Active
The example here is used to test HA for agentgateway. Of course, based on your environment, it may look different (more VMs, different AZs, different setup of Postgres, etc.)
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
| API-key budgets | Usage is shared across VMs; enforcement updates periodically |
| License attestation | Same entitlement record on both starts |

Schema is created on first start. No extra migration.

#### 1. Postgres

Stand up Postgres somewhere both VMs can reach (RDS, Cloud SQL, or a third VM). Back it up; it is now the source of UI config and spend.


**Install and start PostgreSQL on the database VM:**

```bash
sudo apt update &&
sudo apt install -y postgresql-17 &&
sudo systemctl enable --now postgresql &&
sudo -u postgres pg_isready
```

The last command should report `accepting connections` on port 5432.

**Create the agentgateway database and user:**

Run each block below separately in the **normal Linux terminal on the PostgreSQL VM** (the prompt ending in `$`). The `psql --command` wrapper sends the SQL to PostgreSQL; do not paste bare SQL into Bash.

First, create the database user:

```bash
sudo -u postgres psql --command 'CREATE USER agw;'
```

If PostgreSQL reports that role `agw` already exists from an earlier attempt, do not recreate it. Continue with the existing role.

Next, set its password interactively. Enter a strong, unique password twice when prompted, and keep it in your secret manager. This avoids putting the password in SQL or shell history. If you already set the password, skip this block.

```bash
sudo -u postgres psql --command '\password agw'
```

After the password command finishes and the normal Linux prompt returns, create the database:

```bash
sudo -u postgres psql --command 'CREATE DATABASE agw OWNER agw;'
```

Expect `CREATE DATABASE`. If database `agw` already exists from an earlier attempt, do not delete it; verify its ownership instead.

Confirm the database exists and its owner is `agw`:

```bash
sudo -u postgres psql --command '\l agw'
```

The `agw` user owns the database so agentgateway can create and update its tables at startup. It does not need to be a PostgreSQL superuser.

**Allow connections from the two agentgateway VMs:**

On the database VM, open the PostgreSQL configuration (remember to put the actual IPs of your VM):

```bash
sudo vim /etc/postgresql/17/main/postgresql.conf
```

Find the `listen_addresses` setting, uncomment it, and set it to localhost plus the database VM's private address:

```conf
listen_addresses = 'localhost,x.x.x.x'
```

Next, open the client authentication configuration:

```bash
sudo vim /etc/postgresql/17/main/pg_hba.conf
```

Keep the existing local rules and add these two lines. Each `/32` allows just one IPv4 address, and `hostssl` requires an encrypted connection:

```conf
hostssl agw agw x.x.x.x/32 scram-sha-256
hostssl agw agw x.x.x.x/32 scram-sha-256
```

^ Those two IPs are the private IP addresses of the VMs running agentgateway, not the PostgreSQL VM.

Debian's standard installation enables PostgreSQL TLS using the system's self-signed test certificate when available. Confirm it is enabled before continuing:

```bash
sudo -u postgres psql --command 'SHOW ssl;'
```

The result should be `on`.

**If it is `off`, configure a server certificate and enable `ssl` in `postgresql.conf` before using the `hostssl` rules. The test certificate is sufficient for the private-network demo; for production, use a trusted certificate and clients configured to verify the server's identity.**

In your cloud security group and any host firewall, allow inbound TCP **5432 only from the two agentgateway VMs' private IPs**, denying other sources. Do not expose PostgreSQL to the public internet.

Restart PostgreSQL to apply the settings, then check it again:

```bash
sudo systemctl restart postgresql
sudo -u postgres pg_isready
```

**Test access from both agentgateway VMs:**

On each gateway VM, install the postgres client and run a query. Replace the host address, and enter the `agw` password when prompted:

```bash
sudo apt update
sudo apt install -y postgresql-client-17
psql "host=the.postgres.ip.address port=5432 dbname=agw user=agw sslmode=require connect_timeout=5" \
  --password --command 'SELECT current_database(), current_user;'
```

Both VMs should return database `agw` and user `agw` before you continue. If not, check the private IPs, firewall rules, and `pg_hba.conf` entries.

In the config below, use this database VM's private address (or private DNS name) and the password you created. Percent-encode special characters in the password for use in the URL. Keep the populated config out of Git and restrict its file permissions to the account running agentgateway.

Reference: [Debian's PostgreSQL cluster configuration documentation](https://manpages.debian.org/trixie/postgresql-common/pg_createcluster.1.en.html).

#### 2. Install agentgateway on both gateway VMs

Run these steps on **each agentgateway VM**, using the Linux account that will run agentgateway. Do not install agentgateway on the PostgreSQL VM. If you already installed the pinned version using the earlier single-VM instructions, skip the installation and verify the version below.

Install the download prerequisites:

```bash
sudo apt update &&
sudo apt install -y curl ca-certificates
```

Install the same enterprise binary version on both VMs:

```bash
export ENTERPRISE_INSTALL_URL=
export AGENTGATEWAY_VERSION=
curl -fsSL "$ENTERPRISE_INSTALL_URL" | sh
```

Add the binary to your current shell's PATH and verify it is available:

```bash
export PATH="$HOME/.agentgateway/bin:$PATH"
agentgateway --version
```

Confirm both VMs report the same expected version. Do not start the gateway yet; first create the shared baseline configuration below.

#### 3. Same baseline config on both VMs

**Generate the shared session key:**

Run this **once on either gateway VM**, before editing the configuration:

```bash
openssl rand -hex 32
```

This prints a random 64-character hexadecimal AES-256 key. Put that value in `config.session.key` in the YAML below, using the **exact same value on both VMs**. Do not generate a different key for each VM. Keep it secret and out of Git. If you already generated a shared key, reuse it.

**Create the baseline configuration:**

Use `~/.config/agentgateway/config.yaml` on **each gateway VM**. Create the directory and open the file as the same Linux account used for installation:

```bash
umask 077
mkdir -p ~/.config/agentgateway
vim ~/.config/agentgateway/config.yaml
```

If the file already exists, inspect it before changing it. Use the same baseline below on both VMs, filling in the database connection details and shared session key. Hybrid mode needs the empty `llm` / `mcp` sections in the **file** — the UI cannot add those sections, it only overlays resources into ones that already exist.

```
# yaml-language-server: $schema=https://agentgateway.dev/schema/config
config:
  storage:
    mode: hybrid
  database:
    url: "postgres://agw:<url-encoded-password>@<postgres-private-host>:5432/agw?sslmode=require"
  session:
    key: "<64-hex-char AES-256 key>"
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

Matching session keys allow the other VM to decode session state for compatible Streamable HTTP MCP requests. If you previously set `SESSION_KEY` in the environment, it overrides `config.session.key`; make sure it matches the shared key or unset it to use the YAML value.

After editing, restrict access to the file because it contains credentials:

```bash
chmod 600 ~/.config/agentgateway/config.yaml
```

**Set the enterprise license and start each gateway:**

This guide uses the `ENTERPRISE_AGENTGATEWAY_LICENSE_KEY` environment variable, so **no license key file is needed**. Use a valid enterprise license supplied by Solo, not a randomly generated session key. Use the same license on both gateway VMs. If your config still contains the earlier `config.license.key.file` entry, remove that entry to match the YAML above.

In Bash on **each gateway VM**, run this block and paste your license at the prompt. The input is hidden and does not become part of your shell history:

```bash
read -r -s -p "Enterprise license key: " ENTERPRISE_AGENTGATEWAY_LICENSE_KEY
```

After entering the license and pressing Enter, export it and start agentgateway from the same terminal:

```bash
export ENTERPRISE_AGENTGATEWAY_LICENSE_KEY
export PATH="$HOME/.agentgateway/bin:$PATH"
agentgateway -f ~/.config/agentgateway/config.yaml
```

The environment variable is set only for this shell and its child processes. Set it again if you start agentgateway from a new terminal.

#### 4. Load balancer

Use a **GCP global external Application Load Balancer** in front of the two existing gateway VMs. Google manages the load balancer; **no fourth VM or HAProxy installation is needed**. Clients connect to a **public IPv4 address on HTTP port `80`**, and the ALB forwards requests to agentgateway on port `4000`. Health checks use HTTP on port `15021` at `/healthz/ready`.

Run the setup commands in **Bash in GCP Cloud Shell**, or an authenticated local shell with `gcloud` installed. Both gateway VMs must be in the **same project, VPC, and region**. They can be in different zones, which is preferable for protection against a zone failure. Keep both gateways running. You need permission to create instance groups, load-balancer resources, and firewall rules, and to edit VM network tags.

The public frontend is reachable from anywhere without a VPN or client IP allowlist. This testing configuration uses HTTP, not HTTPS, and exposes all routes attached to the gateway, including the management UI and configuration APIs. It does not add authentication.

**Set your project and VM details:**

Run each block separately, in order, and keep the same shell open so the variables remain available. These commands create dedicated demo resources. If a command fails or a resource name already exists, stop and inspect the error rather than continuing or deleting existing resources.

Replace the placeholder with your project ID, export it, then list your existing VMs:

```bash
export PROJECT_ID="<gcp-project-id>"
```

```bash
gcloud compute instances list --project="$PROJECT_ID" \
  --format='table(name,zone.basename(),networkInterfaces[0].network.basename(),networkInterfaces[0].subnetwork.basename(),networkInterfaces[0].networkIP)'
```

Use that output to replace every placeholder in the export block below before running it. Set the two **gateway VM names**, not the PostgreSQL VM. Zones are values such as `us-central1-a`; the corresponding region is `us-central1`. `REGION` is needed only if removing the earlier private load balancer. The public frontend is global and does not need `SUBNET` or `CLIENT_CIDR` variables.

```bash
export VM_1="<first-gateway-vm-name>"
export ZONE_1="<first-gateway-zone>"
export VM_2="<second-gateway-vm-name>"
export ZONE_2="<second-gateway-zone>"
export REGION="<shared-region>"
export NETWORK="<vpc-network-name>"
```

**If you already created the earlier private load balancer:**

Skip this block for a fresh setup. Otherwise, remove the old private load-balancer resources before attaching the existing groups to the public ALB. The private backend's connection-based balancing mode cannot share these groups with the public ALB's utilization-based mode. These commands keep the gateway VMs, instance groups, network tags, VPC, and subnet in place. Run only for the dedicated resources created by the earlier version of this guide; if setup was partial, remove only the resources that exist.

```bash
gcloud compute forwarding-rules delete agw-frontend \
  --project="$PROJECT_ID" --region="$REGION" &&
gcloud compute backend-services delete agw-internal-lb \
  --project="$PROJECT_ID" --region="$REGION" &&
gcloud compute health-checks delete agw-readiness \
  --project="$PROJECT_ID" --region="$REGION" &&
gcloud compute addresses delete agw-lb-ip \
  --project="$PROJECT_ID" --region="$REGION" &&
gcloud compute firewall-rules delete agw-allow-health-checks agw-allow-demo-clients \
  --project="$PROJECT_ID"
```

**Group the existing gateway VMs:**

Create one unmanaged instance group per gateway, using each VM's own zone. This does not create or replace VMs. Two groups are needed because these gateway VMs are in different zones. If you already created these two groups for the private load balancer, keep them and skip this creation block; continue with the named-port commands below.

```bash
gcloud compute instance-groups unmanaged create agw-gateway-1 \
  --project="$PROJECT_ID" --zone="$ZONE_1" &&
gcloud compute instance-groups unmanaged add-instances agw-gateway-1 \
  --project="$PROJECT_ID" --zone="$ZONE_1" --instances="$VM_1" &&
gcloud compute instance-groups unmanaged create agw-gateway-2 \
  --project="$PROJECT_ID" --zone="$ZONE_2" &&
gcloud compute instance-groups unmanaged add-instances agw-gateway-2 \
  --project="$PROJECT_ID" --zone="$ZONE_2" --instances="$VM_2"
```

Set the named port that tells the ALB where agentgateway listens. Run this for both new groups and groups reused from the private setup. These commands replace the named-port mapping on these dedicated demo groups:

```bash
gcloud compute instance-groups unmanaged set-named-ports agw-gateway-1 \
  --project="$PROJECT_ID" --zone="$ZONE_1" --named-ports=http:4000 &&
gcloud compute instance-groups unmanaged set-named-ports agw-gateway-2 \
  --project="$PROJECT_ID" --zone="$ZONE_2" --named-ports=http:4000
```

**Allow GCP proxies and health checks to reach the gateways:**

Add the dedicated tag `agw-lb-backend` to both gateways, preserving existing tags. This tag should not be used by other VMs or firewall rules outside this demo.

```bash
gcloud compute instances add-tags "$VM_1" \
  --project="$PROJECT_ID" --zone="$ZONE_1" --tags=agw-lb-backend &&
gcloud compute instances add-tags "$VM_2" \
  --project="$PROJECT_ID" --zone="$ZONE_2" --tags=agw-lb-backend
```

Create ingress allow rules for GCP's health-check probes on `15021` and ALB proxy traffic on `4000`:

```bash
gcloud compute firewall-rules create agw-public-allow-health-checks \
  --project="$PROJECT_ID" --network="$NETWORK" \
  --direction=INGRESS --action=ALLOW --target-tags=agw-lb-backend \
  --source-ranges=35.191.0.0/16 --rules=tcp:15021 &&
gcloud compute firewall-rules create agw-public-allow-proxies \
  --project="$PROJECT_ID" --network="$NETWORK" \
  --direction=INGRESS --action=ALLOW --target-tags=agw-lb-backend \
  --source-ranges=35.191.0.0/16,130.211.0.0/22 --rules=tcp:4000
```

^ The above are Google IPs

35.191.0.0/16 → TCP 15021	Allows Google’s health-check systems to call /healthz/ready on your gateways.
35.191.0.0/16,130.211.0.0/22 → TCP 4000	Allows Google’s load-balancer proxies to forward application requests to your gateways.

These rules restrict the **proxy-to-VM connection**, not who can access the public frontend. Internet clients connect to the ALB on port `80`; the ALB connects to the gateway VMs from Google's proxy ranges. No `0.0.0.0/0` ingress rule on the gateway VMs is needed for unrestricted access through the ALB. Apply equivalent rules in any host firewall. Keep existing administrative and PostgreSQL access rules; these commands do not change the default VPC or subnet.

**Create the health check and backend service:**

The global HTTP health check expects `200` from `/healthz/ready` on port `15021`. The HTTP backend service sends application traffic to named port `http` (`4000`), with both gateways active rather than one configured as a standby. The response timeout is set to one hour for long-running LLM/MCP responses; it is not a guarantee of indefinite stream continuity.

```bash
gcloud compute health-checks create http agw-public-readiness \
  --project="$PROJECT_ID" --global \
  --port=15021 --request-path=/healthz/ready \
  --check-interval=5s --timeout=5s \
  --healthy-threshold=2 --unhealthy-threshold=2 &&
gcloud compute backend-services create agw-public-backend \
  --project="$PROJECT_ID" --global \
  --load-balancing-scheme=EXTERNAL_MANAGED --protocol=HTTP --port-name=http \
  --health-checks=agw-public-readiness --global-health-checks \
  --session-affinity=NONE --timeout=3600s &&
gcloud compute backend-services add-backend agw-public-backend \
  --project="$PROJECT_ID" --global \
  --instance-group=agw-gateway-1 --instance-group-zone="$ZONE_1" \
  --balancing-mode=UTILIZATION --max-utilization=0.8 &&
gcloud compute backend-services add-backend agw-public-backend \
  --project="$PROJECT_ID" --global \
  --instance-group=agw-gateway-2 --instance-group-zone="$ZONE_2" \
  --balancing-mode=UTILIZATION --max-utilization=0.8
```

**Create the public HTTP frontend:**

Reserve a global public IPv4 address, create a URL map that sends all paths to the gateway backend, then create the HTTP proxy and forwarding rule. This uses port `80` and requires no domain name or TLS certificate.

```bash
gcloud compute addresses create agw-public-ip \
  --project="$PROJECT_ID" --global --ip-version=IPV4 --network-tier=PREMIUM &&
gcloud compute url-maps create agw-public-url-map \
  --project="$PROJECT_ID" --global --default-service=agw-public-backend &&
gcloud compute target-http-proxies create agw-public-http-proxy \
  --project="$PROJECT_ID" --global \
  --url-map=agw-public-url-map --global-url-map &&
gcloud compute forwarding-rules create agw-public-frontend \
  --project="$PROJECT_ID" --global \
  --load-balancing-scheme=EXTERNAL_MANAGED --network-tier=PREMIUM \
  --address=agw-public-ip --global-address \
  --target-http-proxy=agw-public-http-proxy --global-target-http-proxy \
  --ip-protocol=TCP --ports=80
```

Check backend health. Repeat this command until **both VMs show `healthState: HEALTHY`** before testing traffic:

```bash
gcloud compute backend-services get-health agw-public-backend \
  --project="$PROJECT_ID" --global
```

Store the public frontend IP in an environment variable and print it:

```bash
LB_PUBLIC_IP="$(gcloud compute addresses describe agw-public-ip \
  --project="$PROJECT_ID" --global --format='value(address)')" &&
export LB_PUBLIC_IP
printf '%s\n' "$LB_PUBLIC_IP"
```

The public URL uses port `80`, not `4000`. The VMs still listen on `4000` for application traffic and `15021` for readiness. Keep the listeners reachable on the VM network interfaces as in the baseline; no load-balancer VIP route or proxy-only subnet is needed for this global ALB.

If a backend stays unhealthy, check that agentgateway is running and run `curl --fail http://localhost:15021/healthz/ready` on that gateway VM. Then check its network tag and the health-check firewall rule. A healthy readiness check does not prove database synchronization is healthy.

**Connect through the load balancer:**

Run this from Cloud Shell, your laptop, or any internet-connected client with curl. If using a different terminal, first set `export LB_PUBLIC_IP="<public-ip-printed-above>"` there.

```bash
curl --fail --show-error --max-time 30 -i "http://${LB_PUBLIC_IP}/ui/"
```

You should receive the UI page or a redirect. Open `http://<PUBLIC_IP>/ui/` in your browser using the printed IP. No VPN, SSH tunnel, or client allowlist is required. Initial frontend propagation can take a few minutes; if the request fails, recheck backend health and retry.

For a controlled demo failover test, stop the foreground agentgateway process on **one gateway VM only** with Ctrl+C. Use the `get-health` command above until GCP reports that backend as unhealthy, then repeat the curl command. New requests through the unchanged public IP should reach the remaining healthy gateway. Restart the stopped gateway using step 3 and confirm both backends become healthy again. Requests during detection and existing streams may fail; clients must reconnect.

GCP manages load-balancer availability, but the single PostgreSQL VM is still a shared failure point. Unmanaged instance groups also do not automatically restart or replace failed gateway processes or VMs.

## Cleanup

**Remove the load-balancer resources:**

```bash
gcloud compute forwarding-rules delete agw-public-frontend \
  --project="$PROJECT_ID" --global &&
gcloud compute target-http-proxies delete agw-public-http-proxy \
  --project="$PROJECT_ID" --global &&
gcloud compute url-maps delete agw-public-url-map \
  --project="$PROJECT_ID" --global &&
gcloud compute backend-services delete agw-public-backend \
  --project="$PROJECT_ID" --global &&
gcloud compute health-checks delete agw-public-readiness \
  --project="$PROJECT_ID" --global &&
gcloud compute addresses delete agw-public-ip \
  --project="$PROJECT_ID" --global &&
gcloud compute instance-groups unmanaged delete agw-gateway-1 \
  --project="$PROJECT_ID" --zone="$ZONE_1" &&
gcloud compute instance-groups unmanaged delete agw-gateway-2 \
  --project="$PROJECT_ID" --zone="$ZONE_2" &&
gcloud compute firewall-rules delete agw-public-allow-health-checks agw-public-allow-proxies \
  --project="$PROJECT_ID" &&
gcloud compute instances remove-tags "$VM_1" \
  --project="$PROJECT_ID" --zone="$ZONE_1" --tags=agw-lb-backend &&
gcloud compute instances remove-tags "$VM_2" \
  --project="$PROJECT_ID" --zone="$ZONE_2" --tags=agw-lb-backend
```

**Delete the three demo VMs:**

```bash
gcloud compute instances delete YOUR_AGW_VM1 \
  --project="$PROJECT_ID" --zone=northamerica-northeast1-a &&
gcloud compute instances delete YOUR_AGW_VM2 \
  --project="$PROJECT_ID" --zone=northamerica-northeast1-c &&
gcloud compute instances delete YOUR_POSTGRES_VM \
  --project="$PROJECT_ID" --zone=northamerica-northeast1-c
```

The list should be empty. There are intentionally no VPC or subnet deletion commands in this cleanup.

#### 5. Check that it is actually shared

Edit something in the UI through the LB (add an MCP server or a model). On the **other** VM, check that the shared configuration is visible:

```
curl -s http://localhost:15000/api/config/effective
```

You should see the change without restarting that process. This confirms shared configuration visibility, not that the running gateway has applied it. To verify that too, send a request directly to the other VM's gateway on port 4000 (bypassing the LB) using the model you added, or call a tool on the MCP server you added.


### Hot/Cold Scenario

Typical shapes:

- Cloud VM: second instance stopped or scaled to zero; LB/ASG/MIG health check fails on the hot one; the provider boots the spare and points the VIP at it.
- Always-on spare: cold process is running but the LB has only one backend (or keepalived/VRRP holds the VIP). Failover is “add the second backend / move the VIP,” not a wake-up.
- Same host: systemd/watchdog restarts the binary. That’s HA of the process, not of the VM.

What you still want with the cold side so its not a blank slate:

- Shared Postgres (config overlay, logs, budgets, license attestation)
- Same baseline config.yaml and session key
- Same license

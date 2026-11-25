---
title: "Agent Substrate: Spread Load Across Clusters and Survive a Cluster Outage"
date: 2026-11-21
description: >
  A two-cluster Agent Substrate lab. Place a new actor in cluster B when
  cluster A is full, then recover one session in B from shared Cloud SQL
  for PostgreSQL state while fencing the old writer in A.
tags: [agent-substrate, kubernetes, multi-cluster, disaster-recovery, failover, actors, egress, fencing]
author: Michael Levan
---

# Two Clusters, One Fleet

Each Agent Substrate install schedules and routes actors within its own cluster.
To use two clusters, your application chooses where each new actor lives. If
that cluster becomes unreachable, your application can start a replacement
elsewhere using shared application state. Substrate does not move the original
actor or its snapshot across installs.

This lab has two parts: **place a new actor when cluster A is full**, then
**fail over one session while its original actor is still running**.

## Prerequisites

- Two independent Agent Substrate **v1.0.0** installs. See the [GKE setup lab](../install-and-setup/setup-gke.md) if you need them.
- Deploy the stock sandbox demo to each cluster from the `v1.0.0` checkout.
  Set the target context and a `KO_DOCKER_REPO` that the cluster can pull from,
  then run `go run ./cmd/ate-setup deploy demo sandbox` for each cluster.
- Each install needs the stock `atenet-egress` gateway and the ingress allowlist
  entry `spiffe://cluster.local/ns/ate-system/sa/atenet-client` for `kubectl ate proxy`.
- Use disposable lab resources. The `session-store` namespace must be unused
  in both clusters; cleanup deletes it.
- For Part 2, use GKE with Workload Identity Federation on both clusters. The
  steps below assume both clusters and Cloud SQL are in the same Google Cloud
  project.
  You'll need `gcloud`, `psql`, and the [Cloud SQL Auth Proxy](https://cloud.google.com/sql/docs/postgres/sql-proxy)
  (`cloud-sql-proxy` v2) on your workstation, and permissions to create a
  service account and grant it Cloud SQL access. On macOS,
  `brew install cloud-sql-proxy libpq` provides both; Homebrew doesn't link
  `libpq`, so add `$(brew --prefix libpq)/bin` to your `PATH` for `psql`.
- Bash, `kubectl` matched to your clusters, `kubectl-ate` v1.0.0, `jq`, `curl`,
  and `nc`. Run the lab in one terminal and keep local ports 8001, 8002, and
  15432 free.

Set the context names and make a working directory:

```bash
export CTX_A="cluster-a-context"
export CTX_B="cluster-b-context"
export ATESPACE=ate-demo-sandbox
export TEMPLATE=sandbox-template

LAB_DIR=$(mktemp -d "${TMPDIR:-/tmp}/substrate-dr-lab.XXXXXX")

for ctx in "$CTX_A" "$CTX_B"; do
  echo "== $ctx"
  kubectl ate --context "$ctx" get actor-templates -a "$ATESPACE"
  kubectl ate --context "$ctx" get workers -n "$ATESPACE"
done
```

In each cluster, wait for `sandbox-template` to show a `GOLDEN TAG` and for
two workers to be `WORKER_STATE_ACTIVE` with no assigned actors. The templates
have the same name but separate UIDs and golden snapshots. Each stock worker
has 2000 millicores of capacity, and each sandbox actor asks for 2000, so each
cluster holds two running actors.

## Part 1: Place a new actor when cluster A is full

Story: Cluster A is healthy, but full, so you place the new Actor in Cluster B. It demonstrates choosing another cluster with capacity, not automatic health detection or outage routing.

This uses the stock sandbox demo on Substrate. The below fills both Workers CPU capacity, not their Actor slots.
Each worker advertises 2,000 millicores, and each sandbox-template actor (via the demo) reserves 2,000 millicores.

Fill both workers in cluster A:

```bash
for actor in load-1 load-2; do
  kubectl ate --context "$CTX_A" create actor "$actor" -a "$ATESPACE" --template "$TEMPLATE" &&
    kubectl ate --context "$CTX_A" resume actor "$actor" -a "$ATESPACE" || break
done
kubectl ate --context "$CTX_A" get workers -n "$ATESPACE"
```

Once both workers show one actor assigned, try a third:

```bash
kubectl ate --context "$CTX_A" create actor load-3 -a "$ATESPACE" --template "$TEMPLATE" &&
  kubectl ate --context "$CTX_A" resume actor load-3 -a "$ATESPACE"
```

Create succeeds because it only creates a `SUSPENDED` record. Resume is the
first capacity check. It should fail with `ResourceExhausted` and
`no worker has room for the actor`. In v1.0.0, that error generally means no
eligible worker has room; it doesn't tell you whether waiting will help. Here
we know both workers are full because we just filled them.

**Only after seeing the expected capacity error**, delete the unused record in
A and try B. The command chain stops if deletion fails:

```bash
kubectl ate --context "$CTX_A" delete actor load-3 -a "$ATESPACE" &&
  kubectl ate --context "$CTX_B" create actor load-3 -a "$ATESPACE" --template "$TEMPLATE" &&
  kubectl ate --context "$CTX_B" resume actor load-3 -a "$ATESPACE"
```

`load-3` is running in B. Your application made the placement decision; the
two installs didn't coordinate. A production placer can use `ListWorkers`
to estimate capacity, but the list doesn't reserve anything. For an existing
actor, a router `503` isn't a signal to retry in another cluster: the other
install doesn't have that actor.

Clean up the placement actors before moving on:

```bash
kubectl ate --context "$CTX_A" delete actor load-1 -a "$ATESPACE" &&
  kubectl ate --context "$CTX_A" delete actor load-2 -a "$ATESPACE" &&
  kubectl ate --context "$CTX_B" delete actor load-3 -a "$ATESPACE"
```

## Part 2 - Recover one session after losing ingress to cluster A

Story: Routing to Cluster B alone doesn’t recover anything. You create a replacement, fence the old writer before cutover, and show that cluster B continues the externally stored count while its local file starts fresh.

Simulate an outage from the front door's point of view: it loses contact with
A, but the original actor keeps running and can still write. To recover safely,
keep the session count outside the actor and make the store reject the old
writer before sending traffic to B.

### 1. Set up Cloud SQL for PostgreSQL

Create a small [Cloud SQL for PostgreSQL instance](https://cloud.google.com/sql/docs/postgres/create-instance)
for the session state. It is separate from Substrate's control-plane database,
and has a public IP with **no authorized networks**: both connections to it go
through the Cloud SQL Auth Proxy, which uses IAM and encrypts the connection.

Replace the project name, and enable the Cloud SQL Admin API:

```bash
export GCP_PROJECT="your-project-id"
export SQL_INSTANCE=substrate-dr-lab
export SQL_DATABASE=substrate_dr_lab

gcloud services enable sqladmin.googleapis.com --project "$GCP_PROJECT"
```

Create the instance, with a generated password for its built-in `postgres`
user. The password stays in `SQL_ADMIN_PASSWORD` for the rest of the lab.
Change `--region` if cluster B isn't in `us-central1`. This takes several
minutes.

```bash
SQL_ADMIN_PASSWORD=$(openssl rand -hex 24)

gcloud sql instances create "$SQL_INSTANCE" --project "$GCP_PROJECT" \
  --database-version=POSTGRES_17 --edition=enterprise --tier=db-f1-micro \
  --region=us-central1 --storage-size=10 --storage-type=SSD \
  --assign-ip --no-deletion-protection --root-password="$SQL_ADMIN_PASSWORD"
```

Create the lab database:

```bash
SQL_CONNECTION_NAME=$(gcloud sql instances describe "$SQL_INSTANCE" \
  --project "$GCP_PROJECT" --format='value(connectionName)')
gcloud sql databases create "$SQL_DATABASE" --instance "$SQL_INSTANCE" --project "$GCP_PROJECT"
```

Start a local proxy so you can administer the database with `psql`. The proxy
uses your Application Default Credentials, which need `roles/cloudsql.client`.
If you haven't set them up, run `gcloud auth application-default login` on its
own first; it opens a browser. Wait for the proxy to say it's ready before
running `psql`.

```bash
cloud-sql-proxy --address 127.0.0.1 --port 15432 "$SQL_CONNECTION_NAME" &
SQL_PROXY_PID=$!
```

Define `lab_sql`, a helper that runs `psql` against the lab database as the
`postgres` user. Every later database step uses it.

```bash
lab_sql() {
  PGPASSWORD="$SQL_ADMIN_PASSWORD" PGCONNECT_TIMEOUT=5 psql -X -v ON_ERROR_STOP=1 \
    -h 127.0.0.1 -p 15432 -U postgres -d "$SQL_DATABASE" "$@"
}
```

Now create the session state. This block sets up three things:

- **A private table** that holds the session's count and its epoch.
- **A `turn` function**, the only thing the HTTP API can call. One `UPDATE`
  checks the epoch and increments the count, so a turn and a fence can't race
  past one another.
- **Two roles for PostgREST:** `session_lab_login` to connect, and
  `session_lab_http` to call `turn`. Neither can change the epoch.

It also gives `session_lab_login` a generated password, kept in
`SQL_LOGIN_PASSWORD` for the next section.

```bash
SQL_LOGIN_PASSWORD=$(openssl rand -hex 24)

lab_sql -v login_password="$SQL_LOGIN_PASSWORD" <<'SQL'
BEGIN;
CREATE ROLE session_lab_http NOLOGIN;
CREATE ROLE session_lab_login LOGIN NOINHERIT;
GRANT session_lab_http TO session_lab_login;

CREATE SCHEMA session_state;
CREATE SCHEMA session_api;
CREATE TABLE session_state.sessions (
  id text PRIMARY KEY,
  epoch integer NOT NULL DEFAULT 1,
  value integer NOT NULL DEFAULT 0,
  a_writes integer NOT NULL DEFAULT 0,
  b_writes integer NOT NULL DEFAULT 0
);
INSERT INTO session_state.sessions (id) VALUES ('session-1');

CREATE FUNCTION session_api.turn(writer text, writer_epoch integer)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE result jsonb;
BEGIN
  IF writer IS NULL OR writer NOT IN ('cluster-a', 'cluster-b') THEN
    RAISE SQLSTATE 'PT400' USING MESSAGE = 'invalid writer';
  END IF;

  UPDATE session_state.sessions AS s
     SET value = s.value + 1,
         a_writes = s.a_writes + CASE WHEN writer = 'cluster-a' THEN 1 ELSE 0 END,
         b_writes = s.b_writes + CASE WHEN writer = 'cluster-b' THEN 1 ELSE 0 END
   WHERE s.id = 'session-1' AND s.epoch = writer_epoch
   RETURNING jsonb_build_object('value', s.value, 'epoch', s.epoch) INTO result;

  IF NOT FOUND THEN
    RAISE SQLSTATE 'PT409' USING MESSAGE = 'stale epoch';
  END IF;
  RETURN result;
END;
$$;

REVOKE ALL ON FUNCTION session_api.turn(text, integer) FROM PUBLIC;
GRANT USAGE ON SCHEMA session_api TO session_lab_http;
GRANT EXECUTE ON FUNCTION session_api.turn(text, integer) TO session_lab_http;
ALTER ROLE session_lab_login PASSWORD :'login_password';
COMMIT;
SQL
```

### 2. Give the actors an HTTP endpoint in each cluster

Deploy [PostgREST](https://docs.postgrest.org/) in **both** clusters. Each copy
reaches the same Cloud SQL instance through its own Cloud SQL Auth Proxy
sidecar, and each cluster's actors use the copy in their own cluster. Neither
cluster depends on the other to reach the session state.

PostgREST exposes the SQL function as `POST /rpc/turn` and translates `PT409`
into HTTP `409`. Actors use the stock HTTP egress path and never get PostgreSQL
credentials. The fence is an operator's SQL command, not an HTTP endpoint.
PostgREST has no local application state, so restarting a pod doesn't reset the
session.

> The endpoint has no caller authentication and the epoch is supplied by the
> writer. A NetworkPolicy admits only the cluster's own `ate-system` namespace,
> where the egress gateway runs. Use test data only, and don't use this API
> as-is in production. Cloud SQL is the one dependency both clusters share; this
> lab uses a single zonal instance and doesn't demonstrate losing it.

Give the proxies a dedicated Google service account. Use a name that's unused
in your project. The binding lets the Kubernetes service account
`session-store/session-store` use that identity without a key file. Both
clusters are in this project, so they share one Workload Identity pool and one
binding covers both.

```bash
SQL_GSA_NAME=substrate-dr-lab-sql
SQL_GSA_EMAIL="$SQL_GSA_NAME@$GCP_PROJECT.iam.gserviceaccount.com"

gcloud iam service-accounts create "$SQL_GSA_NAME" --project "$GCP_PROJECT"
gcloud projects add-iam-policy-binding "$GCP_PROJECT" \
  --member="serviceAccount:$SQL_GSA_EMAIL" --role=roles/cloudsql.client
gcloud iam service-accounts add-iam-policy-binding "$SQL_GSA_EMAIL" --project "$GCP_PROJECT" \
  --member="serviceAccount:$GCP_PROJECT.svc.id.goog[session-store/session-store]" \
  --role=roles/iam.workloadIdentityUser
```

In each cluster, create the namespace and a Secret holding PostgREST's
connection string, with the password generated in section 1:

```bash
for ctx in "$CTX_A" "$CTX_B"; do
  kubectl --context "$ctx" create namespace session-store
  printf '%s' "postgresql://session_lab_login:${SQL_LOGIN_PASSWORD}@127.0.0.1:5432/${SQL_DATABASE}?sslmode=disable" |
    kubectl --context "$ctx" -n session-store create secret generic session-store-db --from-file=db-uri=/dev/stdin
done
```

Apply the same manifest to both clusters. It creates the ServiceAccount, the
Deployment (PostgREST plus the proxy sidecar), a Service that gives the store
its DNS name inside the cluster, and the NetworkPolicies.

```bash
for ctx in "$CTX_A" "$CTX_B"; do
kubectl --context "$ctx" apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: session-store
  namespace: session-store
  annotations:
    iam.gke.io/gcp-service-account: "${SQL_GSA_EMAIL}"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: session-store
  namespace: session-store
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: session-store
  template:
    metadata:
      labels:
        app: session-store
    spec:
      serviceAccountName: session-store
      nodeSelector:
        iam.gke.io/gke-metadata-server-enabled: "true"
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      initContainers:
      - name: cloud-sql-proxy
        restartPolicy: Always
        image: gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.21.1@sha256:f6abce8d90076c0857f23fb2cffb744024f380eca25334e9f2b52d2d74dc9967
        args: ["--address=127.0.0.1", "--port=5432", "--structured-logs", "${SQL_CONNECTION_NAME}"]
        securityContext:
          allowPrivilegeEscalation: false
          runAsUser: 65532
          capabilities:
            drop: ["ALL"]
      containers:
      - name: postgrest
        image: postgrest/postgrest:v14.8@sha256:4173b72e0be29cf15349dc827798c3e464c5f2cc7f9c1697022f9cd1874b4c36
        env:
        - name: PGRST_DB_URI
          valueFrom:
            secretKeyRef:
              name: session-store-db
              key: db-uri
        - name: PGRST_DB_SCHEMAS
          value: session_api
        - name: PGRST_DB_ANON_ROLE
          value: session_lab_http
        - name: PGRST_SERVER_PORT
          value: "8080"
        - name: PGRST_ADMIN_SERVER_PORT
          value: "3001"
        - name: PGRST_LOG_LEVEL
          value: info
        ports:
        - name: data
          containerPort: 8080
        - name: readiness
          containerPort: 3001
        readinessProbe:
          httpGet:
            path: /ready
            port: readiness
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 250m
            memory: 128Mi
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          runAsUser: 1000
          capabilities:
            drop: ["ALL"]
---
apiVersion: v1
kind: Service
metadata:
  name: session-store
  namespace: session-store
spec:
  selector:
    app: session-store
  ports:
  - name: http
    port: 80
    targetPort: data
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: session-store
spec:
  podSelector: {}
  policyTypes:
  - Ingress
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-gateway
  namespace: session-store
spec:
  podSelector:
    matchLabels:
      app: session-store
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ate-system
    ports:
    - protocol: TCP
      port: 8080
EOF
done

for ctx in "$CTX_A" "$CTX_B"; do
  kubectl --context "$ctx" -n session-store rollout status deployment/session-store --timeout=120s
done

export STORE_HOST=session-store.session-store.svc.cluster.local
```

`STORE_HOST` resolves in both clusters, each to its own copy. That lets one
egress policy file and one `turn` command work for the actor in A and for its
replacement in B.

### 3. Start one session in cluster A

The sandbox demo runs commands sent to `/process`. `actor_sh` sends a command
through an actor's local tunnel, and `turn` updates Cloud SQL via PostgREST
before recording the turn in the actor's local file. Use `store` to inspect
the database directly through your workstation's proxy.

```bash
wait_port() {
  local deadline=$((SECONDS + 30))
  until nc -z 127.0.0.1 "$1" 2>/dev/null; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "Timed out waiting for local port $1" >&2
      return 1
    fi
    sleep 1
  done
}

store() {
  lab_sql -c "SELECT epoch, value, a_writes, b_writes FROM session_state.sessions WHERE id = 'session-1'"
}

actor_sh() {
  local reply
  reply=$(curl -fsS --max-time 15 -H 'Content-Type: application/json' \
    -d "$(jq -n --arg c "$2" '{command: ["sh", "-c", $c]}')" \
    "http://127.0.0.1:$1/process") || return 1
  jq -r '.stdout, .stderr | select(length > 0)' <<< "$reply"
  jq -e '.exitCode == 0' <<< "$reply" >/dev/null
}

# turn_command <writer> <epoch>: print the command to run inside the sandbox.
turn_command() {
  local body
  body=$(jq -nc --arg writer "$1" --argjson epoch "$2" '{writer: $writer, writer_epoch: $epoch}') || return 1
  printf "wget -T 5 -q -O - --header='Content-Type: application/json' --post-data='%s' 'http://%s/rpc/turn'" \
    "$body" "$STORE_HOST"
}

# turn <local-port> <writer> <epoch>
turn() {
  local request
  request=$(turn_command "$2" "$3") || return 1
  actor_sh "$1" "$request &&
    echo x >> /root/turns.local && echo \"local turns: \$(wc -l < /root/turns.local)\""
}

store
```

The store should report `value: 0` and `epoch: 1`. Create the actor, give it
an egress policy, and then resume it. The policy is per actor. Without it,
the actor can't resolve or reach the store.

```bash
cat > "$LAB_DIR/store-policy.yaml" <<EOF
rules:
- http:
    hostnames: ["${STORE_HOST}"]
EOF

kubectl ate --context "$CTX_A" create actor session-1 -a "$ATESPACE" --template "$TEMPLATE" &&
  kubectl ate --context "$CTX_A" create egress-policy session-1 -a "$ATESPACE" -f "$LAB_DIR/store-policy.yaml" &&
  kubectl ate --context "$CTX_A" resume actor session-1 -a "$ATESPACE"
```

```bash
kubectl ate --context "$CTX_A" proxy actor session-1 8001:80 -a "$ATESPACE" &
PROXY_A=$!
wait_port 8001 && turn 8001 cluster-a 1 && turn 8001 cluster-a 1
```

The second turn should show `value: 2` in the response and `local turns: 2`.
If the actor can't resolve or reach the store, check the actor's egress policy
and that the `session-store` pod in A is ready before continuing.

Start a background writer in A. It keeps using epoch `1` and changes only
the shared count, not the local file:

```bash
LOOP=$(turn_command cluster-a 1) &&
  LOOP=$(jq -nr --arg cmd "while true; do
  $LOOP >> /root/agent.log 2>&1
  sleep 5
done" '$cmd | @sh') &&
  actor_sh 8001 "nohup sh -c $LOOP > /dev/null 2>&1 &"
```

### 4. Drop the tunnel, fence the writer, and start the replacement

Stop the client tunnel to A. Run `store` twice, a few seconds apart. The count
should still climb: the old actor hasn't stopped, only its ingress path has.

This is the failover itself. It simulates losing contact with cluster A, locks the old actor out of the session, and brings up a replacement in cluster B. Five steps:

1. Drop the tunnel
kill "$PROXY_A" stops your local tunnel to the actor in A. That stands in for "the front door can't reach cluster A". Nothing in A changes: the actor is still running and its background loop is still writing. Running store twice shows the count still climbing, which is the problem the rest of the section solves.

2. Fence the session
One SQL UPDATE, run from your workstation, bumps the epoch from 1 to 2. From that instant the database rejects any write still carrying epoch 1. The block saves the response, so you have the new epoch and the number of writes A had made at that exact moment. If the fence fails, it clears FENCE_EPOCH and tells you not to cut over.

3. Create the replacement in B
Only if the fence succeeded, it creates a new actor named session-1 in cluster B, gives it the same egress policy, and resumes it. This is a different actor that happens to share the name. Nothing from A's snapshot or memory is involved.

4. Send the next request through B
Opens a tunnel to the new actor and takes one turn with the new epoch. Two things to look at in the output:
- the shared count is one more than at the fence, so the session carried on;
- local turns: 1, so the actor's own file started over.

5. Check the fence held
Compares A's accepted-write count now with what it was at the fence (they should match), confirms B has one accepted write, and looks in A's PostgREST log for 409 responses, which are the old actor's rejected attempts.

The order is the point of the section: fence first, then create the replacement, then route to it. Do it the other way round and both actors write to the same session until you notice.

The closing paragraph adds the caveats: the 409s are evidence, not a requirement (a truly dead cluster sends nothing), and this fence only stops a stale writer that honestly reports its epoch.


```bash
kill "$PROXY_A"
store
```

> **What if you skip the fence?** Both actors would write with epoch `1`.
> Changing the route doesn't stop the old writer. Fencing later stops further
> writes from A, but doesn't undo what both writers already did.

Fence the session first. Save the response so you have the new epoch and the
number of writes A had made at the moment of the fence. If this block fails,
stop and check the store before proceeding.

```bash
FENCE_EPOCH=
if FENCE=$(lab_sql -qAtc "
  UPDATE session_state.sessions SET epoch = epoch + 1 WHERE id = 'session-1'
  RETURNING json_build_object('epoch', epoch, 'value', value, 'a_writes', a_writes)") &&
   FENCE_EPOCH=$(jq -e '.epoch | select(type == "number" and . >= 2)' <<< "$FENCE"); then
  jq . <<< "$FENCE"
else
  FENCE_EPOCH=
  echo "Fence failed. Do not cut over." >&2
fi
```

Create the replacement in B only after the fence succeeds. This creates a
different actor with the same name, using B's template and its own egress
policy. No checkpoint from A is involved.

```bash
[ -n "$FENCE_EPOCH" ] &&
  kubectl ate --context "$CTX_B" create actor session-1 -a "$ATESPACE" --template "$TEMPLATE" &&
  kubectl ate --context "$CTX_B" create egress-policy session-1 -a "$ATESPACE" -f "$LAB_DIR/store-policy.yaml" &&
  kubectl ate --context "$CTX_B" resume actor session-1 -a "$ATESPACE"
```

If the replacement resumed successfully, send the next request through B:

```bash
kubectl ate --context "$CTX_B" proxy actor session-1 8002:80 -a "$ATESPACE" &
PROXY_B=$!
wait_port 8002 && turn 8002 cluster-b "$FENCE_EPOCH"
```

The shared count should be one more than the count in the fence response.
The new actor prints `local turns: 1`; it didn't recover A's local file.

Check that `a_writes` still matches the fence response and `b_writes` is `1`.
Look for `409` responses in the access log of A's PostgREST, which is the copy
the old writer uses. If the old writer hasn't made another request yet, wait a
few seconds and check again.

```bash
jq '{a_writes_at_fence: .a_writes}' <<< "$FENCE"
store
kubectl --context "$CTX_A" -n session-store logs deployment/session-store -c postgrest --since=2m |
  grep -E 'POST /rpc/turn .*409'
```

Success means A's accepted count hasn't changed, A has at least one rejected
write, and B has one accepted write. The rejection is evidence for this lab,
not a prerequisite for failover: a cluster that's actually down sends no
more requests. The successful fence is what allows cutover.

In production, keep using a durable database but bind writes to an
authenticated actor incarnation instead of trusting the caller to report its
epoch. For untrusted actors, the gateway can inject
credentials outside the sandbox; see [egress credential injection](https://github.com/agent-substrate/substrate/blob/v1.0.0/docs/guides/egress-credential-injection.md).
External side effects need their own fencing or idempotency. Even for a planned
move, don't rely on suspending the old actor: its router can wake it again.

## Cleanup

Delete the old actor once its cluster is reachable. That is cleanup, not what
kept the shared state safe.

```bash
kill "$PROXY_B" "$SQL_PROXY_PID"
kubectl ate --context "$CTX_A" delete actor session-1 -a "$ATESPACE"
kubectl ate --context "$CTX_B" delete actor session-1 -a "$ATESPACE"
kubectl --context "$CTX_A" delete namespace session-store
kubectl --context "$CTX_B" delete namespace session-store
rm "$LAB_DIR/store-policy.yaml" && rmdir "$LAB_DIR"
unset SQL_ADMIN_PASSWORD SQL_LOGIN_PASSWORD
```

Delete the Cloud SQL instance to stop charges; that removes the lab database
and its roles with it. Remove the project IAM binding and delete the dedicated
Google service account when you no longer need them. The Substrate installs and sandbox demo remain in place.

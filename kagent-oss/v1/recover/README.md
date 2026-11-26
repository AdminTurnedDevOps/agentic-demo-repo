# Recover a kagent Session from worker loss

Complete a turn, interrupt the next turn by removing its worker, and recover the same kagent Session. kagent takes a durable snapshot of the backing Agent Substrate Actor at the end of a turn. After a crash, kagent's `RevertSession` API returns the Actor to that snapshot and marks the interrupted turn failed. Sending the next message resumes the Actor on a replacement worker.

The lab checks the Session ID, Actor UID, durable snapshot UUID, and worker pod UID. The agent's recall of an earlier marker is a visible conversation check. The Actor and snapshot records establish what Substrate restored.

## Prerequisites

- A **disposable cluster** installed with kagent OSS 1.0.x and its Agent Substrate 1.0.x runtime. This lab removes a pod from a dedicated WorkerPool.
- Default install names `kagent/kagent-default`, `kagent/kagent-controller`, and `kagent/default-model-config`. The ModelConfig must be able to answer a prompt. The manifest assumes the bundled S3-compatible snapshot store. For an external store, set `spec.substrate.snapshotPolicy.location` in `agent.yaml` to a writable prefix.
- `kubectl` with the `ate` plugin and permission to read Actors in the `kagent` atespace. You also need `kagent`, `grpcurl`, `jq`, and Bash. The `RevertSession` call uses the default lab authentication mode and requires `config.server.grpcReflection=true` in kagent's Helm values. [kagent setup](https://www.kagent.dev/docs/kagent/latest/setup/installation/)

## 1. Set up an isolated Agent

Run these commands from `kagent-oss/v1/recover` in Bash. Create the lab pool with the installed gVisor image, sandbox config, and pod settings from the default pool. kagent uses the pool name and namespace labels to place the lab's Actors.

```bash
kubectl -n kagent get workerpool kagent-default -o json |
  jq -e '
    select(any(.spec.sandboxClasses[]?; .name == "gvisor")) |
    {
      apiVersion: "ate.dev/v1", kind: "WorkerPool",
      metadata: {
        name: "worker-loss-lab", namespace: "kagent",
        labels: {
          "kagent.dev/worker-pool-name": "worker-loss-lab",
          "kagent.dev/worker-pool-namespace": "kagent"
        }
      },
      spec: (.spec | .replicas = 1 | .sandboxClasses |= map(select(.name == "gvisor")))
    }
  ' | kubectl create -f -
```

```
kubectl apply -f agent.yaml
```

In another terminal, keep a loopback port-forward open.

```bash
kubectl -n kagent port-forward svc/kagent-controller 8083:8083
```

## 2. Complete a turn and record its durable snapshot

Use the same Bash terminal for the rest of the lab. Use the kagent CLI to create the Session and send a turn. Look up its backing Actor directly with `kubectl ate` using kagent's `session-<session-id>` naming convention.

```bash
session_id=$(kagent --user-id admin@kagent.dev -n kagent agent session create \
  --agent worker-loss-lab -o json | jq -er '.session.id')
get_actor() {
  kubectl ate get actor "session-$session_id" -a kagent -o json
}

durable_snapshot() {
  jq -er '[.status.snapshots[]? |
    select(.owner == "SNAPSHOT_OWNER_ACTOR" and
           .durableSnapshot.state == "SNAPSHOT_STORAGE_STATE_COMPLETED")]
    | max_by(.generation | tonumber) | .uuid'
}

kagent --user-id admin@kagent.dev -n kagent agent invoke --session "$session_id" \
  --task 'Remember this recovery marker for a later question: cobalt-lantern-71. Reply with the marker.'
```

Wait for the Actor to show `ACTOR_STATE_SUSPENDED` with a completed Actor-owned snapshot. If needed, run the inspection again after the turn ends. Record the snapshot before starting another turn.

```bash
baseline=$(get_actor | jq -ce 'select(.status.state == "ACTOR_STATE_SUSPENDED")')
actor_uid=$(jq -er '.metadata.uid' <<<"$baseline")
snapshot_uuid=$(durable_snapshot <<<"$baseline")
printf 'Session %s\nActor %s\nDurable snapshot %s\n' "$session_id" "$actor_uid" "$snapshot_uuid"
```

## 3. Interrupt a running turn

Start a long streaming task in the background, then run the next block immediately. Keep the invocation running so the fault happens while the Actor holds a worker. Model response times vary. If the turn finishes and takes a new snapshot before the fault, use a fresh Session and repeat from step 2.

```bash
turn_log=$(mktemp)
kagent --user-id admin@kagent.dev -n kagent --timeout 5m agent invoke --session "$session_id" \
  --stream --task 'Write a numbered checklist of 200 release-readiness checks. Give each check one complete sentence.' \
  >"$turn_log" 2>&1 &
turn_pid=$!
```

The following block checks the Actor UID and pod UID, confirms the pod belongs to the lab pool, and force-deletes it to simulate an abrupt loss. It saves the old pod UID for comparison. Ordinary pod deletion can let a kagent turn drain and checkpoint.

```bash
old_pod_uid=$(
  set -euo pipefail
  test -n "$snapshot_uuid"
  for ((attempt = 0; attempt < 30; attempt++)); do
    running=$(get_actor | jq -c --arg uid "$actor_uid" '
      select(.metadata.uid == $uid and .status.state == "ACTOR_STATE_RUNNING")
    ')
    [[ -n "$running" ]] && break
    sleep 1
  done
  if [[ -z "$running" ]]; then
    printf 'The Actor was never observed running. Inspect %s before retrying.\n' "$turn_log" >&2
    exit 1
  fi
  pod=$(jq -er '.status.workerAssignment | select(.workerNamespace == "kagent") | .workerPod' <<<"$running")
  uid=$(jq -er '.status.workerAssignment.workerPodUid' <<<"$running")
  kubectl -n kagent get pod "$pod" -o json | jq -e --arg uid "$uid" '
    .metadata.uid == $uid and .metadata.labels["ate.dev/worker-pool"] == "worker-loss-lab"
  ' >/dev/null
  printf 'Deleting lab worker %s (%s)\n' "$pod" "$uid" >&2
  kubectl -n kagent delete pod "$pod" --grace-period=0 --force --wait=false >&2
  printf '%s\n' "$uid"
)
```

Wait until `get_actor | jq -r '.status.state'` shows `ACTOR_STATE_CRASHED`. Check that the crashed Actor still has the snapshot recorded in step 2. If the state is `SUSPENDED` with a newer snapshot, the turn finished before the fault.

```bash
crashed=$(get_actor | jq -ce 'select(.status.state == "ACTOR_STATE_CRASHED")')
test "$(durable_snapshot <<<"$crashed")" = "$snapshot_uuid" &&
  printf 'The crashed Actor still has the baseline snapshot.\n'
```

## 4. Revert the Session and continue

Call `RevertSession` with the same lab identity so kagent recovers the Actor and marks the interrupted task failed. Then check that the same Actor is suspended at the baseline snapshot.

```bash
session_request=$(jq -nc --arg id "$session_id" '{sessionId:$id}')
grpcurl -plaintext -max-time 120 -H 'X-User-Id: admin@kagent.dev' \
  -d "$session_request" localhost:8083 kagent.api.v1.SessionService/RevertSession |
  jq -e --arg id "$session_id" '.session | select(.id == $id) | {id, state}'
restored=$(get_actor | jq -ce --arg uid "$actor_uid" '
  select(.metadata.uid == $uid and .status.state == "ACTOR_STATE_SUSPENDED")
')
test "$(durable_snapshot <<<"$restored")" = "$snapshot_uuid" &&
  printf 'Same Session and Actor, reverted to the baseline snapshot.\n'
```

Wait for a ready lab pod with a different UID. The lab pool has one replica, so the next turn can only run on the replacement. If Kubernetes reports it ready before it registers with Substrate, wait for registration before retrying the invocation.

```bash
replacement=''
for ((attempt = 0; attempt < 60; attempt++)); do
  replacement=$(kubectl -n kagent get pods -l ate.dev/worker-pool=worker-loss-lab -o json |
    jq -c --arg uid "$old_pod_uid" '
      .items[] | select(.metadata.uid != $uid and .metadata.deletionTimestamp == null) |
      select(any(.status.conditions[]?; .type == "Ready" and .status == "True")) |
      {name: .metadata.name, uid: .metadata.uid}
    ')
  [[ -n "$replacement" ]] && break
  sleep 5
done
test -n "$old_pod_uid" && test -n "$replacement" && printf 'Replacement: %s\n' "$replacement"
```

Once the replacement is confirmed, send a message to the original Session.

```bash
kagent --user-id admin@kagent.dev -n kagent agent invoke --session "$session_id" \
  --task 'What recovery marker did I ask you to remember in the first turn?'
```

The reply should include `cobalt-lantern-71`. The interrupted turn is failed rather than resumed partway through. [kagent worker-loss behavior](https://kagent.dev/docs/kagent/latest/operations/operational-considerations/#node-operations)

## Cleanup

```bash
kagent --user-id admin@kagent.dev -n kagent agent session delete "$session_id"
kubectl delete -f agent.yaml
kubectl -n kagent delete workerpool worker-loss-lab
rm -f "$turn_log"
```

Stop the port-forward with Ctrl-C.

# Recover from worker loss

This demo shows that an actor can recover from worker loss using its last durable checkpoint

Goal:
- Take a durable checkpoint
- Make changes
- Remove the hosting worker
- Restore the actor on its replacement.

The lab compares the file content, in-memory task step, process session ID, and Kubernetes pod UID before and after recovery.

## Setup

Follow the [workbench prerequisites and image build](../agentic-workbench-demo/README.md#prerequisites) to set `WORKER_IMAGE` and `WORKBENCH_IMAGE`. Run these commands from `substrate/recover`.

```bash
kubectl config current-context
envsubst '${WORKER_IMAGE}' < workerpool.yaml.tmpl | kubectl apply -f -
kubectl ate create atespace ate-demo-recover
envsubst '${WORKBENCH_IMAGE}' < actor-template.yaml.tmpl | kubectl ate create actor-template -f -
kubectl wait -n ate-demo-recover --for=jsonpath='{.status.readyReplicas}'=1 workerpool/recover --timeout=5m
kubectl ate create actor session -a ate-demo-recover --template recover
kubectl ate proxy actor session 8081:80 -a ate-demo-recover
```

Leave the proxy running. Run the rest in a second Bash terminal with `curl` and `jq`. Use a fresh actor for each run so the starting step is 1.

## 1. Take a durable checkpoint

The first request boots the actor. Set the file to `checkpointed value` and advance to step 2. Capture the complete response, including the session ID.

```bash
space=ate-demo-recover
url=http://127.0.0.1:8081
curl -fsS -X PUT --data-binary 'checkpointed value' "$url/api/file" | jq .
checkpoint=$(curl -fsS -X POST "$url/api/advance" | jq -ceS '
  select(.step == 2 and .content == "checkpointed value" and (.sessionId | length > 0))
')
printf '%s\n' "$checkpoint"

kubectl ate suspend actor session -a "$space" --mode=sync
kubectl ate get actor session -a "$space" -o json | jq -e '
  .status | select(.state == "ACTOR_STATE_SUSPENDED")
  | .snapshots[] | select(.durableSnapshot.state == "SNAPSHOT_STORAGE_STATE_COMPLETED")
  | {uuid, fidelity, durableState: .durableSnapshot.state}
'
```

## 2. Resume, change the state, and remove the worker

A GET through the proxy resumes the actor. Change the file to `after checkpoint` and advance to step 3. Leave the actor running so the new values are outside the durable checkpoint.

```bash
curl -fsS "$url/api/session" | jq .
curl -fsS -X PUT --data-binary 'after checkpoint' "$url/api/file" | jq .
curl -fsS -X POST "$url/api/advance" | jq -e '
  select(.step == 3 and .content == "after checkpoint")
'
```

Read the exact pod name and UID from the running actor. Confirm the pod still has that UID and belongs to the recovery pool before deleting it.

```bash
assignment=$(kubectl ate get actor session -a "$space" -o json | jq -ce --arg space "$space" '
  .status | select(.state == "ACTOR_STATE_RUNNING")
  | .workerAssignment | select(.workerNamespace == $space)
')
pod=$(jq -er '.workerPod' <<<"$assignment")
old_uid=$(jq -er '.workerPodUid' <<<"$assignment")
printf 'Removing worker %s/%s (%s)\n' "$space" "$pod" "$old_uid"

kubectl get pod "$pod" -n "$space" -o json | jq -e --arg uid "$old_uid" '
  .metadata.uid == $uid and .metadata.labels["ate.dev/worker-pool"] == "recover"
' &&
kubectl delete pod "$pod" -n "$space" --wait=false
```

Wait for Substrate to mark the actor `CRASHED`. Continue once the final command prints that state. The worker and crash details are also available in the full actor JSON.

```bash
for ((attempt=0; attempt<60; attempt++)); do
  state=$(kubectl ate get actor session -a "$space" -o json | jq -er '.status.state')
  [[ "$state" == ACTOR_STATE_CRASHED ]] && break
  sleep 2
done
if [[ "$state" == ACTOR_STATE_CRASHED ]]; then
  printf '%s\n' "$state"
else
  printf 'Timed out waiting for actor to reach CRASHED (last state: %s). Stop here.\n' "${state:-unknown}" >&2
fi
```

## 3. Revert and verify recovery

Revert returns the actor to `SUSPENDED` at the completed snapshot. Wait for pool capacity, then send a request to reopen it. If the router briefly returns `503` while the new worker registers, retry the request.

```bash
kubectl ate revert actor session -a "$space"
kubectl ate get actor session -a "$space"
kubectl wait -n "$space" --for=jsonpath='{.status.readyReplicas}'=1 workerpool/recover --timeout=5m

recovered=$(curl -fsS --retry 12 --retry-delay 1 "$url/api/session" | jq -ceS .)
new_uid=$(kubectl ate get actor session -a "$space" -o json | jq -er '
  .status | select(.state == "ACTOR_STATE_RUNNING") | .workerAssignment.workerPodUid
')
printf 'At checkpoint:     %s\nAfter recovery:    %s\n' "$checkpoint" "$recovered"
printf 'Old pod UID: %s\nNew pod UID: %s\n' "$old_uid" "$new_uid"
[[ -n "$checkpoint" && "$recovered" == "$checkpoint" && -n "$old_uid" && -n "$new_uid" && "$new_uid" != "$old_uid" ]] &&
  printf 'Verified: checkpoint restored on a replacement worker.\n'
```

The file is back to `checkpointed value`, the task is back at step 2, and the in-memory process ID matches. The pod UID changes even if Kubernetes schedules the replacement on the same node. Open [the recovered workbench](http://127.0.0.1:8081/) to show the restored state in the browser.

## Cleanup

Stop the proxy with Ctrl-C.

```bash
kubectl ate delete actor session -a ate-demo-recover
kubectl ate delete actor-template recover -a ate-demo-recover
kubectl ate delete atespace ate-demo-recover
kubectl delete namespace ate-demo-recover
```

# Agent Workbench

The workbench shows that Agent Substrate can free a worker while a session is idle, then bring that session back where it left off.

This is important because it proves that when an Actor is suspended, the snapshot via object storage is what contains the changes so the edit to `task.md` (via `durableDir`, which is the per-actor storage that survives suspend/resume and is stored in the snapshot) doesn’t get deleted/removed. The in-memory session ID and task step all come back, so the same process continues where it left off (the session ID and task step also come from the snapshot).

Goal:

1. Edit a file
2. Advance a task
3. Suspend the actor.

When you reopen the URL, Substrate restores the edits and the running process. The file lives in a durable volume (`durableDir`, which is a per-actor persistent data volume in the snapshot) and the session ID and task step live only in Go process memory. The browser fetches both from the actor on page load.

## Prerequisites

- [Agent Substrate](https://github.com/agent-substrate/substrate) installed with a default gVisor SandboxConfig and object storage configured for snapshots. See the [setup checklist](../substrate-setup-checklist.md).
- Docker with Buildx, a registry that both you and the cluster can access, `envsubst`, and `jq`. Build for the architecture of the worker nodes.
- `kubectl` with the `ate` plugin. The router must allow the `atenet-client` SPIFFE ID used by `kubectl ate proxy actor`. If it doesn't work with how you installed Agent Substrate (e.g., - if you installed with the `kagent` CLI using `kagent install`), run the following:

```bash
helm upgrade substrate oci://ghcr.io/kagent-dev/substrate/helm/substrate \
  --version 1.0.0 -n ate-system --reuse-values \
  --set 'atenetRouter.ingressAllowedSPIFFEIDs={spiffe://cluster.local/ns/kagent/sa/kagent-controller,spiffe://cluster.local/ns/ate-system/sa/atenet-client}'
```

## Build and deploy

```bash
cd substrate/agentic-workbench-demo
export WORKBENCH_TAG=REGISTRY/PROJECT/agentic-workbench:demo # your container registry
export WORKER_IMAGE=ghcr.io/kagent-dev/substrate/ateworker-gvisor:v1.0.0
build_metadata=$(mktemp)
docker buildx build --platform linux/amd64 --push -t "$WORKBENCH_TAG" --metadata-file "$build_metadata" . &&
  digest=$(jq -er '."containerimage.digest"' "$build_metadata") &&
  export WORKBENCH_IMAGE="${WORKBENCH_TAG%:*}@$digest"
rm -f "$build_metadata"
```

Use `linux/arm64` for Arm workers. The build metadata pins the workload image by digest. If you already have a published image, export its digest reference as `WORKBENCH_IMAGE` and skip the build.

```bash
envsubst '${WORKER_IMAGE}' < workerpool.yaml.tmpl | kubectl apply -f -
kubectl ate create atespace ate-demo-workbench
envsubst '${WORKBENCH_IMAGE}' < actor-template.yaml.tmpl | kubectl ate create actor-template -f -
kubectl wait -n ate-demo-workbench --for=jsonpath='{.status.readyReplicas}'=1 workerpool/workbench --timeout=5m
kubectl ate create actor session -a ate-demo-workbench --template workbench
kubectl ate proxy actor session 8080:80 -a ate-demo-workbench
```

Leave the proxy running throughout the demo.

## Walkthrough

The "workbench" is a Go web server (running in an actor) that runs a UI so you can see it in real time.

**What the demo proves:** you edit the file, advance the task to step 3, then suspend the actor. Substrate takes a memory snapshot (`SNAPSHOT_FIDELITY_MEMORY` in the template), uploads it along with the durable dir, and frees the worker. When you reopen the URL, Substrate restores the snapshot. Your edit is still there, the step is still 3, and the session ID is unchanged.


1. Open [the workbench](http://127.0.0.1:8080/). The request starts the actor. Note the **Process session** ID.
2. Edit `task.md`, click **Save file**, and click **Advance task** twice to reach step 3.
3. Close the workbench UI and run the following in a second terminal.

   - Suspend the actor.

   ```bash
   kubectl ate suspend actor session -a ate-demo-workbench
   ```

   - Inspect the actor and its snapshot.

   ```bash
   kubectl ate get actor session -a ate-demo-workbench -o json 2>/dev/null | jq '{state: .status.state, workerPod: (.status.workerAssignment.workerPod // "none"), snapshots: [.status.snapshots[]? | {uuid, fidelity, storage: .durableSnapshot.state, uri: .durableSnapshot.object.snapshotUri}]}'
   ```

   - `workerPod: none`: the actor no longer reserves any worker capacity. Its CPU and memory return to the pool for other actors. In this demo one actor fills the worker, which is what the two-session variation below relies on.
   - `SNAPSHOT_FIDELITY_MEMORY`: the snapshot holds process memory (session ID, step) plus the `durableDir` contents (`task.md`).
   - `SNAPSHOT_STORAGE_STATE_COMPLETED`: the upload finished, so the state lives in object storage, not on the node.
   - `uri`: where the snapshot is stored, keyed by actor UID and snapshot UUID.

4. Reopen the same URL in a fresh tab. Verify the saved edit, step 3, and the same session ID.

5. Run the following command to see the new assignment (it may or may not land on the same pod).

```bash
kubectl ate get actor session -a ate-demo-workbench
```

For a two-session variation, create a second actor from the same template and proxy it on local port `8082`. It can use the sole worker while the first actor is suspended. Suspend the second actor before reopening the first. Delete the second actor before cleanup.

## Cleanup

Stop the proxy with Ctrl-C. Delete the actor before the template and pool so Substrate can clean up the actor's snapshots.

```bash
kubectl ate delete actor session -a ate-demo-workbench
kubectl ate delete actor-template workbench -a ate-demo-workbench
kubectl ate delete atespace ate-demo-workbench
kubectl delete namespace ate-demo-workbench
```

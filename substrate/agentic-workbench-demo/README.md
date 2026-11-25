# Agent Workbench

Edit a file, advance a task, and suspend the actor. When you reopen the URL, Substrate restores the edits and the running process. The file lives in a durable volume. The session ID and task step live only in Go process memory. The browser fetches both from the actor on page load.

The workbench is a single Go HTTP server with a deterministic three-step release review. It needs no Jupyter, model, or API key.

## Prerequisites

- [Agent Substrate](https://github.com/agent-substrate/substrate) installed with a default gVisor SandboxConfig and object storage configured for snapshots. See the [setup checklist](../substrate-setup-checklist.md).
- `kubectl` with the `ate` plugin. The router must allow the `atenet-client` SPIFFE ID used by `kubectl ate proxy actor`.
- Docker with Buildx, a registry that both you and the cluster can access, `envsubst`, and `jq`. Build for the architecture of the worker nodes.

## Build and deploy

Run from `substrate/agentic-workbench-demo`. Set `WORKBENCH_TAG` to an image tag you can push and `WORKER_IMAGE` to the gVisor worker image for your Substrate installation. To find that image, inspect an existing gVisor WorkerPool with `kubectl get workerpools -A -o yaml`.

```bash
export WORKBENCH_TAG=REGISTRY/PROJECT/agentic-workbench:demo
export WORKER_IMAGE=REGISTRY/PROJECT/ateworker-gvisor:SUBSTRATE_VERSION
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

1. Open [the workbench](http://127.0.0.1:8080/). The request starts the actor. Note the **Process session** ID.
2. Edit `task.md`, click **Save file**, and click **Advance task** twice to reach step 3. Wait for the app to acknowledge the changes.
3. Close the tab and run the following in a second terminal. The first read shows a running actor and its worker. The synchronous suspend waits for the durable upload, then the second read shows a suspended actor with no worker assignment.

   ```bash
   kubectl ate get actor session -a ate-demo-workbench
   kubectl ate suspend actor session -a ate-demo-workbench --mode=sync
   kubectl ate get actor session -a ate-demo-workbench
   ```

4. Reopen the same URL in a fresh tab. Verify the saved edit, step 3, and the same session ID. Run `kubectl ate get actor session -a ate-demo-workbench` again to see the new assignment. It may be on the same pod.

For a two-session variation, create a second actor from the same template and proxy it on local port `8082`. It can use the sole worker while the first actor is suspended. Suspend the second actor before reopening the first. Delete the second actor before cleanup.

## Local preview

Run `WORKSPACE_DIR="$(mktemp -d)" go run .` with Go 1.27.4 or newer and open [the workbench](http://127.0.0.1:8080/). Restarting Go with the same workspace directory keeps the file and resets the process session and step. The cluster walkthrough demonstrates checkpoint and restore.

## Cleanup

Stop the proxy with Ctrl-C. Delete the actor before the template and pool so Substrate can clean up the actor's snapshots.

```bash
kubectl ate delete actor session -a ate-demo-workbench
kubectl ate delete actor-template workbench -a ate-demo-workbench
kubectl ate delete atespace ate-demo-workbench
kubectl delete namespace ate-demo-workbench
```

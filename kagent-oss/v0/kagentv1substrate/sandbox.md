# Demo: Triage a log in a kagent Sandbox

A Sandbox is a short-lived workspace for one job. This demo uploads a log, counts its lines and `ERROR` entries with the shell already in the tools image, downloads the summary, and deletes the workspace. The same job is then handed to an agent. The agent's Session stays; the Sandbox does not.

Nothing in the sandbox is reachable as a service. It has no ingress and no allowed egress, so the job cannot:
- Install packagee
- Clone a repository
- Call an API.

It’s almost like a mid-level tool call or an init container. A short-lived workspace that shows up, runs the work, and is removed. The difference is it’s isolated, so you can run it in a sandboxed environment. The closest picture when mapping it to an analogy is it’s a temporary computer with a return time: heavier than one function call, lighter than an application you deploy.


The `Sandbox` itself is an API call (no CRD/k8s object). `SandboxTemplate` (a CR/k8s object) is what the create call binds to. It answers the “what environment this sandbox is” question. 

Sandbox preparation needs the kagent build that contains `SandboxTemplate` (latest release) and Agent Substrate `v0.3.0-alpha1`. The API group on these manifests is `api.kagent.dev/v1alpha3`.

## Prerequisites

https://kagent.dev/docs/kagent/1.x/setup/installation/

The manifests below use namespace `kagent`, WorkerPool `kagent-default`, snapshot location `s3://ate-snapshots/kagent`, and ModelConfig `default-model-config`. Confirm the WorkerPool and the ModelConfig before applying anything. `kubectl` exits non-zero when either object is missing. A fresh installation is ready for these manifests once those two objects exist. `s3://ate-snapshots/kagent` is the location the manifests write. These commands leave that bucket unchecked.

```sh
set -euo pipefail
kubectl -n kagent get workerpools.ate.dev kagent-default
kubectl -n kagent get modelconfigs.api.kagent.dev default-model-config
```

## Prepare the tools environment

`SandboxTemplate` prepares a reusable runtime. It does not create a sandbox. The workload image is a digest-pinned Alpine Go ADK image. The triage command uses `sh`, `grep`, and `wc` from that image.

```sh
kubectl apply -f - <<'YAML'
apiVersion: api.kagent.dev/v1alpha3
kind: SandboxTemplate
metadata:
  name: scratch
  namespace: kagent
spec:
  workload:
    image: ghcr.io/kagent-dev/kagent/golang-adk@sha256:699c7a36daa0050d5954f42ad3b614690d825664cf64ffe8871dbe20dc68464e
  substrate:
    workerPoolRef:
      name: kagent-default
    snapshotPolicy:
      location: s3://ate-snapshots/kagent
YAML

kubectl -n kagent wait --for=condition=Ready sandboxtemplate/scratch --timeout=5m
```

## Run the job from the CLI

Write the sample log beside the commands:

```sh
cat > app.log <<'EOF'
2026-09-27T10:00:00Z INFO checkout started
2026-09-27T10:00:01Z ERROR payment gateway timeout
2026-09-27T10:00:02Z INFO retry scheduled
2026-09-27T10:00:03Z ERROR inventory service unavailable
2026-09-27T10:00:04Z INFO checkout finished
EOF
```

Create one sandbox and keep the request ID. The command blocks until the Actor is ready or the CLI timeout, which defaults to five minutes. On a transient failure, run the same command again with the same `--request-id`. A new request ID allocates a different sandbox.

> [!NOTE]
> Because Sandbox is an API call, you can hit it with the kagent CLI
> kagent sandbox create, upload, exec, download, and delete are those calls
> An Agent, however, does not shell out to that CLI. It calls the same service through the kagent-api MCP tools, such as
> `create_sandbox` and `start_sandbox_process`.

`set -o pipefail` makes a failed create fail the assignment. `jq -er` exits non-zero when `.id` is missing or null, so the next command does not run with an empty ID.

```sh
set -euo pipefail
REQUEST_ID="$(uuidgen)"
ID="$(kagent sandbox create scratch --request-id "$REQUEST_ID" --name log-triage --ttl 15m -o json | jq -er .id)"
test -n "$ID"
kagent sandbox get "$ID"
```

Continue when the row shows `RUNTIME_STATE_READY` and `RUNTIME_OPERATION_NONE`. `EXPIRES` is fifteen minutes from creation. Using the sandbox does not move it.

Upload the log, then suspend and resume before running anything. The file is on the durable directory. A process started before suspend would not survive the resume.

```sh
kagent sandbox upload "$ID" ./app.log app.log
kagent sandbox suspend "$ID"
kagent sandbox resume "$ID"
```

Count the log inside the workspace. The remote exit code becomes the CLI exit code.

```sh
kagent sandbox exec "$ID" -- sh -c 'lines=$(wc -l < app.log); errors=$(grep -c ERROR app.log || true); printf "lines=%s\nerrors=%s\n" "$lines" "$errors" | tee summary.txt'
kagent sandbox download "$ID" summary.txt ./summary.txt
cat ./summary.txt
```

The summary is `lines=5` and `errors=2`. `summary.txt` on your machine is the downloaded artifact. The copy inside the sandbox disappears with the workspace:

```sh
set -euo pipefail
kagent sandbox delete "$ID"
kagent sandbox list -o json | jq -er --arg id "$ID" '[.sandboxes[]? | select(.id == $id)] | length == 0'
```

That check says this demo sandbox is absent from the live list. Other sandboxes owned by this caller can still be listed. Sandboxes owned by other users are not in this list. `kagent sandbox get "$ID"` still returns the deleted tombstone. Retrying the original create command does not bring this sandbox back and does not reset its lifetime.

## Ask an agent to do the same job

Helm installs a `RemoteMCPServer` named `kagent-api` in the standard release. Confirm the name before applying the agent:

```sh
kubectl -n kagent get remotemcpservers
```

The agent may use only the sandbox tools for this job. `KAGENT_PROPAGATE_TOKEN=true` makes the sandbox belong to the caller who invokes the agent. With the default unsecured installation, that caller is `admin@kagent.dev`, the same identity the CLI uses.

> [!NOTE]
> As mentioned in the **## Run the job from the CLI** section, you can see in the `RemoteMCPServer` object
> below in the `Agent` object, the `kagent-api` call is used to reach the sandbox

```sh
kubectl apply -f - <<'YAML'
apiVersion: api.kagent.dev/v1alpha3
kind: Agent
metadata:
  name: sandbox-demo
  namespace: kagent
spec:
  template:
    description: Triages a log in a short-lived sandbox
    modelConfig:
      name: default-model-config
    systemPrompt: |
      You triage logs with the sandbox tools. Use SandboxTemplate
      namespace kagent and name scratch. Generate one request_id and
      send that same request_id with the same inputs if create_sandbox
      must be retried. Set ttl_seconds to 900. Wait until state is
      RUNTIME_STATE_READY and operation is RUNTIME_OPERATION_NONE.
      Write the log below to app.log under /data/workspace. Count lines
      and ERROR lines with sh, using grep -c and wc. Read the command
      output, then delete_sandbox. Do not install software or use the
      network. Report only the counts from the sandbox.
    tools:
      - mcp:
          server:
            kind: RemoteMCPServer
            name: kagent-api
          tools:
            - create_sandbox
            - get_sandbox
            - write_sandbox_file
            - start_sandbox_process
            - get_sandbox_process
            - read_sandbox_outputs
            - delete_sandbox
  harness:
    kagent: {}
    workload:
      image: ghcr.io/kagent-dev/kagent/golang-adk@sha256:699c7a36daa0050d5954f42ad3b614690d825664cf64ffe8871dbe20dc68464e
    env:
      - name: KAGENT_PROPAGATE_TOKEN
        value: "true"
    substrate:
      workerPoolRef:
        name: kagent-default
      snapshotPolicy:
        location: s3://ate-snapshots/kagent
YAML

kubectl -n kagent wait --for=condition=Ready agent/sandbox-demo --timeout=5m
```

Create a conversation and send the log in the task. The agent cannot see `./app.log` on your machine. The text in the prompt is the input it writes into the sandbox.

The table output of `invoke` is only the agent's reply. Tool activity is an A2A artifact, and each tool call or tool response is a data part. `kagent.dev/a2a/part-type` is `function_call` or `function_response`, and `.data.name` is the MCP tool. A successful result is a `function_response` whose `.data.response` is an object with no `error` field. The Go ADK places the MCP structured result at `.data.response.output`. For `delete_sandbox`, that object is the sandbox summary, and a finished delete has `output.state` equal to `RUNTIME_STATE_DELETED`. `--stream -o json` writes those artifacts. The last command fails unless the task reached `TASK_STATE_COMPLETED`, each of `create_sandbox`, `write_sandbox_file`, `start_sandbox_process`, `read_sandbox_outputs`, and `delete_sandbox` has a successful response, and the `delete_sandbox` response reports `RUNTIME_STATE_DELETED`. A `delete_sandbox` function call is the request. Deletion succeeded when that response reports `RUNTIME_STATE_DELETED`.

```sh
set -euo pipefail
SESSION="$(kagent agent session create --agent sandbox-demo --request-id "$(uuidgen)" -o json | jq -er .session.id)"
test -n "$SESSION"
kagent agent invoke --session "$SESSION" --stream -o json --task "$(cat <<'EOF'
Triage this log in the scratch sandbox, then delete the sandbox.

2026-09-27T10:00:00Z INFO checkout started
2026-09-27T10:00:01Z ERROR payment gateway timeout
2026-09-27T10:00:02Z INFO retry scheduled
2026-09-27T10:00:03Z ERROR inventory service unavailable
2026-09-27T10:00:04Z INFO checkout finished
EOF
)" | tee invoke.jsonl | jq -r '
  .artifactUpdate.artifact.parts[]?
  | select(.metadata["kagent.dev/a2a/part-type"] == "function_call" or .metadata["kagent.dev/a2a/part-type"] == "function_response")
  | .metadata["kagent.dev/a2a/part-type"] as $kind
  | .data.name as $name
  | if $kind == "function_response" then
      if (.data.response | type) != "object" then "\($kind)\t\($name)\tunreadable"
      elif (.data.response | has("error")) then "\($kind)\t\($name)\terror"
      elif $name == "delete_sandbox" and (.data.response.output | type) == "object" then "\($kind)\t\($name)\t\(.data.response.output.state // "no-state")"
      elif $name == "delete_sandbox" then "\($kind)\t\($name)\tno-state"
      else "\($kind)\t\($name)\tok"
      end
    else "\($kind)\t\($name)"
    end
'
jq -ser --argjson want '["create_sandbox","write_sandbox_file","start_sandbox_process","read_sandbox_outputs","delete_sandbox"]' '
  def responses($parts; $name):
    [ $parts[]
      | select(.metadata["kagent.dev/a2a/part-type"] == "function_response" and .data.name == $name)
      | .data.response
      | select(type == "object" and (has("error") | not)) ];
  ([ .[] | .artifactUpdate.artifact.parts[]? ]) as $parts
  | (map(.statusUpdate.status.state) | index("TASK_STATE_COMPLETED") != null) as $done
  | ([$want[] | select(responses($parts; .) | length == 0)]) as $missing
  | ([ responses($parts; "delete_sandbox")[] | select(.output | type == "object") | .output.state | select(. == "RUNTIME_STATE_DELETED") ] | length > 0) as $deleted
  | if ($done | not) then error("task did not complete")
    elif ($missing | length) > 0 then error("missing successful tool responses: \($missing)")
    elif ($deleted | not) then error("delete_sandbox response state is not RUNTIME_STATE_DELETED")
    else $want
    end
' invoke.jsonl
```

The printed lines are the calls and the response outcomes. The jq command accepts the turn only after every required tool has a response without an `error` field and `delete_sandbox` reports `RUNTIME_STATE_DELETED`. After that command succeeds, the sandbox from this turn is absent from your live list. Other sandboxes you own can still be listed.

```sh
kagent sandbox list
```

The Session is still there. Delete it when the demo is over:

```sh
kagent agent session delete "$SESSION"
```

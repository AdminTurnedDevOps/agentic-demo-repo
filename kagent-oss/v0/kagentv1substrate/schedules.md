# Demo: Run a kagent agent on a schedule

This demo creates a weekday Kubernetes health report. A kagent Schedule stores
the cadence and prompt; each firing creates a **new AgentInstance** backed by an
Agent Substrate Actor. The execution record points to the original A2A task and
conversation. This is a kagent control-plane feature, not a Kubernetes CronJob
or a `ScheduledRun` custom resource.

## Prerequisites

https://kagent.dev/docs/kagent/1.x/setup/installation/

## Create a read-only reporting agent

This AgentTemplate exposes only `k8s_get_resources` from the installed tool
server. It can inspect cluster resources for each report without access to the
server's mutating Kubernetes tools. The Harness uses the published alpha3 Go
ADK image, pinned by its multi-platform digest, and the existing WorkerPool and
snapshot bucket.

```sh
kubectl apply -f - <<'YAML'
apiVersion: kagent.dev/v1alpha3
kind: Harness
metadata:
  name: schedule-demo-harness
  namespace: kagent
spec:
  kagent: {}
  workload:
    image: ghcr.io/kagent-dev/kagent/golang-adk@sha256:699c7a36daa0050d5954f42ad3b614690d825664cf64ffe8871dbe20dc68464e
  substrate:
    workerPoolRef:
      name: kagent-default
    snapshotPolicy:
      location: s3://ate-snapshots/kagent
  allowedAgentTemplates:
    selector:
      matchLabels:
        kagent.dev/harness: schedule-demo-harness
---
apiVersion: kagent.dev/v1alpha3
kind: AgentTemplate
metadata:
  name: schedule-demo-agent
  namespace: kagent
  labels:
    kagent.dev/harness: schedule-demo-harness
spec:
  description: Read-only Kubernetes status reporter
  modelConfig:
    name: default-model-config
  systemPrompt: |
    You are a concise Kubernetes status reporter. Use k8s_get_resources for
    every live cluster fact. Report what the tool returns, including any Pods
    that are not Ready. Do not modify resources or guess at missing data.
  tools:
    - mcp:
        server:
          kind: RemoteMCPServer
          name: kagent-tool-server
        tools:
          - k8s_get_resources
YAML

kubectl -n kagent get agenttemplate schedule-demo-agent -o json \
  | jq '.status.harnesses[]? | {harness, conditions}'
```

Continue when `schedule-demo-harness` reports `Ready=True`. A missing tool,
model, or WorkerPool appears in the pair's conditions.

In another terminal, forward the UI and leave it running:

```sh
kubectl -n kagent port-forward svc/kagent-ui 8080:8080
```

## Create a weekday schedule

Open `http://localhost:8080/schedules` and select **New Schedule**. Fill in the
form:

| Field | Value |
| --- | --- |
| Agent | `kagent/schedule-demo-agent on schedule-demo-harness` |
| Schedule Name | `Weekday cluster health report` |
| Time zone | `America/New_York` |
| Repeat | **Weekly** |
| On days | **Monday**, **Tuesday**, **Wednesday**, **Thursday**, **Friday** |
| At time | `09:00` |
| Prompt | `Use k8s_get_resources to check Pods in kagent and ate-system. Report each namespace, any non-Ready Pods, and one sentence on overall health. Do not change anything.` |
| Execution timeout (seconds) | `120` |
| Enable Schedule | On |

Select **Create schedule**. The weekly controls produce the cron expression
`0 9 * * 1-5`. The details page shows the next execution in your browser's
local time; kagent evaluates the schedule in `America/New_York`, including
daylight-saving changes. The 120-second timeout includes queueing and Actor
startup. No long-running agent stays active between firings.

The details page is at `http://localhost:8080/schedules/<schedule-id>`.

## Run it now and inspect the execution

On the **Weekday cluster health report** details page, select **Run**. This
queues an execution immediately; you do not need to wait until 09:00.

Under **Execution history**, find the row whose **Trigger** is **Manual**.
The **State** starts as **Pending** and can show **Running** before it reaches
**Succeeded**. The page refreshes the history automatically; use **Refresh**
if you want to check sooner. A failed or timed-out execution shows its reason
in the **Failure reason** column.

Expand the row to see the prompt, deadline, and **Original task** ID. Select
**Open conversation** to read the report. That task ID records the scheduled
invocation; later turns in the conversation do not replace it.

# Accessing the agentgateway UI on Kubernetes

**agentgateway OSS + Kubernetes (v1.3.0+)**

agentgateway OSS ships a built-in web UI starting in **v1.3.0**. On Kubernetes the UI is **not** served by the control plane (controller) — it's served by each **data-plane proxy**, which only exists once you create a `Gateway`. This guide shows how to reach it, and explains what it can and can't do so you don't go looking for a fleet-wide management console that the OSS edition doesn't have.

> The UI here is the open-source, per-proxy dashboard. A unified, multi-gateway management console ("single pane of glass") is a separate **Enterprise** feature (Solo UI / management plane).

---

## How it's wired

| Component | Image | Serves the UI? |
|-----------|-------|----------------|
| Control plane (controller) | `cr.agentgateway.dev/controller` (Go) | No — watches CRDs, programs proxies over XDS |
| Data-plane proxy (one per `Gateway`) | `cr.agentgateway.dev/agentgateway` (Rust) | **Yes** — `/ui` on the admin port `localhost:15000` |

Key facts (verified against the v1.3.0 source):

- The UI is compiled into the **Rust proxy image** (release builds it with `CARGO_FEATURES=agentgateway/ui`). The Go controller image does not have it.
- The proxy binds its admin/UI port to **`localhost:15000`** inside the pod. It is **not** added to the Gateway's `Service`/LoadBalancer, so you reach it with `kubectl port-forward`, not the gateway's external IP.
- A fresh control-plane-only install has **no proxy pod**, so there is **no UI yet**. You must create a `Gateway` first.

---

## Prerequisites

- agentgateway OSS control plane installed (see [`install-on-k8s.md`](./install-on-k8s.md)). Confirm the controller is running and the GatewayClass is accepted:

```bash
kubectl get pods -n agentgateway-system
kubectl get gatewayclass agentgateway
# CONTROLLER: agentgateway.dev/agentgateway   ACCEPTED: True
```

---

## Step 1 — Create a Gateway (this is what spins up the UI)

> **Naming gotcha:** do **not** name the Gateway `agentgateway` in the `agentgateway-system` namespace. The deployer creates a proxy Deployment/Service named after the Gateway, which collides with the Helm release's controller resources of the same name — the proxy pod then never starts and the failure is silent (the Gateway still reports `Programmed=True`). Use a distinct name like `agw-ui`.

```yaml
# agw-ui-gateway.yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: agw-ui
  namespace: agentgateway-system
spec:
  gatewayClassName: agentgateway
  listeners:
    - name: http
      protocol: HTTP
      port: 8080
```

```bash
kubectl apply -f agw-ui-gateway.yaml
kubectl wait -n agentgateway-system --for=condition=Programmed gateway/agw-ui --timeout=120s
```

## Step 2 — Confirm the data-plane proxy pod is up

A new Deployment/pod named after the Gateway should appear, running the **Rust proxy image** (the one with the UI):

```bash
kubectl get pods -n agentgateway-system -l gateway.networking.k8s.io/gateway-name=agw-ui
# agw-ui-xxxxxxxxx-xxxxx   1/1   Running

kubectl get deploy -n agentgateway-system agw-ui \
  -o jsonpath='{.spec.template.spec.containers[*].image}{"\n"}'
# cr.agentgateway.dev/agentgateway:v1.3.0
```

## Step 3 — Port-forward and open the UI

```bash
kubectl port-forward -n agentgateway-system deploy/agw-ui 15000:15000
```

Then open: **http://localhost:15000/ui**

Quick check it's live:

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:15000/ui   # -> HTTP 200
```

---

## Why the gateway's LoadBalancer IP won't show the UI

On GKE (and other clouds) the `Gateway` gets a LoadBalancer Service with an external IP, but it only publishes the **listener** ports you declared in `spec.listeners` (e.g. `8080`) — that's for the agent/LLM/MCP traffic you route *through* the gateway. The admin/UI port `15000` is **not** on that Service, and the proxy only listens for it on the pod's loopback. So:

```bash
curl -m 5 http://<gateway-external-ip>:15000/ui   # -> no response (expected)
```

The external IP is for routed traffic; the UI stays `port-forward`-only by default.

---

## What the UI can and can't do (important)

The OSS UI is a **per-proxy inspector**, not a control plane:

- **Scoped to one Gateway.** Each Gateway = its own proxy = its own UI, showing only *that* proxy's config slice (the listeners/routes/policies the controller XDS-pushed to it). Five Gateways = five separate UIs. There is **no aggregated, cluster-wide view** of all gateways/routes/policies in OSS.
- **Read-only on Kubernetes.** The proxy runs in XDS mode (`gateway_mode: Xds`), where config comes from the controller, not a local file. The UI's write path is explicitly disabled in this mode (`"Cannot write to static config"`). You can **view** config, runtime/build info, logs, and cost models — but you can't edit anything through it. (Write/edit only works in *Standalone* mode, i.e. running the binary against a local config file outside Kubernetes.)

---

## Managing *all* gateways

| Goal | OSS path |
|------|----------|
| Manage all gateways/routes/policies | **Kubernetes API** — `kubectl` / GitOps over the CRDs (`Gateway`, `HTTPRoute`, traffic/AI policies). This is the real control surface and source of truth. |
| Inspect what one proxy actually received | The per-Gateway UI (port-forward to that Gateway) |
| Single pane of glass across all gateways | **Not in OSS** — Enterprise management plane / Solo UI |

In OSS the controller *programs* every Gateway but does not expose a UI for them. Treat the per-Gateway UI as a debugging/inspection dashboard, and manage the fleet declaratively via CRDs.

---

## Cleanup

Removing the Gateway deletes its proxy Deployment/Service (and the UI). It does **not** touch the control plane.

```bash
kubectl delete -f agw-ui-gateway.yaml
```

> Do not delete the control plane (controller) to "reset" things — that breaks the install. Reinstall via Helm instead.

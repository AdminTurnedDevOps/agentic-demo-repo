# Plugins Quickstart (Agent Registry Enterprise)

Lite guide: **create / list / use** a Plugin on Agent Registry Enterprise.

Targeted at the EE install on this cluster:

| | |
|--|--|
| Namespace | `agentregistry-system` |
| Chart / app | `agentregistry-enterprise` **v2026.7.1** |
| UI / API | `http://34.138.72.241:12121` (LoadBalancer) |
| Auth | Required (401 without a session/token) |

---

## What a Plugin is (and is not)

A **Plugin** is a first-class registry artifact (`kind: Plugin`, `apiVersion: ar.dev/v1alpha1`).

- **Is:** a **pinned pointer** to an external bundle (today: **git** URL + branch/commit; optional subfolder), plus metadata (title, description, harnesses such as `claude-code`).
- **Is not:** a Kubernetes Deployment you `kubectl apply` to run the plugin as a pod.
- The **Plugin controller** resolves the git ref to a concrete **commit**, scans the source for a plugin manifest/inventory, and records that in **status** (`Ready` when resolved).
- The registry **does not host plugin bytes**; harnesses materialize the pin at use/deploy time.

Phase-1 model (source pointer + resolve). OCI sources and full local author/publish flows may still be incomplete — prefer **git**.

---

## Prerequisites

1. EE Agent Registry running (you already have this).
2. Enterprise `arctl` for YAML apply (recommended on this build — see UI note below):

```bash
export VERSION=v2026.7.1 # or higher
curl -sSL https://storage.googleapis.com/agentregistry-enterprise/install.sh | ARCTL_VERSION=$VERSION sh
export PATH=$HOME/.arctl/bin:$PATH
arctl configure --url http://YOUR_ALB_IP:12121
# complete login if your CLI flow requires it
```

3. Optional: browser session to the UI for browsing the catalog (not required to *create* plugins on this build).

---

## Create a Plugin with YAML (`arctl apply`)

Write a manifest (example):

```yaml
apiVersion: ar.dev/v1alpha1
kind: Plugin
metadata:
  name: demo-formatter
  # tag is set by apply / catalog; use 1.0.0 or latest in CLI/UI as applicable
spec:
  title: Demo Formatter
  description: Sample plugin registered from a public git repo.
  harnesses:
    - claude-code
  source:
    type: git
    git:
      repository:
        url: https://github.com/solo-io/agentregistry-dev-samples
        branch: main
        # commit: <full-sha>     # preferred for reproducible tags
        # subfolder: plugins/foo # if the plugin lives in a monorepo path
```

Apply:

```bash
arctl apply -f plugin.yaml
# or: arctl apply -f plugin.yaml --url http://YOUR_ALB_IP:12121
```

List / get (after auth):

```bash
# REST (needs Authorization header from your login/token flow)
curl -sS -H "Authorization: Bearer $TOKEN" \
  "http://YOUR_ALB_IP:12121/v0/plugins?limit=50"

curl -sS -H "Authorization: Bearer $TOKEN" \
  "http://YOUR_ALB_IP:12121/v0/plugins/demo-formatter"
```

Unauthenticated `GET /v0/plugins` returns **401** on EE — expected.
---

## References

- Live EE OpenAPI: `http://YOUR_ALB_IP:12121/openapi.json` (Plugin paths under `/v0/plugins`)
- Enterprise UI create flow: `/are/catalog/plugins/create/`
- Model: Plugin = git/OCI **source pointer**; status holds resolved pin + manifest
- Sample git used in EE UI E2E: `https://github.com/solo-io/agentregistry-dev-samples`

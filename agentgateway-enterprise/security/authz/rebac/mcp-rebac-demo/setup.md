# MCP ReBAC Demo (Agentgateway Enterprise + OpenFGA)

What is ReBAC in a nutshell?

It enables rules to be conditional based on a relationship between the user and the object.

Example: Mike has `view` access on this. Not because he has a ‘viewer’ role, but because he’s a member of the engineering team, which has access to the project folder, which contains the document.

ReBAC also lets you natively solve for ABAC (attribute-based access control typically implemented with a policy enforcement in the mix) when attributes can be expressed in the form of relationships.

This prototype demonstrates relationship-based authorization for MCP `tools/list` and `tools/call` using:

- Solo for agentgatewayateway enterprise
- Enterprise uilt-in external auth (`traffic.extAuth`)
- OpenFGA as the authorization decision engine

## Prerequisites

- Kubernetes cluster with agentgateway enterprise installs
- `kubectl`, `curl`, `jq`, `python3`.


## ReBAC Server

For the purposes of this setup, we'll use OpenFGA.

It's an OSS authorization platform for relationship-based access control.

```
helm repo add openfga https://openfga.github.io/helm-charts

helm upgrade --install openfga openfga/openfga \
-n openfga \
--set service.type=LoadBalancer \
--create-namespace
```

## Automated run

1. Deploy infra and services:

```bash
export OPENFGA_URL=http://<openfga-lb-ip>:8080
./scripts/run-demo.sh
```

If a public LoadBalancer is not available, port-forward **OpenFGA** and set `OPENFGA_URL=http://localhost:8080` before running the script.

2. Configure MCP Gateway access for testing:

If your cluster provides a public Gateway endpoint (ALB/LB/IP/DNS), use it:

```bash
export GATEWAY_URL=http://<public-gateway-endpoint>:3000/mcp
```

If your cluster does not expose a public endpoint, port-forward the **Gateway** service and use localhost:

```bash
kubectl -n rebac-mcp-demo port-forward svc/mcp-rebac-gateway 3000:3000
export GATEWAY_URL=http://localhost:3000/mcp
```

3. Test Alice:

```bash
./scripts/test-alice.sh
```

4. Test Bob:

```bash
./scripts/test-bob.sh
```

## Manual Run

If you want to run manually OpenFGA bootstrap steps instead of `run-demo.sh`:

```bash
kubectl -n rebac-mcp-demo port-forward svc/openfga 8080:8080
./scripts/bootstrap-openfga.sh
./scripts/seed-demo-data.sh
./scripts/check-openfga.sh
```

## MCP Inspector

- URL: `http://localhost:3000/mcp`
- Auth header: `Authorization: Bearer <token>`
- Generate token:

```bash
./scripts/mint-jwt.sh alice finance
./scripts/mint-jwt.sh bob engineering
./scripts/mint-jwt.sh alice finance q1-forecast
```

## Expected results

- Alice:
  - can discover finance tools
  - cannot discover engineering tools
  - can invoke `create_forecast_ticket`
  - denied on `read_budget` without approver relationship
  - allowed on `read_budget` with contextual `approver_projects=q1-forecast`
- Bob:
  - can discover engineering tools
  - cannot discover finance tools
  - can invoke engineering tools
  - denied for finance tools


## What this proves

- JWT identity at gateway becomes OpenFGA subject (`user:<sub>`).
- Discovery is filtered with OpenFGA `ListObjects`.
- Invocation is enforced with OpenFGA `Check`.
- Non-trivial ReBAC beyond plain team RBAC:
  - `read_budget` requires relation to `project:q1-forecast` as `approver`.
  - `create_forecast_ticket` uses object-to-object relationship: `tool -> agent -> owner_team -> member`.

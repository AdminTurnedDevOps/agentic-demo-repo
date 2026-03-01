# Architecture

## Components

- Agentgateway Enterprise (`Gateway`, `HTTPRoute`, `AgentgatewayBackend`, `EnterpriseAgentgatewayPolicy`)
- OpenFGA (decision engine)
- Thin auth adapter (`/extauth` + `/mcp`)
- MCP servers:
  - `mcp-finance`
  - `mcp-engineering`

## Enforcement and decision split

- Enforcement point: Agentgateway Enterprise
  - JWT validation (`jwtAuthentication`)
  - External auth hook (`extAuth`) to adapter
  
- Decision engine: OpenFGA
  - `Check` for `tools/call`
  - `ListObjects` for `tools/list`

## Why adapter exists

The adapter is only a protocol bridge:

- Converts MCP + JWT request context into OpenFGA tuple checks
- Performs `ListObjects` and filters tool discovery output
- Keeps OpenFGA model/policy logic externalized and relationship-based

## Layout

- `openfga/`: model, tuples, tests (installation of OpenFGA is in this long-description.md)

  Your authorization data/config for OpenFGA:

  1. model.fga / model.json: the authorization model (types, relations, permissions)
  2. tuples.json: the relationship data to seed
  3. tests.fga.yaml: model test cases

  Bootstrap store + model (loads openfga/model.json):

  `./scripts/bootstrap-openfga.sh`

  Seed tuples (loads openfga/tuples.json):

  `./scripts/seed-demo-data.sh`

  Validate checks:

  `./scripts/check-openfga.sh`

- `k8s/`: manifests

All of the configurations (Gateway, HTTPRoute, policies, etc.) that will run on k8s

- `adapter/`: thin OpenFGA auth adapter

  What it does:

  1. Receives Gateway ext-auth checks at /extauth.
  2. Extracts JWT identity + MCP context (mainly tools/call tool name).
  3. Maps request to OpenFGA tuple form (user, relation, object).
  4. Calls OpenFGA Check/ListObjects.
  5. Returns allow/deny and filters tools/list results.

  Why it exists:

  - Agentgateway enforces auth, but OpenFGA is the decision engine.
  - The adapter translates gateway/MCP request shape into OpenFGA API calls.

- `mcp-finance/`, `mcp-engineering/`

MCP servers to test with (written with the FastMCP library)

- `scripts/`: bootstrap, seed, run, test

Everything you need to get this demo running from an automation perspective.

## Production-grade vs prototype-grade

This section is here to set expectations and boundaries.

It specifies:

1. What in this demo is intentionally simplified for speed (prototype-grade).
2. What would need to change for real production use (production-grade direction).

The goal is to prevent someone from mistaking demo shortcuts (for example, in-memory OpenFGA, runtime pip install, demo JWT secret) as best practices.

Prototype-grade:

- HS256 demo JWT secret in manifests
- in-memory OpenFGA datastore
- Python containers install dependencies at startup
- adapter doubles as MCP proxy and ext-auth hook

Production-grade direction:

- managed IdP/JWKS and asymmetric signing
- persistent OpenFGA datastore (Postgres)
- built adapter image with CI/CD and mTLS
- hardened retries/timeouts/observability
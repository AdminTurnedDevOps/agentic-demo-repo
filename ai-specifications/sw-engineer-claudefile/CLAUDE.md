# Global Instructions

## Role
You are a senior software engineering assistant with deep expertise in Kubernetes and AI/ML systems.

## Core Rules
- Never delete, overwrite, or alter existing files or resources without explicit user approval.
- Always ask before making destructive or irreversible changes.
- Do not hallucinate commands, flags, APIs, or configurations. If you are unsure, say so and look it up.

## Expertise Areas


- Repos should have clear setup instructions or automation (Makefile, Taskfile, scripts).

- Front matter must include: title, date, description, tags, and author.
- Code blocks must specify the language for syntax highlighting.
- Every tutorial must have a "Prerequisites" section listing exact tool versions and cluster requirements.
i# CLAUDE.md — Global Instructions

                                                                         This file provides guidance to Claude Code when working in any repository that does not have its own repo-si# CLAUDE.md — Global Instructions


## First Principles

### 1. Don't Break What Exists



### 2. Verify Everything — Never Assume Done

Every change must be tested or validated before declaring it complete. "It should work" is not an answer.

- **Helm charts:** Run `helm template` to verify rendered output. Lint with `helm lint`.
### 3. No Hallucination


- Cloud provider CLI commands (az, aws, gcloud) — flags vary by service and version
- MCP protocol fields and OAuth grant types — verify against the spec

### 4. Security by Default

When creating demos, configs, or infrastructure:

- Never commit `.env` files, kubeconfigs, or credential files.
- Default network policies should be deny-all with explicit allow-listing.

### 5. Reproducibility

- Docker Compose stacks should stand up with `docker compose up` from a clean clone.

## Tech Stack Conventions
- Error handling: wrap errors with `fmt.Errorf("context: %w", err)`. Don't discard errors silently.
- Linting: assume `golangci-lint` is the linter. Run it before considering code complete.
- Tests live next to the code they test (`foo_test.go` alongside `foo.go`).
- Pin dependencies in `requirements.txt` or `pyproject.toml` with exact versions.
- Type hints on all function signatures. Use `mypy` conventions.
- Tests in a `tests/` directory using `pytest`.


### Docker / Compose
- Health checks on every service that accepts connections.

## Content and Documentation
# CLAUDE.md — Global Instructions

This file provides guidance to Claude Code when working in any repository that does not have its own repo-s# CLAUDE.md — Global Instructions

This file provides guidance to Claude Code when working in any repository that does not have its own repo-specific `CLAUDE.md`. If a repo-level `CLAUDE.md` exists, it takes precedence over this file.

## First Principles

These are ordered by priority. When they conflict, the higher-numbered principle wins.

### 1. Don't Break What Exists

Never delete, overwrite, or alter existing files, resources, or infrastructure without explicit approval. This applies to code, manifests, Helm values, running clusters, cloud resources, and content drafts. If a change is destructive or irreversible, stop and ask first.

Default behavior is additive. Create new files, add new manifests, extend configs. If something needs to be replaced, show the diff and get confirmation.

### 2. Verify Everything — Never Assume Done

Every change must be tested or validated before declaring it complete. "It should work" is not an answer.

- **Code:** Run tests, linters, and build commands. If no test suite exists, confirm the code compiles/runs.
- **Kubernetes manifests:** Validate with `kubectl apply --dry-run=client` or equivalent. Confirm resources reach ready state when applied to a live cluster.
- **Helm charts:** Run `helm template` to verify rendered output. Lint with `helm lint`.
- **Docker/Compose:** Build the image. Run the container. Confirm the entrypoint works.
- **Scripts:** Execute them. Don't just write them and walk away.
- **Blog/content:** Check that links resolve, code blocks are syntactically correct, and front matter is valid.

### 3. No Hallucination

Do not invent commands, flags, API fields, CRD specs, or configuration options. If unsure whether a flag exists or an API field is valid, say so and look it up. This is especially critical for:

- `kubectl` and Helm flags — these change across versions
- CRD fields for kagent, agentgateway, kgateway, and Gloo Gateway — always verify against the actual CRD or docs
- Cloud provider CLI commands (az, aws, gcloud) — flags vary by service and version
- MCP protocol fields and OAuth grant types — verify against the spec

### 4. Security by Default

When creating demos, configs, or infrastructure:

- Never hardcode secrets, tokens, or credentials in manifests, code, or scripts. Use Kubernetes Secrets, environment variable references, or vault integrations.
- Never commit `.env` files, kubeconfigs, or credential files.
- Default network policies should be deny-all with explicit allow-listing.

### 5. Reproducibility

Everything must be reproducible from a clean state. A demo that only works on the author's machine is not a demo.

- Repos should have clear setup instructions or automation (Makefile, Taskfile, scripts).
- Kubernetes demos should specify: required cluster version, required CRDs/operators, namespace setup, and apply order.
- Docker Compose stacks should stand up with `docker compose up` from a clean clone.
@
> cat CLAUDE.md
# CLAUDE.md — Global Instructions

This file provides guidance to Claude Code when working in any repository that does not have its own repo-specific `CLAUDE.md`. If a repo-level `CLAUDE.md` exists, it takes precedence over this file.

## First Principles

These are ordered by priority. When they conflict, the higher-numbered principle wins.

### 1. Don't Break What Exists

Never delete, overwrite, or alter existing files, resources, or infrastructure without explicit approval. This applies to code, manifests, Helm values, running clusters, cloud resources, and content drafts. If a change is destructive or irreversible, stop and ask first.

Default behavior is additive. Create new files, add new manifests, extend configs. If something needs to be replaced, show the diff and get confirmation.

### 2. Verify Everything — Never Assume Done

Every change must be tested or validated before declaring it complete. "It should work" is not an answer.

- **Code:** Run tests, linters, and build commands. If no test suite exists, confirm the code compiles/runs.
- **Kubernetes manifests:** Validate with `kubectl apply --dry-run=client` or equivalent. Confirm resources reach ready state when applied to a live cluster.
- **Helm charts:** Run `helm template` to verify rendered output. Lint with `helm lint`.
- **Docker/Compose:** Build the image. Run the container. Confirm the entrypoint works.
- **Scripts:** Execute them. Don't just write them and walk away.
- **Blog/content:** Check that links resolve, code blocks are syntactically correct, and front matter is valid.

### 3. No Hallucination

Do not invent commands, flags, API fields, CRD specs, or configuration options. If unsure whether a flag exists or an API field is valid, say so and look it up. This is especially critical for:

- `kubectl` and Helm flags — these change across versions
- CRD fields for kagent, agentgateway, kgateway, and Gloo Gateway — always verify against the actual CRD or docs
- Cloud provider CLI commands (az, aws, gcloud) — flags vary by service and version
- MCP protocol fields and OAuth grant types — verify against the spec

### 4. Security by Default

When creating demos, configs, or infrastructure:

- Never hardcode secrets, tokens, or credentials in manifests, code, or scripts. Use Kubernetes Secrets, environment variable references, or vault integrations.
- Never commit `.env` files, kubeconfigs, or credential files.
- Default network policies should be deny-all with explicit allow-listing.

### 5. Reproducibility

Everything must be reproducible from a clean state. A demo that only works on the author's machine is not a demo.

- Repos should have clear setup instructions or automation (Makefile, Taskfile, scripts).
- Kubernetes demos should specify: required cluster version, required CRDs/operators, namespace setup, and apply order.
- Docker Compose stacks should stand up with `docker compose up` from a clean clone.
- Pin versions. Don't use `latest` tags in manifests or Dockerfiles. Don't use unpinned `go get` or `pip install` without version constraints.

## Tech Stack Conventions

### Go Projects

- Use Go modules. `go.mod` and `go.sum` are committed.
- Project layout follows the standard: `cmd/` for entrypoints, `internal/` or `pkg/` for library code, `api/` for protobuf/gRPC definitions if applicable.
- Error handling: wrap errors with `fmt.Errorf("context: %w", err)`. Don't discard errors silently.
- Linting: assume `golangci-lint` is the linter. Run it before considering code complete.
- Tests live next to the code they test (`foo_test.go` alongside `foo.go`).

### Python Projects

- Use virtual environments or containerized execution. Never `pip install` globally without `--break-system-packages` or a venv.
- Pin dependencies in `requirements.txt` or `pyproject.toml` with exact versions.
- Type hints on all function signatures. Use `mypy` conventions.
- Tests in a `tests/` directory using `pytest`.

### Kubernetes / Infrastructure

- **Manifests:** YAML files in a `manifests/`, `deploy/`, or `k8s/` directory. One resource per file unless tightly coupled resources belong together (e.g., Deployment + Service).
- **Helm:** Values files should be clearly named (`values-dev.yaml`, `values-prod.yaml`). Don't nest everything under a single key — keep values flat where possible.
- **Namespaces:** Each demo or project component gets its own namespace. Don't dump everything into `default`.
- **CRDs from the ecosystem:** When working with kagent, agentgateway, kgateway, Gloo Gateway, or Istio CRDs, always check the installed CRD version before writing manifests. Field names and API versions change between releases.

### Docker / Compose

- Multi-stage builds for Go and Python to keep images small.
- `docker-compose.yaml` (not `docker-compose.yml`) as the canonical filename.
- Service names in Compose should be descriptive: `keycloak`, `agentgateway`, `otel-collector` — not `service1`, `app`.
- Health checks on every service that accepts connections.

## Content and Documentation


### README Files

- Every repo must have a README with: one-paragraph description, architecture diagram (if applicable), prerequisites, quickstart, and project structure overview.
- Architecture diagrams in SVG or PNG, committed to the repo. Excalidraw source files (`.excalidraw`) committed alongside exports for future editing.
- Don't write a wall of text. Use sections with clear headings. A reader should be able to get the project running in under 5 minutes from the README alone.

### Diagrams

- Excalidraw is the primary diagramming tool. Commit both `.excalidraw` source and `.svg`/`.png` exports.
- For simple flow diagrams in markdown, Mermaid is acceptable.
- Diagrams should have a title, clear labels on every box/arrow, and a brief caption or surrounding text explaining what the reader is looking at.

## Working Patterns

### Before Writing Code

1. **Understand the repo structure.** Run `ls`, read the README, check for a Makefile or Taskfile.
2. **Check for existing patterns.** If there are existing manifests, tests, or modules, follow their style. Don't introduce a new convention without discussing it.
3. **Identify the build/test cycle.** Find out how to build, test, and run before making changes. If it's not documented, that's the first thing to fix.

### When Creating Demos

- Each demo should be self-contained in its own directory or repo.
- Include a `Makefile` or `Taskfile.yml` with common targets: `setup`, `deploy`, `test`, `clean`.
- Always include a teardown/cleanup path. If a demo creates cloud resources, namespaces, or CRDs, there must be a `make clean` or equivalent that removes them.
- Test the demo from a clean state before considering it done. Clone the repo fresh, follow the README, confirm it works.

### When Debugging

- Start with logs and events: `kubectl logs`, `kubectl describe`, `kubectl get events`.
- Check resource status and conditions before diving into code.
- For agentgateway/kgateway issues: check the gateway pod logs, confirm listener/route status, verify upstream connectivity.
- For OAuth/OIDC issues: inspect the token (jwt.io or `jq` decode), verify issuer/audience/scope claims, check the IdP configuration (Keycloak realm, Entra app registration, Auth0 application).
- Don't guess. Collect evidence first, form a hypothesis, then test it.

## Things to Never Do

- Never use `kubectl delete` on production namespaces or CRDs without explicit confirmation.
- Never run `helm upgrade` or `helm install` with `--force` unless asked.
- Never store secrets in git, environment variables in committed files, or tokens in code comments.
- Never use `sleep` as a synchronization mechanism in scripts. Wait for actual conditions (`kubectl wait`, health check polling, readiness probes).
- Never ignore a failing test. If a test fails, investigate. If it's a known flake, document it. Don't skip it silently.
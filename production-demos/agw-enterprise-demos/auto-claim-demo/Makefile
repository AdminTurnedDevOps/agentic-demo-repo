SHELL := /bin/bash
NS := auto-claims
ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
MCP_TAG ?= 0.1.2
GEN := $(ROOT).generated/manifests

.PHONY: help preflight image enable-sts secrets personas render deploy validate demo reset status clean disable-sts

help:
	@echo "One-time:  make preflight image render enable-sts"
	@echo "Setup:     make secrets personas render deploy validate"
	@echo "Record:    ./demo.sh            (./demo.sh 4 to start at scene 4)"
	@echo "Between:   make reset           (or ./demo.sh reset)"
	@echo "Teardown:  make clean           (namespace only; STS stays: make disable-sts)"

preflight:
	$(ROOT)scripts/preflight.sh

image:
	MCP_TAG=$(MCP_TAG) $(ROOT)scripts/build-image.sh

# Changes the shared enterprise-agentgateway release; shows a diff and asks first.
enable-sts:
	$(ROOT)scripts/enable-sts.sh

secrets:
	kubectl apply -f $(ROOT)manifests/00-namespace.yaml
	$(ROOT)scripts/secrets.sh

personas:
	$(ROOT)scripts/personas.sh

render:
	MCP_TAG=$(MCP_TAG) $(ROOT)scripts/render.sh

# Platform only: everything the audience does not need to watch being built.
# Scene policies (identity, tool registry, guardrails, cost) are applied live by demo.sh.
deploy:
	kubectl apply --dry-run=server -f $(ROOT)manifests/00-namespace.yaml -f $(GEN)/10-claims-mcp.yaml -f $(ROOT)manifests/20-gateway.yaml \
	  -f $(ROOT)manifests/30-mcp-route.yaml -f $(GEN)/31-llm-route.yaml -f $(ROOT)manifests/32-a2a-route.yaml \
	  -f $(ROOT)manifests/40-agent.yaml -f $(ROOT)manifests/policies/50-audit.yaml >/dev/null
	kubectl apply -f $(ROOT)manifests/00-namespace.yaml -f $(GEN)/10-claims-mcp.yaml -f $(ROOT)manifests/20-gateway.yaml \
	  -f $(ROOT)manifests/30-mcp-route.yaml -f $(GEN)/31-llm-route.yaml -f $(ROOT)manifests/32-a2a-route.yaml \
	  -f $(ROOT)manifests/40-agent.yaml -f $(ROOT)manifests/policies/50-audit.yaml
	kubectl -n $(NS) wait --for=condition=Programmed gateway/claims-gateway --timeout=180s
	kubectl -n $(NS) wait --for=condition=Ready mcpserver/claims-mcp --timeout=180s
	kubectl -n $(NS) wait --for=condition=Accepted enterpriseagentgatewaybackend/claims-mcp enterpriseagentgatewaybackend/claims-llm enterpriseagentgatewaybackend/claims-agent-a2a --timeout=120s
	kubectl -n $(NS) wait --for=condition=Ready agent/claims-agent --timeout=300s

validate:
	$(ROOT)scripts/validate.sh

demo:
	$(ROOT)demo.sh

reset:
	$(ROOT)demo.sh reset

status:
	$(ROOT)demo.sh status

clean:
	kubectl delete namespace $(NS) --ignore-not-found --wait=true
	@echo "Namespace $(NS) removed. The STS is still enabled on the shared release: make disable-sts"

# Turns the STS back off on the shared release (asks first).
disable-sts:
	@read -r -p "Run helm upgrade --reuse-values --set tokenExchange.enabled=false on agentgateway-system/agentgateway? Type 'yes': " a; \
	  [[ "$$a" == "yes" ]] || { echo "aborted"; exit 1; }
	helm upgrade agentgateway oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway \
	  --version $$(helm -n agentgateway-system list -f '^agentgateway$$' -o json | jq -r '.[0].chart' | sed 's/^enterprise-agentgateway-//') \
	  -n agentgateway-system --reuse-values --set tokenExchange.enabled=false
	kubectl -n agentgateway-system rollout status deploy/enterprise-agentgateway --timeout=180s

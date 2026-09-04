SHELL := /bin/bash
NS := dealeriq
REGISTRY ?= northamerica-northeast1-docker.pkg.dev/field-engineering-us/mlevan-images
TAG ?= 0.1.1
MCP_IMAGE := $(REGISTRY)/dealeriq-mcp:$(TAG)
BYO_IMAGE := $(REGISTRY)/dealeriq-byo:$(TAG)
ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

copy-secret = kubectl get secret $(2) -n $(3) >/dev/null 2>&1 || \
	kubectl get secret $(2) -n $(1) -o json \
	| python3 -c 'import json,sys; d=json.load(sys.stdin); m=d["metadata"]; d["metadata"]={"name":m["name"],"namespace":"$(3)", "labels":{"app.kubernetes.io/part-of":"dealeriq"}}; d.pop("status", None); print(json.dumps(d))' \
	| kubectl apply -f -

.PHONY: setup deploy seed demo-reset clean images validate

setup: images
	kubectl apply --dry-run=client -f $(ROOT)mcp/manifests/namespace.yaml >/dev/null
	kubectl apply -f $(ROOT)mcp/manifests/namespace.yaml
	$(call copy-secret,agentgateway-system,anthropic-secret,$(NS))
	$(call copy-secret,kagent,kagent-anthropic,$(NS))
	$(call copy-secret,kagent,regcred,$(NS))
	kubectl apply --dry-run=client -f $(ROOT)mcp/manifests/configmap.yaml >/dev/null
	kubectl apply -f $(ROOT)mcp/manifests/configmap.yaml

images:
	gcloud builds submit $(ROOT)mcp --project=field-engineering-us --tag $(MCP_IMAGE)
	gcloud builds submit $(ROOT)agents/byo --project=field-engineering-us --tag $(BYO_IMAGE)

deploy:
	kubectl apply --dry-run=client -f $(ROOT)mcp/manifests/mcpserver.yaml >/dev/null
	kubectl apply -f $(ROOT)mcp/manifests/mcpserver.yaml
	kubectl apply --dry-run=client -f $(ROOT)gateway/mock-llm.yaml >/dev/null
	kubectl apply -f $(ROOT)gateway/mock-llm.yaml
	kubectl apply --dry-run=client -f $(ROOT)gateway/llm-route/gateway.yaml >/dev/null
	kubectl apply -f $(ROOT)gateway/llm-route/gateway.yaml
	kubectl apply --dry-run=client -f $(ROOT)gateway/tracing.yaml >/dev/null
	kubectl apply -f $(ROOT)gateway/tracing.yaml
	kubectl apply --dry-run=client -f $(ROOT)agents/declarative >/dev/null
	kubectl apply -f $(ROOT)agents/declarative
	kubectl apply --dry-run=client -f $(ROOT)agents/byo/agent.yaml >/dev/null
	kubectl apply -f $(ROOT)agents/byo/agent.yaml
	kubectl apply --dry-run=client -f $(ROOT)policies/00-deny-all.yaml -f $(ROOT)policies/10-reader.yaml >/dev/null
	kubectl apply -f $(ROOT)policies/00-deny-all.yaml -f $(ROOT)policies/10-reader.yaml
	kubectl delete accesspolicy dealeriq-writer-tools -n $(NS) --ignore-not-found
	kubectl delete accesspolicy dealeriq-reader-update-lead-status -n $(NS) --ignore-not-found
	@echo "Waiting for MCPServer and Agents..."
	kubectl wait --for=condition=Accepted enterpriseagentgatewaybackend/dealeriq-claude -n $(NS) --timeout=60s
	kubectl wait --for=condition=Accepted enterpriseagentgatewaybackend/dealeriq-mock-llm -n $(NS) --timeout=60s
	kubectl wait --for=jsonpath='{.status.ancestors[0].conditions[?(@.type=="Attached")].status}'=True enterpriseagentgatewaypolicy/dealeriq-llm-tracing -n $(NS) --timeout=60s
	kubectl rollout status deploy/dealeriq-mock-llm -n $(NS) --timeout=180s
	kubectl rollout status deploy/dealeriq-mock-llm-ok -n $(NS) --timeout=180s
	kubectl wait --for=condition=Ready mcpserver/dealer-leads-mcp -n $(NS) --timeout=180s
	kubectl wait --for=condition=Ready agent/dealer-assistant -n $(NS) --timeout=180s
	kubectl wait --for=condition=Ready agent/dealer-assistant-byo -n $(NS) --timeout=300s

seed:
	kubectl apply -f $(ROOT)mcp/manifests/configmap.yaml
	kubectl rollout restart deploy/dealer-leads-mcp -n $(NS) || true
	kubectl rollout status deploy/dealer-leads-mcp -n $(NS) --timeout=180s || true

demo-reset:
	kubectl delete accesspolicy dealeriq-reader-update-lead-status -n $(NS) --ignore-not-found
	kubectl delete accesspolicy dealeriq-writer-tools -n $(NS) --ignore-not-found
	kubectl apply -f $(ROOT)policies/00-deny-all.yaml -f $(ROOT)policies/10-reader.yaml
	kubectl delete enterpriseagentgatewaybudget dealeriq-daily-token-budget -n $(NS) --ignore-not-found
	kubectl delete enterpriseagentgatewaypolicy dealeriq-budget-enforcement dealeriq-llm-rate-limit dealeriq-mock-llm-circuit-breaker -n $(NS) --ignore-not-found
	$(ROOT)scripts/reset-budget-counter.sh
	$(MAKE) seed
	NS=$(NS) $(ROOT)scripts/clear-sessions.sh
	@echo "demo-reset complete"

validate:
	$(ROOT)scripts/validate.sh

clean:
	kubectl delete namespace $(NS) --ignore-not-found --wait=true
	@echo "dealeriq namespace removed; no other namespaces were touched"

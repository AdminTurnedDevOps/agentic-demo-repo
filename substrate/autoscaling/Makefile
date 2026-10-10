# Burst Without 503s lab: automation for the README steps.
#
# Required env for deploy: ATEOM_IMAGE, COUNTER_IMAGE, BUCKET_NAME (see README Environment and Step 1).
# The README walks the same steps by hand; the scenarios themselves are run with
# scripts/burst.sh and scripts/router-parking.sh.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c

ATESPACE  := ate-lab-burst
NAMESPACE := ate-lab-burst
MON_NS    := ate-lab-burst-monitoring
ACTORS    := a1 a2 a3 a4 a5 a6

.PHONY: help check-env deploy actors suspend-all monitoring hpa clean lint

help:
	@echo "targets: deploy actors suspend-all monitoring hpa clean lint"

check-env:
	@for v in ATEOM_IMAGE COUNTER_IMAGE BUCKET_NAME; do \
	  if [[ -z "$${!v:-}" ]]; then echo "missing env: $$v (see README Environment and Step 1)" >&2; exit 1; fi; \
	done

## Pool, atespace, template; waits for the golden snapshot (README Step 2).
deploy: check-env
	envsubst '$${ATEOM_IMAGE}' < manifests/workerpool.yaml.tmpl | kubectl apply -f -
	kubectl -n $(NAMESPACE) rollout status deployment/burst --timeout=10m
	kubectl ate get atespace $(ATESPACE) >/dev/null 2>&1 || kubectl ate create atespace $(ATESPACE)
	kubectl ate get actor-template burst -a $(ATESPACE) >/dev/null 2>&1 || \
	  envsubst '$${COUNTER_IMAGE} $${BUCKET_NAME}' < manifests/actortemplate.yaml.tmpl \
	    | kubectl ate create actor-template -f -
	@echo "waiting for golden snapshot (up to 15m)"
	@for i in $$(seq 1 180); do \
	  out=$$(kubectl ate get actor-template burst -a $(ATESPACE) -o yaml); \
	  if grep -q 'errorMessage:' <<<"$$out"; then echo "$$out"; exit 1; fi; \
	  if grep -q 'goldenTag:' <<<"$$out"; then echo "golden snapshot ready"; exit 0; fi; \
	  sleep 5; \
	done; echo "timed out waiting for golden snapshot" >&2; exit 1

## Six actors on a two-worker pool (README Step 3).
actors:
	@for a in $(ACTORS); do \
	  kubectl ate get actor $$a -a $(ATESPACE) >/dev/null 2>&1 || \
	    kubectl ate create actor $$a -a $(ATESPACE) --template burst; \
	done
	kubectl ate get actors -a $(ATESPACE)

suspend-all:
	@for a in $(ACTORS); do kubectl ate suspend actor $$a -a $(ATESPACE) >/dev/null 2>&1 || true; done
	kubectl ate get actors -a $(ATESPACE)

## Prometheus + prometheus-adapter (README Step 4). Refuses to take over an
## existing external-metrics APIService that this lab did not create.
monitoring:
	@if kubectl get apiservice v1beta1.external.metrics.k8s.io >/dev/null 2>&1; then \
	  owner=$$(kubectl get apiservice v1beta1.external.metrics.k8s.io -o jsonpath='{.spec.service.namespace}'); \
	  if [[ "$$owner" != "$(MON_NS)" ]]; then \
	    echo "external.metrics.k8s.io is served from namespace '$$owner'; refusing to replace it (see README Prerequisites)" >&2; exit 1; \
	  fi; \
	fi
	kubectl apply -f manifests/prometheus.yaml
	kubectl -n $(MON_NS) rollout status deployment/prometheus --timeout=5m
	kubectl apply -f manifests/prometheus-adapter.yaml
	kubectl -n $(MON_NS) rollout status deployment/prometheus-adapter --timeout=5m
	kubectl wait --for=condition=Available apiservice/v1beta1.external.metrics.k8s.io --timeout=5m

## External-metric HPA on the WorkerPool (README "The HPA adds capacity").
hpa:
	kubectl apply -f manifests/hpa.yaml
	kubectl -n $(NAMESPACE) get hpa burst

## Tear down everything the lab created, except snapshot objects in GCS.
clean:
	-kubectl delete -f manifests/hpa.yaml --ignore-not-found
	-./scripts/router-parking.sh default
	-@for a in $(ACTORS); do kubectl ate delete actor $$a -a $(ATESPACE) --any-state; done
	-kubectl ate delete actor-template burst -a $(ATESPACE)
	-kubectl ate delete atespace $(ATESPACE)
	-kubectl delete -f manifests/prometheus-adapter.yaml --ignore-not-found
	-kubectl delete -f manifests/prometheus.yaml --ignore-not-found
	-kubectl delete namespace $(NAMESPACE) --ignore-not-found

## Offline checks: script syntax, shellcheck and yq (each skipped if not installed).
lint:
	bash -n scripts/burst.sh
	bash -n scripts/router-parking.sh
	@if command -v shellcheck >/dev/null; then shellcheck scripts/*.sh && echo "ok  shellcheck"; else echo "shellcheck not installed; skipped"; fi
	@if command -v yq >/dev/null; then \
	  for f in manifests/*.yaml manifests/*.tmpl; do yq eval-all '.' "$$f" >/dev/null && echo "ok  $$f"; done; \
	else echo "yq not installed; YAML parse skipped"; fi

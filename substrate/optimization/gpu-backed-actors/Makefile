SHELL := /bin/bash

DEMO_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
SUBSTRATE_DIR ?= $(abspath $(DEMO_DIR)/../../../../substrate)
BUILD_DIR := $(DEMO_DIR)/.build

NAMESPACE ?= ate-demo-gpu
WORKERPOOL ?= gpu-workers
TEMPLATE ?= gpu-context-release
ATESPACE ?= gpu-demo
ACTOR ?= gpu-1
GPU_ACCELERATOR ?= nvidia-tesla-t4
GPU_WORKLOAD_IMAGE_REPO ?= $(KO_DOCKER_REPO)/gpu-actor-workload
SNAPSHOT_LOCATION ?=
GPU_WORKLOAD_IMAGE ?=
ATEOM_GPU_IMAGE ?=

WORKLOAD_METADATA := $(BUILD_DIR)/workload-metadata.json
WORKLOAD_IMAGE_FILE := $(BUILD_DIR)/workload-image
ATEOM_IMAGE_FILE := $(BUILD_DIR)/ateom-gpu-image
GOLDEN_ACTOR_FILE := $(BUILD_DIR)/golden-actor-id
ATESPACE_MARKER_FILE := $(BUILD_DIR)/atespace-created
WORKERPOOL_MANIFEST := $(BUILD_DIR)/workerpool.yaml
ACTORTEMPLATE_MANIFEST := $(BUILD_DIR)/actortemplate.yaml

.DEFAULT_GOAL := help

.PHONY: help check-render-tools check-registry images build-workload build-ateom render setup deploy test clean

help:
	@printf '%s\n' \
	  'make images  - build and push the CUDA workload and glibc ateom images' \
	  'make render  - render manifests into .build and parse-check the YAML' \
	  'make setup   - build images and render manifests' \
	  'make deploy  - apply the GPU WorkerPool, then the ActorTemplate' \
	  'make test    - cold boot CUDA, suspend, restore, and suspend again' \
	  'make clean   - remove this demo actor, atespace, and Kubernetes resources'

check-render-tools:
	@command -v envsubst >/dev/null
	@command -v ruby >/dev/null

check-registry:
	@test -n "$(KO_DOCKER_REPO)" || { printf 'KO_DOCKER_REPO is required\n' >&2; exit 1; }

$(BUILD_DIR):
	@mkdir -p "$@"

build-workload: check-registry | $(BUILD_DIR)
	@command -v docker >/dev/null
	@command -v jq >/dev/null
	docker buildx build \
	  --platform linux/amd64 \
	  --push \
	  --provenance=false \
	  --metadata-file "$(WORKLOAD_METADATA)" \
	  --tag "$(GPU_WORKLOAD_IMAGE_REPO):cuda-12.8.1" \
	  "$(DEMO_DIR)/workload"
	@digest="$$(jq -er '."containerimage.digest"' "$(WORKLOAD_METADATA)")"; \
	  printf '%s@%s\n' "$(GPU_WORKLOAD_IMAGE_REPO)" "$$digest" > "$(WORKLOAD_IMAGE_FILE)"
	@printf 'GPU workload image: %s\n' "$$(cat "$(WORKLOAD_IMAGE_FILE)")"

build-ateom: check-registry | $(BUILD_DIR)
	@test -x "$(SUBSTRATE_DIR)/hack/run-tool.sh" || { printf 'SUBSTRATE_DIR is not a Substrate checkout: %s\n' "$(SUBSTRATE_DIR)" >&2; exit 1; }
	@image="$$(cd "$(SUBSTRATE_DIR)" && \
	  KO_DOCKER_REPO="$(KO_DOCKER_REPO)" \
	  KO_DEFAULTPLATFORMS=linux/amd64 \
	  KO_DEFAULTBASEIMAGE='debian@sha256:1710bde34461551a19a47c787885ec9ad7058d9a5bead2affb8d088fa2f8502b' \
	  ./hack/run-tool.sh ko build ./cmd/ateom-gvisor)"; \
	  test -n "$$image"; \
	  printf '%s\n' "$$image" > "$(ATEOM_IMAGE_FILE)"
	@printf 'GPU ateom image: %s\n' "$$(cat "$(ATEOM_IMAGE_FILE)")"

images: build-workload build-ateom

render: check-render-tools | $(BUILD_DIR)
	@workload_image="$(GPU_WORKLOAD_IMAGE)"; \
	  if test -z "$$workload_image" && test -s "$(WORKLOAD_IMAGE_FILE)"; then workload_image="$$(cat "$(WORKLOAD_IMAGE_FILE)")"; fi; \
	  test -n "$$workload_image" || { printf 'Run make build-workload or set GPU_WORKLOAD_IMAGE\n' >&2; exit 1; }; \
	  ateom_image="$(ATEOM_GPU_IMAGE)"; \
	  if test -z "$$ateom_image" && test -s "$(ATEOM_IMAGE_FILE)"; then ateom_image="$$(cat "$(ATEOM_IMAGE_FILE)")"; fi; \
	  test -n "$$ateom_image" || { printf 'Run make build-ateom or set ATEOM_GPU_IMAGE\n' >&2; exit 1; }; \
	  snapshot_location="$(SNAPSHOT_LOCATION)"; \
	  if test -z "$$snapshot_location"; then \
	    test -n "$(BUCKET_NAME)" || { printf 'Set BUCKET_NAME or SNAPSHOT_LOCATION\n' >&2; exit 1; }; \
	    snapshot_location="gs://$(BUCKET_NAME)/ate-demo-gpu/"; \
	  fi; \
	  export NAMESPACE="$(NAMESPACE)" \
	  WORKERPOOL="$(WORKERPOOL)" \
	  GPU_ACCELERATOR="$(GPU_ACCELERATOR)" \
	  ATEOM_GPU_IMAGE="$$ateom_image"; \
	  envsubst '$${NAMESPACE} $${WORKERPOOL} $${GPU_ACCELERATOR} $${ATEOM_GPU_IMAGE}' \
	    < "$(DEMO_DIR)/manifests/workerpool.yaml.tmpl" \
	    > "$(WORKERPOOL_MANIFEST)"; \
	  export NAMESPACE="$(NAMESPACE)" \
	  TEMPLATE="$(TEMPLATE)" \
	  GPU_WORKLOAD_IMAGE="$$workload_image" \
	  SNAPSHOT_LOCATION="$$snapshot_location"; \
	  envsubst '$${NAMESPACE} $${TEMPLATE} $${GPU_WORKLOAD_IMAGE} $${SNAPSHOT_LOCATION}' \
	    < "$(DEMO_DIR)/manifests/actortemplate.yaml.tmpl" \
	    > "$(ACTORTEMPLATE_MANIFEST)"
	@ruby -e 'require "yaml"; ARGV.each { |f| YAML.load_stream(File.read(f)); puts "valid YAML: #{f}" }' \
	  "$(WORKERPOOL_MANIFEST)" "$(ACTORTEMPLATE_MANIFEST)"
	@! grep -q '$${' "$(WORKERPOOL_MANIFEST)" "$(ACTORTEMPLATE_MANIFEST)"

setup: images render

deploy: render
	@command -v kubectl >/dev/null
	@if kubectl get namespace "$(NAMESPACE)" >/dev/null 2>&1; then \
	  owner="$$(kubectl get namespace "$(NAMESPACE)" -o jsonpath='{.metadata.labels.gpu-backed-actors-demo}')"; \
	  test "$$owner" = true || { printf 'Refusing to use existing namespace %s without gpu-backed-actors-demo=true\n' "$(NAMESPACE)" >&2; exit 1; }; \
	fi
	kubectl apply -f "$(WORKERPOOL_MANIFEST)"
	kubectl -n "$(NAMESPACE)" wait --for=create deployment/"$(WORKERPOOL)" --timeout=2m
	kubectl -n "$(NAMESPACE)" rollout status deployment/"$(WORKERPOOL)" --timeout=10m
	kubectl apply -f "$(ACTORTEMPLATE_MANIFEST)"
	kubectl -n "$(NAMESPACE)" wait \
	  --for=condition=Ready actortemplate/"$(TEMPLATE)" --timeout=15m

test:
	@set -Eeuo pipefail; \
	  if kubectl ate get atespace "$(ATESPACE)" >/dev/null 2>&1; then \
	    printf 'Atespace %s already exists; use a different ATESPACE\n' "$(ATESPACE)" >&2; \
	    exit 1; \
	  fi; \
	  cleanup_on_error() { \
	    kubectl ate delete actor "$(ACTOR)" --atespace "$(ATESPACE)" --any-state >/dev/null 2>&1 || true; \
	    if kubectl ate delete atespace "$(ATESPACE)" >/dev/null 2>&1; then rm -f "$(ATESPACE_MARKER_FILE)"; fi; \
	  }; \
	  trap cleanup_on_error ERR; \
	  kubectl ate create atespace "$(ATESPACE)"; \
	  printf '%s\n' "$(ATESPACE)" > "$(ATESPACE_MARKER_FILE)"; \
	  kubectl ate create actor "$(ACTOR)" --atespace "$(ATESPACE)" --template "$(NAMESPACE)/$(TEMPLATE)"; \
	  kubectl ate resume actor "$(ACTOR)" --atespace "$(ATESPACE)" --boot; \
	  kubectl ate logs actors "$(ACTOR)" --atespace "$(ATESPACE)" | grep 'GPU_PROBE_OK'; \
	  kubectl ate suspend actor "$(ACTOR)" --atespace "$(ATESPACE)"; \
	  kubectl ate resume actor "$(ACTOR)" --atespace "$(ATESPACE)"; \
	  kubectl ate get actor "$(ACTOR)" --atespace "$(ATESPACE)"; \
	  kubectl ate suspend actor "$(ACTOR)" --atespace "$(ATESPACE)"; \
	  trap - ERR

clean:
	@if ! kubectl get namespace "$(NAMESPACE)" >/dev/null 2>&1; then \
	  printf 'Refusing automatic cleanup because namespace %s does not exist\n' "$(NAMESPACE)" >&2; \
	  exit 1; \
	fi
	@owner="$$(kubectl get namespace "$(NAMESPACE)" -o jsonpath='{.metadata.labels.gpu-backed-actors-demo}')"; \
	  test "$$owner" = true || { printf 'Refusing cleanup because namespace %s is not marked as demo-owned\n' "$(NAMESPACE)" >&2; exit 1; }
	@if test -e "$(ATESPACE_MARKER_FILE)" && { ! test -s "$(ATESPACE_MARKER_FILE)" || ! test "$$(cat "$(ATESPACE_MARKER_FILE)")" = "$(ATESPACE)"; }; then \
	  printf 'Refusing global actor cleanup because the Atespace ownership marker is invalid\n' >&2; \
	  exit 1; \
	elif test -s "$(ATESPACE_MARKER_FILE)"; then \
	  if kubectl ate get actor "$(ACTOR)" --atespace "$(ATESPACE)" >/dev/null 2>&1; then \
	    kubectl ate delete actor "$(ACTOR)" --atespace "$(ATESPACE)" --any-state; \
	  elif ! kubectl ate get atespace "$(ATESPACE)" >/dev/null 2>&1; then \
	    printf 'Cannot verify actor state because the Substrate control plane is unavailable\n' >&2; \
	    exit 1; \
	  fi; \
	else \
	  printf 'No demo-owned Atespace marker; skipping global actor cleanup\n'; \
	fi
	@set -e; \
	  golden_actor=""; \
	  if test -s "$(GOLDEN_ACTOR_FILE)"; then \
	    golden_actor="$$(cat "$(GOLDEN_ACTOR_FILE)")"; \
	  else \
	    if golden_actor="$$(kubectl get actortemplate "$(TEMPLATE)" -n "$(NAMESPACE)" -o jsonpath='{.status.goldenActorID}' 2>/dev/null)"; then \
	      :; \
	    elif kubectl get namespace "$(NAMESPACE)" >/dev/null 2>&1; then \
	      golden_actor=""; \
	    else \
	      printf 'Cannot verify ActorTemplate state because the Kubernetes API is unavailable\n' >&2; \
	      exit 1; \
	    fi; \
	    if test -n "$$golden_actor"; then printf '%s\n' "$$golden_actor" > "$(GOLDEN_ACTOR_FILE)"; fi; \
	  fi; \
	  kubectl delete actortemplate "$(TEMPLATE)" -n "$(NAMESPACE)" --ignore-not-found; \
	  if test -n "$$golden_actor"; then \
	    if kubectl ate get actor "$$golden_actor" --atespace ate-golden >/dev/null 2>&1; then \
	      kubectl ate delete actor "$$golden_actor" --atespace ate-golden --any-state; \
	    elif ! kubectl ate get atespace ate-golden >/dev/null 2>&1; then \
	      printf 'Cannot verify golden actor state because the Substrate control plane is unavailable\n' >&2; \
	      exit 1; \
	    fi; \
	  fi; \
	  rm -f "$(GOLDEN_ACTOR_FILE)"
	@kubectl delete workerpool "$(WORKERPOOL)" -n "$(NAMESPACE)" --ignore-not-found
	@if test -s "$(ATESPACE_MARKER_FILE)"; then kubectl ate delete atespace "$(ATESPACE)"; fi
	@kubectl delete namespace "$(NAMESPACE)"
	@rm -f "$(ATESPACE_MARKER_FILE)"

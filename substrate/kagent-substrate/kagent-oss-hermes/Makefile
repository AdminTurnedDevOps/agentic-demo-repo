IMAGE ?= northamerica-northeast1-docker.pkg.dev/field-engineering-us/mlevan-images/kagent-hermes
TAG ?= 0.1.0
PLATFORM ?= linux/amd64

.PHONY: lock
lock:
	uv pip compile requirements.in --generate-hashes --output-file requirements.lock

.PHONY: test
test:
	go test ./...
	go vet ./...

.PHONY: build
build: test
	docker buildx build --platform $(PLATFORM) --load --build-arg VERSION=$(TAG) -t $(IMAGE):$(TAG) .

.PHONY: push
push: test
	docker buildx build --platform $(PLATFORM) --push --build-arg VERSION=$(TAG) -t $(IMAGE):$(TAG) .

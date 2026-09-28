NAMESPACE := openfga-actors
CHART_VERSION := 0.3.15

.PHONY: setup build deploy test clean

# Run only on the cluster selected by your current kubectl context.
setup:
	kubectl apply -f namespace.yaml
	kubectl -n $(NAMESPACE) rollout status deployment/openfga

# Supply IMAGE as a pullable registry reference. Never use an unpushed local image.
build:
	: "$${IMAGE:?Set IMAGE to a pullable registry reference}"
	docker buildx build --platform linux/amd64,linux/arm64 --push -t "$(IMAGE)" adapter

deploy:
	: "$${IMAGE:?Set IMAGE to a pullable registry reference}"
	python3 deploy.py --image "$(IMAGE)"
	kubectl apply -f gateway.yaml
	kubectl -n $(NAMESPACE) rollout status deployment/openfga-actors-auth
	kubectl -n $(NAMESPACE) rollout status deployment/openfga-actors-gateway

# Local unit tests; integration_test.py separately tests the live OpenFGA model.
test:
	docker build -t openfga-actors-auth:test adapter
	docker run --rm openfga-actors-auth:test python -m unittest -v test_server

# Removes this lab's resources and the disposable in-memory FGA store.
clean:
	kubectl delete -f gateway.yaml --ignore-not-found
	kubectl delete -f auth.yaml --ignore-not-found
	kubectl delete -f namespace.yaml --ignore-not-found

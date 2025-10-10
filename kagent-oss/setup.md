# Installation

Below you will find the installation of kagent for both Anthropic and OpenAI as your first Model used (you can add more after installation)

## CRDs

```
helm install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
    --namespace kagent \
    --create-namespace
```

## With Anthropic
```
export ANTHROPIC_API_KEY=your_api_key
```

```
helm upgrade --install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
    --namespace kagent \
    --set providers.default=anthropic \
    --set providers.anthropic.apiKey=$ANTHROPIC_API_KEY

```

## Dashboard Setup

```
kubectl port-forward svc/kagent-ui -n kagent 8080:8080
```
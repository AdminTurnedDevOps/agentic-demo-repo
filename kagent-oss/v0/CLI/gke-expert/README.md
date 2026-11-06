# gke-expert Agent

This is a gke-expert agent that can be used to test KAgent BYO agent with ADK.

## Model Configuration

This agent is configured to use the **anthropic** provider with model **claude-sonnet-4-5**.

## Usage

1. Build the agent image and push it to the local registry using the KAgent CLI

```bash
kagent build gke-expert
```

2. Deploy the agent

```bash
kagent deploy gke-expert --api-key <api-key>
```

Or create a secret with the api key

```bash
kubectl create secret generic my-secret -n <namespace> --from-literal=<PROVIDER>_API_KEY=$API_KEY --dry-run=client -oyaml | k apply -f -
```

And then deploy the agent

```bash
kagent deploy gke-expert --api-key-secret "my-secret"
```
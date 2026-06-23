The ate-system substrate control plane (CRDs, ate-api-server, atenet-router, at least one WorkerPool, etc.) must be installed and healthy before you enable the integration on the kagent side.

The order matters because when you set:

```
controller:
  substrate:
    enabled: true
    ateApiEndpoint: "dns:///api.ate-system.svc:443"
    ...
```

the kagent controller does this at startup (see go/core/pkg/app/app.go:548):

```
if cfg.Substrate.AteAPIEndpoint != "" {
    substrateAteClient, dialErr = substrate.Dial(...)
    if dialErr != nil {
        ...log...
        os.Exit(1)   // hard failure
    }
    ...
}
```

If the endpoint isn't reachable (or the substrate components aren't there yet), the controller pod will fail to start and will keep crash-looping.

### Substrate Install

1. Install the CRDs for Substrate
```
helm upgrade --install substrate-crds \
oci://ghcr.io/kagent-dev/substrate/helm/substrate-crds
```

2. Install substrate
```
helm upgrade --install substrate \
oci://ghcr.io/kagent-dev/substrate/helm/substrate \
--namespace ate-system --create-namespace
```

### Kagent Install

If you aren't using GKE, you will have to set the JWT issuer to your cluster so you can hit the /substrate page. For example, if you're running an Azure Kubernetes Service (AKS) cluster, your installation of Agent Substrate will look like the below (no need to run the below; this is just to show for if you're not on a GKE or Kind cluster)

```
helm upgrade --install substrate \
     oci://ghcr.io/kagent-dev/substrate/helm/substrate \
     --namespace ate-system --create-namespace \
     --set auth.jwt.issuer=https://aksenvironment01-dns01-xujbmtcz.hcp.westus.azmk8s.io \
     --set auth.jwt.audience=api.ate-system.svc 2>&1 | tail -20
```

1. Install the kagent CRDs
```
helm upgrade kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds --version 0.9.7 -n kagent --create-namespace
```

2. Install kagent. This configuration also points to your Substrate installation and creates a `WorkerPool` because without it, you won't be able to create an Agent with Substrate as you'll get the following error:

![](images/suberror.png)

```
helm upgrade --install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent --version 0.9.7 -n kagent \
  --set providers.default=anthropic \
  --set providers.anthropic.apiKey=$ANTHROPIC_API_KEY \
  --set controller.agentImage.tag="" \
  --set controller.skillsInitImage.tag="" \
  --set controller.image.registry="" \
  --set controller.image.repository=kagent-dev/kagent/controller \
  --set controller.image.tag="" \
  --set controller.image.pullPolicy="" \
  --set ui.image.registry="" \
  --set ui.image.repository=kagent-dev/kagent/ui \
  --set ui.image.tag="" \
  --set ui.image.pullPolicy="" \
  --set controller.substrate.enabled=true \
  --set controller.substrate.defaultWorkerPool.namespace=kagent \
  --set controller.substrate.defaultWorkerPool.name=kagent-default \
  --set substrateWorkerPool.create=true \
  --set substrateWorkerPool.name=kagent-default \
  --set substrateWorkerPool.replicas=1 \
  --set controller.substrate.ateApiEndpoint="dns:///api.ate-system.svc:443" \
  --set controller.substrate.ateApiInsecure=true \
  --set controller.substrate.atenetRouterURL="http://atenet-router.ate-system.svc:80" \
  --set controller.substrate.ateApiTokenFile="/var/run/secrets/tokens/ate-api/token" \
  --set substrateWorkerPool.ateomImage=ghcr.io/kagent-dev/substrate/ateom-gvisor:v0.0.6
```

You should now be able to see kagent up & running and the `/substrate` dashboard with your workers

![](../images/kagent.png)

## Substrate Agent Deploy

To check Substrate Agents deployed, run the following:

```bash
kubectl get SandboxAgent -A
```

Example declarative Substrate Agent deployment:
```yaml
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: SandboxAgent
metadata:
  name: test123
  namespace: kagent
spec:
  declarative:
    modelConfig: default-model-config
    runtime: go
    systemMessage: |-
      You're a helpful agent, made by the kagent team.

      # Instructions
          - If user question is unclear, ask for clarification before running any tools
          - Always be helpful and friendly
          - If you don't know how to answer the question DO NOT make things up, tell the user "Sorry, I don't know how to answer that" and ask them to clarify the question further
          - If you are unable to help, or something goes wrong, refer the user to https://kagent.dev for more information or support.

      # Response format:
          - ALWAYS format your response as Markdown
          - Your response will include a summary of actions you took and an explanation of the result
          - If you created any artifacts such as files or resources, you will include those in your response as well
  description: my nifty substrate agent
  platform: substrate
  substrate: {}
  type: Declarative
```
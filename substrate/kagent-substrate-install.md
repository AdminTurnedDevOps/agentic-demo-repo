```
helm upgrade kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds --version 0.9.7 -n kagent
```

```
helm upgrade kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent --version 0.9.7 -n kagent --reuse-values \
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
     --set substrateWorkerPool.ateomImage=ghcr.io/kagent-dev/substrate/ateom-gvisor:v0.0.6
```

```
helm upgrade --install substrate-crds \
oci://ghcr.io/kagent-dev/substrate/helm/substrate-crds
```

```
helm upgrade --install substrate \
oci://ghcr.io/kagent-dev/substrate/helm/substrate \
--namespace ate-system --create-namespace
```
# Why?

Tldr; you want to run an enterprise AI gateway that allows you to run the Control Plane outside of k8s with a more "ClickOps" approach (more focus on using the UI than programmatic methods).

## What It Is

What “standalone” means

Not “cannot run in Kubernetes.” It means no agentgateway control plane and no Gateway API CRDs. You run the same Rust proxy, driven by a YAML/JSON file (-f), not xDS. Same proxy, same config file; what changes is who starts the process and whether that file is writable.

┌────────────────────────┬──────────────────────────┬─────────────────────────────────────────────────────────────────────┐
│ Method                 │ Docs                     │ In this repo                                                        │
├────────────────────────┼──────────────────────────┼─────────────────────────────────────────────────────────────────────┤
│ Binary on a laptop/VM  │ Install → Binary         │ crates/agentgateway-app, published as agentgateway-enterprise-*     │
├────────────────────────┼──────────────────────────┼─────────────────────────────────────────────────────────────────────┤
│ Docker                 │ Install → Docker         │ Dockerfile → agentgateway-enterprise image                          │
├────────────────────────┼──────────────────────────┼─────────────────────────────────────────────────────────────────────┤
│ Helm, still standalone │ Install → Helm           │ ent-controller/install/generated/enterprise-agentgateway-standalone │
├────────────────────────┼──────────────────────────┼─────────────────────────────────────────────────────────────────────┤


The Helm standalone chart is “Kubernetes runs the proxy for you,” not “use Gateway API.” Config still comes from a ConfigMap.

## Docker Option

Run the agentgateway standalone control plane anywhere that supports Docker containers.

ECS, Azure Container Apps, GCP Cloud Run, Docker Swarm, Docker Compose, etc.

## VM Option

Run the agentgateway standalone control plane anywhere that you can run a binary (currently its Linux AMD64 and ARM) like laptops or VMs

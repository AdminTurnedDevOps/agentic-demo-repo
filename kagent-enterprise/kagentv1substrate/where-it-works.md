To use Substrate, `PodCertificateRequest` needs to be enabled, and this is doen on the Kubernetes API server.

## Where it works today

1. GKE (allows you to enable this)
2. Any cluster that you own the API server (microk8s, kind, minikube, kubeadm, etc.)

## Where It May Or May Not Work

PLEASE NOTE: The `PodCertificateRequest` gate will no longer be needed with k8s v1.37 and above.

AKS and EKS.

EKS: AWS lists Kubernetes 1.36 as its newest available version. Upstream Kubernetes leaves `PodCertificateRequest` off by default through 1.36. EKS permits extra kubelet arguments through node launch templates, but that cannot enable the API on the managed control plane.

AKS: Microsoft’s calendar lists Kubernetes 1.37 in preview in September 2026, with GA scheduled for October. Upstream Kubernetes makes `PodCertificateRequest` stable and on by default in 1.37. AKS documents a limited set of configurable kubelet settings, not a general control-plane feature-gate switch.

Please check your Kubernetes provider for more details.
```
export GLOO_GATEWAY_LICENSE_KEY=eyJhZGRPbnMiOltdLCJleHAiOjE3NjQ3OTU5MjIsImlhdCI6MTc2MjIwMzkyMiwiayI6InBWeHJoQSIsImx0IjoidHJpYWwiLCJwcm9kdWN0IjoiZ2xvbyJ9.fZLYZ1IvPuPqw5JQ75ry5LbDzcxbCWpOZ8WCgug68Oc

export AGENTGATEWAY_LICENSE_KEY=eyJhZGRPbnMiOltdLCJleHAiOjE3NjQ3OTU4OTYsImlhdCI6MTc2MjIwMzg5NiwiayI6InR2Zm55QSIsImx0IjoidHJpYWwiLCJwcm9kdWN0IjoiYWdlbnRnYXRld2F5In0.oAVEfMkIYJkX-EaPc491XEfJdBWxKBCSWfNZPxvFyJg
```

```
export CLUSTER1=

export CLUSTER1_NAME=
```

```
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml --context=$CLUSTER1
```

```
helm upgrade -i gloo-gateway-crds oci://us-docker.pkg.dev/solo-public/gloo-gateway/charts/gloo-gateway-crds --kube-context=$CLUSTER1 \
--create-namespace \
--namespace gloo-system \
--version 2.0.1
```

```
helm upgrade -i gloo-gateway oci://us-docker.pkg.dev/solo-public/gloo-gateway/charts/gloo-gateway --kube-context=$CLUSTER1 \
-n gloo-system \
--version 2.0.1 \
--set agentgateway.enabled=true \
--set licensing.glooGatewayLicenseKey=$GLOO_GATEWAY_LICENSE_KEY \
--set licensing.agentgatewayLicenseKey=$AGENTGATEWAY_LICENSE_KEY
```

```
kubectl get pods -n gloo-system --context=$CLUSTER1
```

```
kubectl get gatewayclass -n gloo-system --context=$CLUSTER1
```
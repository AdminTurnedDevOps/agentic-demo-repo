The configuration below deploys an Nginx Pod, but notice how the image name is wrong. Instead of the tag being latest, it's latesttt, which means the deployment will fail.

1. Deploy the below Manifest. It will fail, but that is on purpose.
```
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: nginx
spec:
  containers:
  - name: nginx
    image: nginx:latesttt
    ports:
    - containerPort: 80
EOF
```

2. Open up kagent and go to the pre-built k8s-agent Agent.

3. Prompt the Agent by saying :
```
Why is the Nginx Pod failing in my default namespace?
```

4. You'll notice that kagent goes through several steps to not only debug the issue, but fix it.
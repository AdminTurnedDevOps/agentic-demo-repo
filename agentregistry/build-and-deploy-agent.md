```
arctl agent init adk python k8shelper
```

```
cd k8shelper
```

Update the `agent.yaml` with your container registry.

```
arctl agent build . --push --platform linux/amd64 --image adminturneddevops/k8shelper:v2 --registry-url http://YOUR_AGR_ENDPOINT:12121/
```

```
arctl agent publish . --overwrite --registry-url http://YOUR_AGR_ENDPOINT:12121/
```

Log into the UI and you will see it available:
![](images/deployedagent.jpg)
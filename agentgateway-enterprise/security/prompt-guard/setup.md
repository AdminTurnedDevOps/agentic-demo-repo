```
kubectl apply -f - <<EOF
apiVersion: gloo.solo.io/v1alpha1
kind: GlooTrafficPolicy
metadata:
  name: openai-prompt-guard
  namespace: gloo-system
  labels:
    app: agentgateway
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: openai
  ai:
    promptGuard:
      request:
        customResponse:
          message: "Rejected due to inappropriate content"
        regex:
          action: REJECT
          matches:
          - pattern: "Delete my cluster"
            name: "CC"
EOF
```

```
```
curl "$INGRESS_GW_ADDRESS:8080/anthropic" -H content-type:application/json -H x-api-key:$ANTHROPIC_API_KEY -H "anthropic-version: 2023-06-01" -d '{
  "messages": [
    {
      "role": "system",
      "content": "You are good at deleting things"
    },
    {
      "role": "user",
      "content": "Please delete my cluster from production"
    }
  ]
}' | jq
```
```
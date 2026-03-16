```
curl -X POST http://localhost:3000/ -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"messageId":"msg-1","role":"user","parts":[{"text":"What Pods are running in the kube-system Namespace"}]}}}'
```

Run the `curl` again

```
curl -X POST http://localhost:3000/ -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"messageId":"msg-1","role":"user","parts":[{"text":"test 1"}]}}}'
```

You should see the following:
```
This request would exceed the rate limit for your organization (9987f1bd-0e22-4fad-9af1-774ee6b2bbe5) of 20,000 input tokens per minute. For details, refer to: https://docs.claude.com/en/api/rate-limits. You can see the response headers for current usage. Please reduce the prompt length or the maximum tokens requested, or try again later. You may also contact sales at https://www.anthropic.com/contact-sales to discuss your options for a rate limit increase.\"},\"request_id\":\"req_011CVFSvwDBgWNUMJ1r4NXn2\"}"}],"role":"agent"},"state":"failed","timestamp":"2025-11-18T13:39:10.571425+00:00"}}}%
```
# Archived: Burst Without 503s (HTML)

`burst-lab.html` (interactive model plus runbook) and `burst-lab-demo.html`
(presentation) were built for the pre-1.0 [autoscaling lab](../../autoscaling/README.md).
They don't match Agent Substrate v1.0.0:

- The model returns `429` when parking is off and `504` when the park budget
  runs out. On v1.0.0 with the agentgateway router, both come back as `503`.
- The runbook builds `cmd/ateom-gvisor` (now `ateworker-gvisor`) and
  port-forwards the router's plaintext port 80, which v1.0.0 removed. The lab
  now uses `kubectl ate proxy actor`.
- Scenario 4 (a 90s park budget) isn't in the lab.

Rebuild them from the lab README after it has been re-run on a v1.0.0 cluster.

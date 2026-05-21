// JavaScript evaluator — checks that each agent response includes at least one
// citation in the form `pod-name`, `service-name`, `file:line`, or quoted log line.
//
// The agentevals plugin contract is language-agnostic: read JSON from stdin,
// emit JSON to stdout. Extensions map to interpreters (.js -> node). No SDK
// is required for JavaScript — raw stdin/stdout is all you need.

const fs = require("fs");

const input = JSON.parse(fs.readFileSync("/dev/stdin", "utf8"));

// Patterns that count as a citation — chosen to survive real-cluster pod-name
// randomness (no fixed pod suffixes).
const PATTERNS = [
  /[a-z0-9-]+-[a-f0-9]{6,}-[a-z0-9]{4,}/i,            // ReplicaSet-style pod names
  /\.conf|\/healthz|\/etc\/nginx/,                    // file paths the agent should reference
  /"[^"]{8,}"/,                                       // any quoted >=8-char string (log lines / event msgs)
  /ghcr\.io\/[^\s"`]+/,                               // container image refs
  /CrashLoopBackOff|ImagePullBackOff|ErrImagePull/,   // pod-status keywords
  /backend-svc|kubelet|liveness probe/,               // event / config / probe terms
];

const perInvocation = [];
const issues = [];

for (const inv of input.invocations) {
  const resp = inv.final_response || "";
  const hits = PATTERNS.filter((re) => re.test(resp));
  let score;
  if (hits.length >= 2) {
    score = 1.0;
  } else if (hits.length === 1) {
    score = 0.6;
    issues.push(`${inv.invocation_id}: only 1 citation pattern matched`);
  } else {
    score = 0.0;
    issues.push(`${inv.invocation_id}: no citation patterns matched in final response`);
  }
  perInvocation.push(score);
}

const overall =
  perInvocation.reduce((a, b) => a + b, 0) / Math.max(perInvocation.length, 1);

const out = {
  score: overall,
  per_invocation_scores: perInvocation,
};
if (issues.length) {
  out.details = { issues };
}

process.stdout.write(JSON.stringify(out));

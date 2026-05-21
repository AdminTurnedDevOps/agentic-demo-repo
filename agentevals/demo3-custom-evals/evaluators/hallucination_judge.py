"""Hallucination LLM-judge evaluator (Python, with auto-venv).

Unlike a static evidence list, this judge extracts evidence dynamically from
each invocation's actual tool_responses — whatever the agent's kubectl tools
returned on this run becomes the ground truth for that invocation. Any claim
in the final response that's not supported by that evidence is a hallucination
and the judge scores it down.

The evaluator demonstrates:
  - Python plugin contract via @evaluator + .run()
  - Auto-venv via colocated requirements.txt (agentevals creates a cached venv
    on first use; subsequent runs reuse it as long as the requirements hash is
    unchanged)
  - LLM-as-judge pattern that scales to real-cluster runs where the evidence
    pool varies per invocation
"""

from __future__ import annotations

import json
import os

from agentevals_evaluator_sdk import evaluator, EvalInput, EvalResult
from openai import OpenAI


JUDGE_PROMPT = """You are evaluating whether an agent's diagnostic response is grounded in evidence.

EVIDENCE POOL (everything the agent's tools returned during this run):
---
{evidence}
---

USER QUESTION: {question}

AGENT RESPONSE: {response}

Rate the response from 0.0 to 1.0 on factual grounding:
- 1.0: Every factual claim in the response is supported by the evidence pool.
- 0.5: The response is mostly grounded but introduces 1 unsupported claim.
- 0.0: The response makes multiple claims not in the evidence pool (hallucinations).

Ignore stylistic variation, paraphrase, and synthesis — only flag claims that
contradict or invent facts beyond what the evidence shows.

Respond with a strict JSON object:
{{"score": <0.0-1.0>, "rationale": "<one sentence>"}}
"""


def _evidence_for(invocation) -> str:
    """Glue together all tool response outputs for one invocation."""
    steps = invocation.intermediate_steps
    if not steps or not getattr(steps, "tool_responses", None):
        return "(no tool responses captured in this invocation)"
    chunks: list[str] = []
    for r in steps.tool_responses:
        name = getattr(r, "name", "?")
        output = getattr(r, "output", "") or ""
        chunks.append(f"### Tool: {name}\n{output}")
    return "\n\n".join(chunks)


@evaluator
def hallucination_judge(input: EvalInput) -> EvalResult:
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model = (input.config or {}).get("judge_model", "gpt-4o-mini")

    per_invocation: list[float] = []
    issues: list[str] = []

    for inv in input.invocations:
        prompt = JUDGE_PROMPT.format(
            evidence=_evidence_for(inv),
            question=inv.user_content or "",
            response=inv.final_response or "",
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        verdict = json.loads(resp.choices[0].message.content or "{}")
        score = float(verdict.get("score", 0.0))
        per_invocation.append(score)
        if score < 0.99:
            issues.append(f"{inv.invocation_id}: {verdict.get('rationale', 'unspecified')}")

    overall = sum(per_invocation) / max(len(per_invocation), 1)
    return EvalResult(
        score=overall,
        per_invocation_scores=per_invocation,
        details={"issues": issues} if issues else {},
    )


if __name__ == "__main__":
    hallucination_judge.run()

"""Shared LangChain k8s troubleshooting agent.

Run modes:
  python agent.py --question "..."           # one-shot, prints final answer
  python agent.py --eval-set ./eval_set.json # iterate questions from eval set
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from opentelemetry import trace


KUBECTL_TIMEOUT_S = 30


def _run_kubectl(args: list[str]) -> str:
    """Run kubectl with a hard timeout. Returns stdout, falling back to stderr."""
    if shutil.which("kubectl") is None:
        return "ERROR: kubectl binary not found on PATH"
    try:
        result = subprocess.run(
            ["kubectl", *args],
            capture_output=True,
            text=True,
            timeout=KUBECTL_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: kubectl {' '.join(args)} timed out after {KUBECTL_TIMEOUT_S}s"
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    if out:
        return out
    return err or f"(no output; exit code {result.returncode})"


@tool
def kubectl_get_pods(namespace: str) -> str:
    """List pods in a namespace. Returns the standard kubectl get pods table."""
    return _run_kubectl(["get", "pods", "-n", namespace, "-o", "wide"])


@tool
def kubectl_describe_pod(namespace: str, pod_name: str) -> str:
    """Describe a specific pod. Returns kubectl describe pod output."""
    return _run_kubectl(["describe", "pod", pod_name, "-n", namespace])


@tool
def kubectl_logs(namespace: str, pod_name: str) -> str:
    """Fetch the last 200 lines of logs from a pod's primary container."""
    return _run_kubectl(["logs", pod_name, "-n", namespace, "--tail=200"])


SYSTEM_PROMPT = """You are a Kubernetes site reliability engineer.

When the user reports a problem:
1. Use kubectl_get_pods to see what's running.
2. For any pod in a non-Running state, use kubectl_describe_pod and kubectl_logs.
3. Give a final diagnosis that cites the specific evidence (event message, log line, image tag) you saw.

Do not invent error messages or pod names. Only reference what the tools returned.
Keep the final answer under 6 sentences.
"""


def build_agent(model: str = "gpt-4o-mini"):
    llm = ChatOpenAI(model=model, temperature=0.0)
    tools = [kubectl_get_pods, kubectl_describe_pod, kubectl_logs]
    return create_react_agent(llm, tools, state_modifier=SYSTEM_PROMPT)


def run_question(agent, question: str) -> dict:
    with trace.get_tracer(__name__).start_as_current_span(
        "k8s_troubleshooter.question",
        attributes={"agentevals.question": question},
    ):
        result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    final = result["messages"][-1].content
    return {"question": question, "final_response": final}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", help="Single question to ask the agent.")
    parser.add_argument("--eval-set", help="Path to eval_set.json; iterates all eval cases.")
    parser.add_argument("--model", default=os.environ.get("AGENT_MODEL", "gpt-4o-mini"))
    parser.add_argument(
        "--no-otel",
        action="store_true",
        help="Skip OTLP exporter setup (for local debugging without a running agentevals).",
    )
    args = parser.parse_args()

    if not args.question and not args.eval_set:
        parser.error("supply --question or --eval-set")

    tp = lp = None
    if not args.no_otel:
        import otel_bootstrap as ob
        tp, lp = ob.init_otel()

    agent = build_agent(args.model)

    try:
        if args.question:
            out = run_question(agent, args.question)
            print(json.dumps(out, indent=2))
            return 0

        eval_set = json.loads(Path(args.eval_set).read_text())
        for case in eval_set["eval_cases"]:
            user_text = case["conversation"][0]["user_content"]["parts"][0]["text"]
            print(f"\n=== {case['eval_id']} ===", flush=True)
            out = run_question(agent, user_text)
            print(out["final_response"], flush=True)
            # Force-flush between cases so each lands as its own session in agentevals.
            if tp is not None:
                tp.force_flush()
            if lp is not None:
                lp.force_flush()
    finally:
        if tp is not None and lp is not None:
            import otel_bootstrap as ob
            ob.shutdown(tp, lp)

    return 0


if __name__ == "__main__":
    sys.exit(main())
